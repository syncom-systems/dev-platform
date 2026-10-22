#!/usr/bin/env python3
"""Routine dev-platform release, run by the owner's agent (ADR 0024, docs/release-management.md).

  python3 tools/release.py ready   [--version V] [--kind K ...] [--skip-continuity]   # READY TO RELEASE / BLOCKED
  python3 tools/release.py publish  --version V  [--kind K ...] [--trailer LINE ...]  # the whole routine release
  python3 tools/release.py records  --version V  [--trailer LINE ...]                 # evidence and tap only

`ready` changes nothing. `publish` finalizes the version (version, predecessor pin, release notes) in a pull request
and merges it once its required checks pass, pushes the annotated tag on that exact merge commit (which starts
release.yml: build, attestations, continuity, independent verification, publication), checks the published release,
then runs `records`: the release identity and evidence go to `releases/<V>/` and the Homebrew formula to the tap, each
through a pull request that merges when its checks pass. Every step re-checks what it relies on and is skipped when
already done, so an interrupted `publish` is resumed by running it again. The first failure stops it with the reason;
nothing is retried around a failed check or verification. It uses the caller's `gh` identity and git checkout only:
no stored state, token or approval of its own.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from dev_platform import lifecycle  # noqa: E402

REPO = "syncom-systems/dev-platform"
TAP = "syncom-systems/homebrew-dev-platform"
PREPARED = ("CHANGELOG.md", "src/dev_platform/__init__.py", "trust/policy.json")
PINNED = {  # identity.json verifier_pins: what consumers and the tap check at the release revision
    "verify_release.py_sha256": "tools/verify_release.py",
    "trust_policy_sha256": "trust/policy.json",
    "install_release.py_sha256": "tools/install_release.py",
    "verify_app_release.py_sha256": "tools/verify_app_release.py",
    "verify_platform_current.py_sha256": "tools/verify_platform_current.py",
    "verify_consumer_evidence.py_sha256": "tools/verify_consumer_evidence.py",
    "consumer_run.py_sha256": "tools/consumer_run.py",
    "homebrew_formula.py_sha256": "tools/homebrew_formula.py",
}
ASSETS = (
    "tar.gz",
    "tar.gz.sha256",
    "sbom.cdx.json",
    "build-environment.json",
    "continuity.json",
    "verification.json",
)


class Stop(Exception):
    """A blocker or failure: reported, never worked around."""


def sh(argv, *, cwd=ROOT, check=True, capture=True, timeout: float | None = 600, **kw) -> str:
    """Run a command; `timeout=None` only for the long steps (tests, builds, continuity)."""
    try:
        p = subprocess.run(argv, cwd=cwd, capture_output=capture, text=True, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        raise Stop(f"{' '.join(map(str, argv[:4]))} did not finish within {timeout:.0f}s") from None
    if check and p.returncode:
        raise Stop(
            f"{' '.join(map(str, argv[:4]))} failed ({p.returncode}): {(p.stderr or p.stdout or '').strip()[-600:]}"
        )
    return (p.stdout or "").strip() if capture else ""


def gh_json(*args):
    return json.loads(sh(["gh", *args]) or "null")


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def say(msg: str) -> None:
    print(f"release: {msg}", flush=True)


# ---------------------------------------------------------------- pure parts (tested)


def next_version(previous: str, kinds: list[str], policy: dict) -> str:
    """The smallest version the versioning policy allows after `previous` for these change kinds."""
    a, b, c, _ = lifecycle.parse_version(previous)
    level = lifecycle.required_level(kinds, policy)  # during 0.x an incompatible change is a (declared) minor
    return {"major": f"{a + 1}.0.0", "minor": f"{a}.{b + 1}.0", "patch": f"{a}.{b}.{c + 1}"}[level]


def changelog_release(text: str, version: str) -> str:
    """Move the `## Unreleased` notes under `## <version>`; empty notes are a blocker."""
    m = re.search(r"^## Unreleased\n(.*?)(?=^## )", text, re.M | re.S)
    if not m:
        raise Stop("CHANGELOG.md has no `## Unreleased` section followed by a release")
    if re.search(rf"^## {re.escape(version)}\b", text, re.M):
        raise Stop(f"CHANGELOG.md already has a {version} section")
    notes = m.group(1).strip("\n")
    if not notes.strip():
        raise Stop("CHANGELOG.md `## Unreleased` is empty: the release needs notes")
    return text[: m.start()] + f"## Unreleased\n\n## {version}\n{notes}\n\n" + text[m.end() :]


def prepare(root: Path, version: str, predecessor: dict) -> None:
    """Finalize the version in a checkout or export: __version__, the continuity predecessor, the release notes.
    Everything is computed before anything is written, so a blocker leaves the files untouched."""
    init, pol_file, cl = (
        root / p for p in ("src/dev_platform/__init__.py", "trust/policy.json", "CHANGELOG.md")
    )
    notes = changelog_release(cl.read_text(), version)
    code, n = re.subn(r'^__version__ = "[^"]+"', f'__version__ = "{version}"', init.read_text(), flags=re.M)
    if n != 1:
        raise Stop("src/dev_platform/__init__.py has no single __version__ line")
    pol = json.loads(pol_file.read_text())
    pol["continuity"] = {
        "predecessor": {k: predecessor[k] for k in ("version", "archive_sha256", "tree_digest")}
    }
    cl.write_text(notes)
    init.write_text(code)
    pol_file.write_text(json.dumps(pol, indent=2) + "\n")


def is_prepared(root: Path, version: str, predecessor: dict) -> bool:
    init = (root / "src/dev_platform/__init__.py").read_text()
    pred = (json.loads((root / "trust/policy.json").read_text()).get("continuity") or {}).get(
        "predecessor"
    ) or {}
    return f'__version__ = "{version}"' in init and pred.get("version") == predecessor["version"]


def identity(version: str, rev: str, ci: dict, continuity: dict | None, release: dict, run_url: str,
             pins: dict) -> dict:  # fmt: skip
    """releases/<V>/identity.json: what a consumer copies into dev-platform.release-pins.json."""
    subj, state = ci["subject"], ci["acceptance"]["state"]
    doc = {
        "version": version,
        "state": state,
        "git_tag": f"v{version}",
        "source_revision": rev,
        "archive": subj["archive"],
        "archive_sha256": subj["archive_sha256"],
        "tree_digest_pin": subj["tree_digest"],
        "release_workflow_run": run_url,
        "signer": f"{REPO}/.github/workflows/release.yml@refs/tags/v{version}",
        "github_release": {k: release[k] for k in ("immutable", "prerelease", "title")},
        "verifier_pins": pins,
    }
    if continuity:
        p, st = continuity["predecessor"], continuity["stage"]
        doc["continuity"] = {"predecessor": p["version"], "predecessor_state": p["verification"]["state"],
                             "stage": st["name"], "admission": st["admission"]}  # fmt: skip
    return doc


def verifier_pins(read) -> dict:
    """sha256 of each pinned tool at the release revision; `read(path)` returns its bytes."""
    return {name: hashlib.sha256(read(path)).hexdigest() for name, path in PINNED.items()}


# ---------------------------------------------------------------- GitHub and git facts


def published_versions() -> list[str]:
    rels = gh_json("release", "list", "--repo", REPO, "--limit", "100", "--json", "tagName,isDraft")
    return [r["tagName"][1:] for r in rels if not r["isDraft"] and lifecycle.SEMVER.match(r["tagName"][1:])]


def predecessor_of(version: str | None) -> dict:
    """The newest published stable release below `version`, with its identity from its recorded evidence."""
    cands = [v for v in published_versions() if lifecycle.parse_version(v)[3] is None]
    if version:
        cands = [v for v in cands if lifecycle._precedence(v) < lifecycle._precedence(version)]
    if not cands:
        raise Stop("no published stable release to continue from")
    prev = max(cands, key=lifecycle._precedence)
    ident_file = ROOT / "releases" / prev / "identity.json"
    if not ident_file.is_file():
        raise Stop(
            f"releases/{prev}/identity.json is missing: run `tools/release.py records --version {prev}` first"
        )
    ident = json.loads(ident_file.read_text())
    asset = gh_json("api", f"repos/{REPO}/releases/tags/v{prev}")
    digest = next((a["digest"] for a in asset["assets"] if a["name"] == f"dev-platform-{prev}.tar.gz"), None)
    if digest != f"sha256:{ident['archive_sha256']}":
        raise Stop(
            f"the published v{prev} archive ({digest}) is not the one releases/{prev}/identity.json records"
        )
    return {
        "version": prev,
        "archive_sha256": ident["archive_sha256"],
        "tree_digest": ident["tree_digest_pin"],
    }


def derived_kinds(previous: str) -> list[str]:
    with tempfile.TemporaryDirectory() as td:
        old = Path(td)
        (old / "manifest.json").write_text(sh(["git", "show", f"v{previous}:toolchains/manifest.json"]))
        (old / "schemas").mkdir()
        for name in sh(["git", "ls-tree", "--name-only", f"v{previous}", "schemas/"]).split():
            (old / name).write_text(sh(["git", "show", f"v{previous}:{name}"]))
        new_manifest = json.loads((ROOT / "toolchains/manifest.json").read_text())
        return sorted(set(lifecycle.diff_manifests(json.loads((old / "manifest.json").read_text()), new_manifest))
                      | set(lifecycle.diff_schemas(old / "schemas", ROOT / "schemas")))  # fmt: skip


def git_state() -> dict:
    sh(["git", "fetch", "-q", "--tags", "origin"])
    return {"branch": sh(["git", "branch", "--show-current"]), "head": sh(["git", "rev-parse", "HEAD"]),
            "main": sh(["git", "rev-parse", "origin/main"]), "dirty": sh(["git", "status", "--porcelain"])}  # fmt: skip


def tag_commit(version: str) -> str | None:
    out = sh(["git", "ls-remote", "--tags", "origin", f"refs/tags/v{version}^{{}}"])
    return out.split()[0] if out else None


# ---------------------------------------------------------------- phase 1


def build_twice(src: Path, version: str, rev: str) -> dict:
    digests = []
    for i in (1, 2):
        out = src.parent / f"build{i}"
        env = {**os.environ, "PYTHONPATH": str(src / "src")}
        py = [sys.executable, "-m", "dev_platform"]
        sh([*py, "release", "build", "--version", version, "--out", str(out), "--source-uri",
            f"https://github.com/{REPO}", "--source-revision", rev], cwd=src, env=env, timeout=None)  # fmt: skip
        arc = out / f"dev-platform-{version}.tar.gz"
        sh([*py, "release", "pack", str(out / version), "--out", str(arc)], cwd=src, env=env, timeout=None)
        digests.append((sha256(arc), sh([*py, "digest", str(out / version)], cwd=src, env=env)))
    if digests[0] != digests[1]:
        raise Stop(f"the build is not deterministic: {digests}")
    return {"archive_sha256": digests[0][0], "tree_digest": digests[0][1]}


def ready(a) -> dict:
    problems, checks, info = [], [], {}

    def check(name, fn):
        try:
            res = fn()
        except Exception as e:  # any surprise is a blocker, never a pass
            problems.append(f"{name}: {e}")
            return None
        checks.append(name)
        return res

    st = git_state()
    info["commit"] = st["head"]
    if st["dirty"]:
        problems.append("working tree has uncommitted changes")
    if st["head"] != st["main"]:
        problems.append(f"HEAD {st['head'][:12]} is not origin/main {st['main'][:12]}")
    pred = check("predecessor identity", lambda: predecessor_of(a.version))
    if not pred:
        return {"ready": False, "problems": problems, "checks": checks, **info}
    policy = lifecycle_policy()
    kinds = sorted(
        set(a.kind) | set(check("compatibility kinds", lambda: derived_kinds(pred["version"])) or [])
    )
    version = check("next version", lambda: a.version or next_version(pred["version"], kinds, policy))
    if not version:
        return {"ready": False, "problems": problems, "checks": checks, **info}
    info.update(version=version, previous=pred["version"], kinds=kinds)
    vp = check("version policy", lambda: lifecycle.check_version(pred["version"], version, kinds, policy))
    problems += [f"version: {p}" for p in vp or []]
    if vp == []:
        checks.append(f"version {pred['version']} -> {version} ({', '.join(kinds) or 'no declared kinds'})")
    if tag_commit(version) or version in published_versions():
        problems.append(f"v{version} already exists")
    check("unit tests", lambda: sh([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                                    env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=None))  # fmt: skip
    check("lint", lambda: (sh(["uvx", "--from", "ruff==0.17.0", "ruff", "check", "."]),
                           sh(["uvx", "--from", "ruff==0.17.0", "ruff", "format", "--check", "."])))  # fmt: skip
    check("docs", lambda: sh([sys.executable, "tools/check_docs.py"]))
    with tempfile.TemporaryDirectory(prefix="release-ready-") as td:
        src = Path(td) / "src"
        src.mkdir()
        # an export of the tracked files only: an ignored local file can never reach the archive
        sh(["bash", "-c", f"git archive HEAD | tar -x -C {shlex.quote(str(src))}"])
        check("release notes and version", lambda: prepare(src, version, pred))
        built = check("deterministic build (two clean builds)", lambda: build_twice(src, version, st["head"]))
        if built:
            info["build_at_head"] = built
        if not a.skip_continuity:
            check(f"continuity ({pred['version']} runs the full stage over this source)",
                  lambda: continuity(Path(td), src, st["head"], version, (built or {}).get("archive_sha256")))  # fmt: skip
    return {"ready": not problems, "problems": problems, "checks": checks, **info}


def continuity(td: Path, prepared: Path, rev: str, version: str, archive_sha: str | None) -> None:
    """What release.yml's continuity job does: the predecessor verifies itself, then runs its full stage here."""
    pol, out = td / "policy.json", td / "continuity.json"
    pol.write_text((prepared / "trust/policy.json").read_text())
    sh([sys.executable, "tools/run_continuity.py", "--policy", str(pol), "--source", ".", "--source-revision", rev,
        "--version", version, "--archive-sha256", archive_sha or "0" * 64, "--out", str(out)], timeout=None)  # fmt: skip
    doc = json.loads(out.read_text())
    v, s = doc["predecessor"]["verification"], doc["stage"]
    if not v["all_checks_passed"] or s["exit"] != 0 or s["admission"] != "admitted":
        raise Stop(f"predecessor verification {v}, full stage exit {s['exit']}, admission {s['admission']}")


