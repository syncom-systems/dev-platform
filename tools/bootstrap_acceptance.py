#!/usr/bin/env python3
"""Acceptance of the installation contract, by REAL execution on a clean machine.

    python tools/bootstrap_acceptance.py --release 0.14.0 --profile rust-python-bazel-9.3 \\
        --fixture fixtures-real/baseline-mixed [--old-cli 0.12.1 --old-cli 0.13.0] --out acceptance.json

Start state: no dev-platform store, toolchains or cache (everything lives in the job-local `.devenv/bootstrap`,
removed first) and no globally installed compiler. The CLI under test (this checkout, which is what the
Homebrew formula installs as the bootstrap) then, with the project's committed pins only:

  1. (each --old-cli) an older published CLI, installed with the trusted installer, runs `setup` for the project
     pinned to --release. It may fail: it validates a release with its own bundled schema, which is the
     transition limitation this contract removes. It must leave the store as it found it;
  2. `dev-platform setup` installs the pinned release with the pinned trusted installer (provenance, SBOM and
     build-environment attestations, archive, revision and tree digest), runs it from a verified snapshot,
     provisions its profile and verifies the environment;
  3. the real Bazel checks run (build, lint, test at the `full` stage), certified;
  4. `setup` again changes and downloads nothing and reports the same environment identity.

Needs `gh` (authenticated) and network, like `dev-platform setup`. Exit status 0 only when every step holds.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
WORK = ROOT / ".devenv" / "bootstrap"


def rmtree(path: Path) -> None:
    for dirpath, dirnames, _ in os.walk(path):
        for d in dirnames:
            os.chmod(Path(dirpath) / d, 0o700)
    if path.exists():
        os.chmod(path, 0o700)
    shutil.rmtree(path, ignore_errors=True)


def run(argv, cwd, env, check=True):
    r = subprocess.run(argv, cwd=cwd, env=env, text=True, capture_output=True)
    if check and r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(f"command failed ({r.returncode}): {' '.join(map(str, argv))}")
    return r


def identity(version: str) -> dict:
    return json.loads((ROOT / "releases" / version / "identity.json").read_text())


def pins_of(version: str) -> dict:
    ident = identity(version)
    keys = ("version", "source_revision", "archive_sha256", "tree_digest_pin", "verifier_pins")
    return {k: ident[k] for k in keys}


def tree_of(path: Path) -> str:
    from dev_platform.digest import tree_digest

    return tree_digest(path)


def install_old_cli(version: str, base: Path, env: dict) -> Path:
    """The published CLI `version`, installed with its trusted installer into its own store (what `brew install`
    of that formula leaves; nothing is shared with the CLI under test)."""
    from dev_platform import locations, projectsetup

    home = base / version
    loc = locations.locate({}, home=home)
    creds = {k: env[k] for k in projectsetup.TOKEN_VARS if k in env}
    rec = projectsetup.ensure_release(
        pins_of(version),
        loc,
        opts={
            "allow_unaccepted": True,
            "allow_prerelease": False,
            "reverify": False,
            "repo_url": projectsetup.DEFAULT_REPO,
        },
        run=projectsetup.run_process,
        env={k: v for k, v in env.items() if k not in projectsetup.TOKEN_VARS},
        creds=creds,
    )
    return Path(rec["path"]) / "src"


def make_project(fixture: Path, version: str, profile: str, env: dict, py: list) -> Path:
    """A project that has committed its pins: the fixture, its two pin files and the owner's one-time entry lines
    for the generated Bazel configuration (docs/rust-python-baseline.md)."""
    from dev_platform import bazelconf

    project = WORK / "project"
    shutil.copytree(ROOT / fixture, project, ignore=shutil.ignore_patterns("bazel-*", "target"))
    pins = pins_of(version)
    (project / "dev-platform.release-pins.json").write_text(json.dumps(pins, indent=2) + "\n")
    run([*py, "init", "--project", str(project), "--platform-version", version,
         "--sha256", pins["tree_digest_pin"], "--profile", profile], ROOT, env)  # fmt: skip
    for rel, line in (("MODULE.bazel", bazelconf.MODULE_HOOK), (".bazelrc", bazelconf.BAZELRC_HOOK)):
        f = project / rel
        f.write_text((f.read_text() if f.is_file() else "") + line + "\n")
    return project


def setup(project: Path, py: list, env: dict, home: Path, cwd: Path = ROOT):
    r = run([*py, "setup", "--project", str(project), "--home", str(home), "--json"], cwd, env, check=False)
    try:
        rec = json.loads(r.stdout)
    except ValueError:
        rec = {"ok": False, "problem": (r.stdout + r.stderr)[-400:]}
    return r.returncode, rec


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--release", required=True, help="the published release the project pins")
    ap.add_argument("--profile", required=True)
    ap.add_argument("--fixture", type=Path, required=True)
    ap.add_argument("--old-cli", action="append", default=[], help="older published CLI versions to try first")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    rmtree(WORK)
    WORK.mkdir(parents=True)
    home = WORK / "home"
    base = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "DEV_PLATFORM_STORE")}
    cli_env = {**base, "PYTHONPATH": str(ROOT / "src")}
    py = [sys.executable, "-m", "dev_platform"]
    steps: dict = {"release": a.release, "profile": a.profile, "host": f"{sys.platform}-{os.uname().machine}"}
    project = make_project(a.fixture, a.release, a.profile, cli_env, py)
    genv = {**base, "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@example.invalid",
            "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@example.invalid"}  # fmt: skip
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "pins"]):
        run(["git", *cmd], project, genv)

    steps["old_clis"] = []
    for old in a.old_cli:
        src = install_old_cli(old, WORK / "old", base)
        env = {**base, "PYTHONPATH": str(src)}
        before = sorted(p.name for p in (home / "versions").glob("*")) if (home / "versions").is_dir() else []
        r = run(py + ["setup", "--project", str(project), "--home", str(home)], project, env, check=False)
        after = sorted(p.name for p in (home / "versions").glob("*") if not p.name.startswith("."))
        steps["old_clis"].append({"cli": old, "exit": r.returncode, "output": (r.stdout + r.stderr)[-300:],
                                  "store_before": before, "store_after": after})  # fmt: skip

    code, rec = setup(project, py, cli_env, home)
    steps["setup"] = {"exit": code, "ok": rec.get("ok"), "problem": rec.get("problem"),
                      "release": rec.get("release"), "toolchain": rec.get("toolchain")}  # fmt: skip
    if code or not rec.get("ok"):
        return finish(a, steps, False)
    tree = tree_of(Path(rec["release"]["path"]))
    steps["installed_tree_matches_pin"] = tree == pins_of(a.release)["tree_digest_pin"]
    benv = {**cli_env, "DEV_PLATFORM_STORE": str(home / "versions"),
            "PATH": os.pathsep.join([*rec["env"]["PATH"], base.get("PATH", "")])}  # fmt: skip
    if rec["env"].get("DEV_PLATFORM_PYTHON"):
        benv["DEV_PLATFORM_PYTHON"] = rec["env"]["DEV_PLATFORM_PYTHON"]
    from dev_platform import toolchain

    manifest = json.loads((Path(rec["release"]["path"]) / "release.json").read_text())["toolchains"]
    benv = {**benv, **toolchain.runtime_env(manifest, a.profile)}
    run(["bazel", "mod", "deps", "--lockfile_mode=update"], project, benv)
    run([*py, "init", "--project", str(project), "--platform-version", a.release,
         "--sha256", pins_of(a.release)["tree_digest_pin"], "--profile", a.profile, "--force"], ROOT, benv)  # fmt: skip
    for cmd in (["add", "-A"], ["commit", "-qm", "lockfile and checks"]):
        run(["git", *cmd], project, genv)
    result = WORK / "result.json"
    r = run([*py, "check", "--project", str(project), "--stage", "full", "--result", str(result)],
            project, benv, check=False)  # fmt: skip
    sys.stderr.write(r.stdout[-1500:])
    doc = json.loads(result.read_text()) if result.is_file() else {}
    cert = (doc.get("certification") or {}).get("certified", False)
    steps["check"] = {"exit": r.returncode, "certified": cert,
                      "checks": {c["id"]: c["state"] for c in doc.get("checks", [])},
                      "identity_digest": (doc.get("environment") or {}).get("identity_digest")}  # fmt: skip
    code2, rec2 = setup(project, py, cli_env, home)
    steps["repeat"] = {
        "exit": code2,
        "release_action": (rec2.get("release") or {}).get("action"),
        "toolchain_action": (rec2.get("toolchain") or {}).get("action"),
        "same_identity": (rec2.get("toolchain") or {}).get("identity_digest")
        == (rec.get("toolchain") or {}).get("identity_digest"),
        "tree_unchanged": tree_of(Path(rec["release"]["path"])) == tree,
    }
    ok = (
        bool(cert)
        and steps["installed_tree_matches_pin"]
        and code2 == 0
        and steps["repeat"]["release_action"] == "present"
        and steps["repeat"]["toolchain_action"] == "reused"
        and steps["repeat"]["same_identity"]
        and steps["repeat"]["tree_unchanged"]
        and steps["check"]["identity_digest"] == (rec.get("toolchain") or {}).get("identity_digest")
    )
    return finish(a, steps, ok)


def finish(a, steps: dict, ok: bool) -> int:
    steps["ok"] = ok
    text = json.dumps(steps, indent=2, sort_keys=True)
    if a.out:
        a.out.write_text(text + "\n")
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