def lifecycle_policy() -> dict:
    from dev_platform import planning

    return planning.load_policy(ROOT / "planning" / "release-policy.json")


def verdict(r: dict) -> str:
    if r["ready"]:
        lines = [f"READY TO RELEASE — v{r['version']} (after {r['previous']}; commit {r['commit'][:12]})"]
        lines += [f"  passed: {c}" for c in r["checks"]]
        b = r.get("build_at_head")
        if b:
            lines.append(f"  build at this commit: archive {b['archive_sha256'][:16]}…, tree {b['tree_digest'][:16]}… "
                         "(the release is built from the merge commit, so its digests will differ)")  # fmt: skip
        return "\n".join(lines)
    return "\n".join(["BLOCKED", *[f"  - {p}" for p in r["problems"]]])


# ---------------------------------------------------------------- phase 2


def wait_and_merge(pr: str, head: str, *, repo: str) -> None:
    say(f"waiting for the required checks of {repo}#{pr}")
    for attempt in range(10):
        p = subprocess.run(["gh", "pr", "checks", pr, "--repo", repo, "--watch", "--fail-fast", "--interval", "30"],
                           capture_output=True, text=True)  # fmt: skip
        if p.returncode == 0:
            break
        if "no checks reported" in (p.stderr + p.stdout) and attempt < 9:
            time.sleep(20)
            continue
        raise Stop(f"checks of {repo}#{pr} did not pass:\n{(p.stdout + p.stderr).strip()[-1500:]}")
    sh(["gh", "pr", "merge", pr, "--repo", repo, "--merge", "--match-head-commit", head])
    say(f"merged {repo}#{pr}")


def open_pr(repo: str, branch: str) -> tuple[str, str] | None:
    """(number, head sha) of the open pull request from `branch`, if a previous run already opened it."""
    prs = gh_json(
        "pr", "list", "--repo", repo, "--head", branch, "--state", "open", "--json", "number,headRefOid"
    )
    return (str(prs[0]["number"]), prs[0]["headRefOid"]) if prs else None


def propose(branch: str, write, paths: list[str], title: str, body: str, trailers: list[str]) -> None:
    """Commit `write()`'s changes on a new branch, open a pull request, return to main, merge when checks pass."""
    pr = open_pr(REPO, branch)
    if not pr:
        sh(["git", "switch", "-q", "-c", branch])
        try:
            write()
            sh(["git", "add", "--", *paths])
            sh(
                [
                    "git",
                    "commit",
                    "-q",
                    "-m",
                    title + ("\n\n" + "\n".join(t for t in trailers if ": " in t) if trailers else ""),
                ]
            )
            sh(["git", "push", "-q", "-u", "origin", branch])
            url = sh(["gh", "pr", "create", "--repo", REPO, "--base", "main", "--head", branch, "--title", title,
                      "--body", body + ("\n\n" + "\n".join(trailers) if trailers else "")])  # fmt: skip
            pr = (url.rsplit("/", 1)[-1], sh(["git", "rev-parse", "HEAD"]))
        finally:
            sh(["git", "switch", "-q", "main"])
    wait_and_merge(*pr, repo=REPO)
    sh(["git", "pull", "-q", "--ff-only", "origin", "main"])
    sh(["git", "branch", "-q", "-D", branch], check=False)
    sh(["git", "push", "-q", "origin", "--delete", branch], check=False)


def finalize_version(a, pred: dict) -> str:
    """The merged commit that declares `a.version`; prepares and merges it when main does not yet."""
    st = git_state()
    if st["dirty"] or st["branch"] != "main" or st["head"] != st["main"]:
        raise Stop("start from a clean, up-to-date main")
    if is_prepared(ROOT, a.version, pred):
        say(f"main already declares {a.version} with predecessor {pred['version']}")
        return st["main"]
    propose(f"release/{a.version}", lambda: prepare(ROOT, a.version, pred), list(PREPARED),
            f"Version {a.version}; continuity predecessor {pred['version']}",
            f"Finalizes {a.version}: `__version__`, the continuity predecessor {pred['version']} (its published "
            "identity) and the release notes from `## Unreleased`. Opened by `tools/release.py publish`.",
            a.trailer)  # fmt: skip
    merged = sh(["git", "rev-parse", "HEAD"])
    changed = sorted(sh(["git", "diff", "--name-only", st["main"], merged]).split())
    if changed != sorted(PREPARED):
        raise Stop(f"the merged change touches {changed}, not exactly {sorted(PREPARED)}")
    return merged


def tag_and_publish(version: str, rev: str) -> dict:
    at = tag_commit(version)
    if at and at != rev:
        raise Stop(f"v{version} exists on {at}, not on {rev}")
    if not at:
        sh(["git", "merge-base", "--is-ancestor", rev, "origin/main"])
        local = sh(["git", "rev-parse", "-q", "--verify", f"refs/tags/v{version}^{{commit}}"], check=False)
        if local and local != rev:
            raise Stop(f"a local tag v{version} points to {local}, not {rev}: remove it and run again")
        if not local:
            sh(["git", "tag", "-a", f"v{version}", "-m", f"dev-platform {version}", rev])
        sh(["git", "push", "-q", "origin", f"v{version}"])
        say(f"pushed v{version} on {rev}; release.yml publishes it")
    run = None
    for _ in range(30):
        runs = gh_json("run", "list", "--repo", REPO, "--workflow", "release.yml", "--limit", "20", "--json",
                       "databaseId,headBranch,headSha,status,conclusion,url")  # fmt: skip
        run = next((r for r in runs if r["headBranch"] == f"v{version}" and r["headSha"] == rev), None)
        if run:
            break
        time.sleep(10)
    if not run:
        raise Stop(f"no release.yml run appeared for v{version}")
    if run["status"] != "completed":
        say(f"watching {run['url']}")
        subprocess.run(["gh", "run", "watch", str(run["databaseId"]), "--repo", REPO, "--interval", "30"],
                       capture_output=True)  # fmt: skip
        run = gh_json(
            "run", "view", str(run["databaseId"]), "--repo", REPO, "--json", "conclusion,url,databaseId"
        )
    if run.get("conclusion") != "success":
        raise Stop(f"release.yml did not succeed ({run.get('conclusion')}): {run['url']}")
    return run


def check_published(version: str, rev: str, d: Path) -> tuple[dict, dict | None, dict]:
    """Download the assets and re-establish everything consumers rely on; independent of the workflow's verdict."""
    rel = gh_json("api", f"repos/{REPO}/releases/tags/v{version}")
    meta = {"immutable": rel.get("immutable") is True, "prerelease": rel["prerelease"], "title": rel["name"]}
    if not meta["immutable"]:
        raise Stop(f"v{version} is not an immutable release")
    sh(["gh", "release", "download", f"v{version}", "--repo", REPO, "--dir", str(d), "--clobber"])
    for a in rel["assets"]:
        if a.get("digest") != f"sha256:{sha256(d / a['name'])}":
            raise Stop(f"asset {a['name']} differs from GitHub's digest")
    arc = d / f"dev-platform-{version}.tar.gz"
    ci = json.loads((d / f"dev-platform-{version}.verification.json").read_text())
    if ci["subject"]["archive_sha256"] != sha256(arc) or ci["expected"]["source_revision"] != rev:
        raise Stop("the CI verification record is not about this archive and revision")
    sh(["gh", "release", "verify", f"v{version}", "--repo", REPO])
    sh(["gh", "release", "verify-asset", f"v{version}", str(arc), "--repo", REPO])
    # the verifier and policy of the tagged revision, run here, outside CI
    tools = d / "pinned"
    tools.mkdir(exist_ok=True)
    for p in ("tools/verify_release.py", "trust/policy.json"):
        (tools / Path(p).name).write_bytes(subprocess.run(["git", "show", f"{rev}:{p}"], cwd=ROOT,
                                                          capture_output=True, check=True).stdout)  # fmt: skip
    cont = d / f"dev-platform-{version}.continuity.json"
    ind_file = d / "verification.independent.json"
    sh([sys.executable, "-I", str(tools / "verify_release.py"), str(arc), "--version", version, "--source-revision", rev,
        "--archive-sha256", ci["subject"]["archive_sha256"], "--tree-digest", ci["subject"]["tree_digest"],
        "--environment", str(d / f"dev-platform-{version}.build-environment.json"),
        *(["--continuity", str(cont)] if cont.is_file() else []), "--policy", str(tools / "policy.json"),
        "--out", str(ind_file)])  # fmt: skip
    ind = json.loads(ind_file.read_text())
    want = "pre-release" if "-" in version else "verified"
    for name, doc in (("CI", ci), ("independent", ind)):
        if doc["acceptance"]["state"] not in (
            want,
            "verified-unaccepted",
        ):  # the latter: releases before 0.12.0
            raise Stop(f"{name} verification state is {doc['acceptance']['state']}")
        if doc["subject"] != ci["subject"]:
            raise Stop("the independent verification disagrees with CI about the subject")
    return ci, json.loads(cont.read_text()) if cont.is_file() else None, meta


def records(a) -> dict:
    version = a.version
    rev = tag_commit(version)
    if not rev:
        raise Stop(f"v{version} is not tagged")
    st = git_state()
    if st["dirty"] or st["branch"] != "main" or st["head"] != st["main"]:
        raise Stop("start from a clean, up-to-date main")
    with tempfile.TemporaryDirectory(prefix=f"release-{version}-") as td:
        d = Path(td)
        ci, cont, meta = check_published(version, rev, d)
        out = ROOT / "releases" / version
        report = {"version": version, "revision": rev, "state": ci["acceptance"]["state"],
                  "archive_sha256": ci["subject"]["archive_sha256"], "tree_digest": ci["subject"]["tree_digest"],
                  "github_release": meta}  # fmt: skip
        if not (out / "identity.json").is_file():
            runs = gh_json("run", "list", "--repo", REPO, "--workflow", "release.yml", "--limit", "50", "--json",
                           "headBranch,headSha,conclusion,url")  # fmt: skip
            run = next((r["url"] for r in runs if r["headBranch"] == f"v{version}" and r["headSha"] == rev
                        and r["conclusion"] == "success"), None)  # fmt: skip
            if not run:
                raise Stop(f"no successful release.yml run for v{version} on {rev}")
            pins = verifier_pins(lambda p: subprocess.run(["git", "show", f"{rev}:{p}"], cwd=ROOT,
                                                         capture_output=True, check=True).stdout)  # fmt: skip
            ident = identity(version, rev, ci, cont, meta, run, pins)
            propose(f"records/{version}", lambda: write_records(out, d, version, ident, cont is not None),
                    [str(out.relative_to(ROOT))], f"Release records: {version}",
                    f"Identity, verification records and Homebrew formula of the published v{version} "
                    f"({ci['acceptance']['state']}). Generated by `tools/release.py records`.", a.trailer)  # fmt: skip
        else:
            say(f"releases/{version}/ is already recorded")
        if meta["prerelease"]:
            report["tap"] = "not updated: pre-releases are not offered through Homebrew"
        else:
            report["tap"] = update_tap(version, a.trailer)
    return report


def write_records(out: Path, d: Path, version: str, ident: dict, has_continuity: bool) -> None:
    (out / "homebrew").mkdir(parents=True, exist_ok=True)
    (out / "identity.json").write_text(json.dumps(ident, indent=2) + "\n")
    shutil.copyfile(d / f"dev-platform-{version}.verification.json", out / "verification.ci.json")
    shutil.copyfile(d / "verification.independent.json", out / "verification.independent.json")
    shutil.copyfile(d / f"dev-platform-{version}.build-environment.json", out / "build-environment.json")
    if has_continuity:
        shutil.copyfile(d / f"dev-platform-{version}.continuity.json", out / "continuity.json")
    sh([sys.executable, "tools/homebrew_formula.py", "--identity", str(out / "identity.json"), "--out",
        str(out / "homebrew" / "dev-platform.rb")])  # fmt: skip
    i = ident
    (out / "README.md").write_text(f"""# {version} ({i["state"]})

Published by release.yml ({i["release_workflow_run"]}) from tag `v{version}` on `{i["source_revision"]}`. Generated
by `tools/release.py records`. Identity and pins: `identity.json`. Records: `verification.ci.json` (the workflow's),
`verification.independent.json` (the tagged verifier and policy, re-run outside CI), `build-environment.json`,
{"`continuity.json`, " if has_continuity else ""}`homebrew/dev-platform.rb` (the tap formula).

Reproduce (a release is verified with the verifier and policy of its own source revision):
```
git show {i["source_revision"]}:trust/policy.json > policy.json
git show {i["source_revision"]}:tools/verify_release.py > verify_release.py
gh release download v{version} --repo {REPO} --dir d
python3 -I verify_release.py d/dev-platform-{version}.tar.gz --version {version} \\
  --source-revision {i["source_revision"]} --archive-sha256 {i["archive_sha256"]} \\
  --tree-digest {i["tree_digest_pin"]} --environment d/dev-platform-{version}.build-environment.json \\
  {f"--continuity d/dev-platform-{version}.continuity.json " if has_continuity else ""}--policy policy.json
```
""")


def update_tap(version: str, trailers: list[str]) -> str:
    formula = (ROOT / "releases" / version / "homebrew" / "dev-platform.rb").read_text()
    path = "Formula/dev-platform.rb"
    cur = gh_json("api", f"repos/{TAP}/contents/{path}?ref=main")
    if base64.b64decode(cur["content"]).decode() == formula:
        return "already current"
    branch = f"dev-platform-{version}"
    pr = open_pr(TAP, branch)
    if pr:  # resumed: the change is already proposed
        wait_and_merge(*pr, repo=TAP)
        return f"updated (#{pr[0]})"
    main_sha = gh_json("api", f"repos/{TAP}/git/ref/heads/main")["object"]["sha"]
    sh(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{TAP}/git/refs",
            "-f",
            f"ref=refs/heads/{branch}",
            "-f",
            f"sha={main_sha}",
        ]
    )
    put = gh_json("api", "-X", "PUT", f"repos/{TAP}/contents/{path}", "-f", f"message=dev-platform {version}",
                  "-f", f"content={base64.b64encode(formula.encode()).decode()}", "-f", f"sha={cur['sha']}",
                  "-f", f"branch={branch}")  # fmt: skip
    body = (
        f"Formula of dev-platform {version}, rendered from {REPO} `releases/{version}/identity.json` by "
        "`tools/homebrew_formula.py`; this repository's checks install it and verify the archive with the "
        "release's own trusted installer. Opened by `tools/release.py`."
    )
    url = sh(["gh", "pr", "create", "--repo", TAP, "--base", "main", "--head", branch, "--title",
              f"dev-platform {version}", "--body", body + ("\n\n" + "\n".join(trailers) if trailers else "")])  # fmt: skip
    wait_and_merge(url.rsplit("/", 1)[-1], put["commit"]["sha"], repo=TAP)
    return f"updated ({url})"


def publish(a) -> dict:
    pred = predecessor_of(a.version)
    rev = tag_commit(a.version) or finalize_version(a, pred)
    run = tag_and_publish(a.version, rev)
    report = records(a)
    report["release_workflow_run"] = run["url"]
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("ready", "publish", "records"):
        p = sub.add_parser(name)
        p.add_argument("--version", required=name != "ready")
        p.add_argument("--kind", action="append", default=[], help="declared change kind (repeatable)")
        p.add_argument(
            "--trailer", action="append", default=[], help="line appended to commits and PR bodies"
        )
        p.add_argument(
            "--skip-continuity", action="store_true", help="ready: skip the predecessor's full stage"
        )
        p.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.version and not lifecycle.SEMVER.match(a.version):
        ap.error(f"version {a.version!r} is not X.Y.Z or X.Y.Z-(alpha|beta|rc).N")
    try:
        if a.cmd == "ready":
            r = ready(a)
            print(json.dumps(r, indent=2) if a.json else verdict(r))
            return 0 if r["ready"] else 1
        r = publish(a) if a.cmd == "publish" else records(a)
    except Stop as e:
        print(f"STOPPED: {e}", file=sys.stderr)
        return 1
    print(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
