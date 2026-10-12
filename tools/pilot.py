#!/usr/bin/env python3
"""Run one consumer pilot end to end and write a findings record (dev-platform.pilot-result/v1).

mode release (default)
  install:   the published release via the trusted installer: verifier/policy/installer bytes come from the
             release's own git tag and must equal the pins in releases/<version>/identity.json; the archive
             and tree digests are pinned too; unaccepted is allowed only because the pilot plan says so
mode head
  install:   an UNATTESTED build of this workspace, to test unreleased fixes against the same consumer
             (the record says so; it is never a release and nothing about it is verified)
then, in both modes
  configure: `dev-platform init` in the consumer checkout (the commit stays in the throwaway checkout)
  execute:   `doctor` and `check --stage full --result` through the installed, pinned platform
  record:    facts (admission, certification, blockers) and findings against pilot/consumers.json `expect`

A pilot never changes acceptance, never pushes to the consumer and never claims qualification: its output is
evidence about adoption friction. Exit 0 when the recorded outcome matches `expect` for the mode.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.match(r"(\d+)\.(\d+)\.(\d+)", v).groups())  # type: ignore[union-attr]


def has_consumer_features(mode: str, ver: str) -> bool:
    """Pins, `provision --verify` and the Bazel proof exist from 0.8.0 (head builds always have them)."""
    return mode == "head" or version_tuple(ver) >= (0, 8, 0)


def make_fixture_consumer(c: dict, dest: Path) -> None:
    """A reference consumer that lives in this repository (a throwaway copy, committed locally)."""
    import shutil

    shutil.copytree(ROOT / c["fixture"], dest, dirs_exist_ok=True, ignore=shutil.ignore_patterns("bazel-*"))
    env = {**os.environ, "GIT_AUTHOR_NAME": "pilot", "GIT_AUTHOR_EMAIL": "pilot@invalid",
           "GIT_COMMITTER_NAME": "pilot", "GIT_COMMITTER_EMAIL": "pilot@invalid"}  # fmt: skip
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "reference consumer"]):
        subprocess.run(["git", "-C", str(dest), *cmd], env=env, check=True, capture_output=True)


def install_release(plan: dict, ident: dict, ver: str, work: Path, findings: list) -> tuple[bool, str]:
    """Trusted installer under pins from the release record. Returns (ok, detail)."""
    pins = ident["verifier_pins"]
    trust = work / "trust"
    (trust / "tools").mkdir(parents=True, exist_ok=True)
    files = (
        ("verify_release.py", ["git", "-C", str(ROOT), "show", f"v{ver}:tools/verify_release.py"], trust / "tools"),
        ("policy.json", ["git", "-C", str(ROOT), "show", f"v{ver}:trust/policy.json"], trust),
        ("install_release.py", ["cat", str(ROOT / "tools" / "install_release.py")], trust / "tools"),
    )  # fmt: skip
    for name, cmd, dest in files:
        r = run(cmd)
        if r.returncode:
            return False, f"cannot read {name}: {r.stderr.strip()}"
        (dest / name).write_text(r.stdout)
    got = {
        "verify": sha(trust / "tools" / "verify_release.py"),
        "policy": sha(trust / "policy.json"),
        "install": sha(trust / "tools" / "install_release.py"),
    }
    want = {
        "verify": pins["verify_release.py_sha256"],
        "policy": pins["trust_policy_sha256"],
        "install": pins["install_release.py_sha256"],
    }
    if got != want:
        return False, f"pin mismatch: {got} != {want}"
    cmd = [sys.executable, str(trust / "tools" / "install_release.py"), "--version", ver,
           "--store", str(work / "store"), "--verifier-sha256", want["verify"],
           "--policy", str(trust / "policy.json"), "--policy-sha256", want["policy"],
           "--archive-sha256", ident["archive_sha256"], "--tree-sha256", ident["tree_digest_pin"],
           "--source-revision", ident["source_revision"]]  # fmt: skip
    if plan["release"].get("allow_unaccepted"):
        cmd.append("--allow-unaccepted")
    r = run(cmd)
    out = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode == 0, "\n".join(out[-3:])


def build_head(work: Path) -> tuple[bool, str, str, str]:
    """(ok, detail, version, tree digest) for an unattested build of this workspace."""
    cur = re.search(r'__version__ = "([^"]+)"', (ROOT / "src" / "dev_platform" / "__init__.py").read_text())[
        1
    ]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    store = work / "store"
    r = run([sys.executable, "-m", "dev_platform", "release", "build", "--version", cur, "--out", str(store),
             "--toolchains", str(ROOT / "toolchains" / "manifest.json"), "--src", str(ROOT / "src")], env=env)  # fmt: skip
    if r.returncode:
        return False, r.stderr.strip()[-400:], cur, ""
    tree = run([sys.executable, "-m", "dev_platform", "digest", str(store / cur)], env=env).stdout.strip()
    return True, "", cur, tree


def app_release_step(c: dict, cd: Path, work: Path, result: Path, env: dict, ver: str, tree: str) -> dict:
    """Application-release chain over the pilot's result (v0.3.0). No approval exists for a pilot, so the
    only correct outcomes are a refusal to assemble (uncertified result) or a non-approval (`unapproved`, or
    `failed` when the consumer's evidence repository cannot be read: the decision is current-state and fails
    closed), also when an unsigned, forged approval is offered. The consumer is never modified beyond its throwaway checkout."""
    out: dict = {}
    locks = [n for n in ("Cargo.lock", "MODULE.bazel.lock", "uv.lock") if (cd / n).is_file()]
    if not locks:
        return {"app_release": "skipped: no lock file"}
    art = work / "source.tar"
    art.write_bytes(subprocess.run(["git", "-C", str(cd), "archive", "--format=tar", "HEAD"],
                                   capture_output=True, check=True).stdout)  # fmt: skip
    rev = run(["git", "-C", str(cd), "rev-parse", "HEAD"]).stdout.strip()
    rel = work / "app-release.json"
    asm = run([sys.executable, "-m", "dev_platform", "provenance", "assemble", "--result", str(result),
               "--name", c["id"], "--app-version", "0.0.0-pilot", "--source-uri", f"https://github.com/{c['repo']}",
               "--artifact", f"source.tar={sha(art)}", *[x for n in locks for x in ("--lock", str(cd / n))],
               "--root", str(cd), "--out", str(rel)], env=env)  # fmt: skip
    if asm.returncode:
        return {"app_release": "refused", "app_release_reason": (asm.stderr or asm.stdout).strip()[-300:]}
    out["app_release"] = "assembled"
    policy = work / "app-trust.json"
    policy.write_text(json.dumps({
        "schema": "dev-platform.app-trust/v1",
        "authorization": {"providers": ["github-signed-commit"], "evidence_repo": c["repo"],
                          "evidence_ref": "main", "approvers": []},
        "platform_releases": [{"version": ver, "tree_digest": tree}]}))  # fmt: skip
    forged = work / "forged.json"
    forged.write_text(json.dumps({
        "schema": "dev-platform.authorization/v1", "id": "forged",
        "subject": {"kind": "application-release", "digest": json_digest(json.loads(rel.read_text()))},
        "decision": "approved",
        "decided_by": {"id": "nobody", "role": "owner", "identity_assertion": {
            "provider": "github-signed-commit", "login": "nobody", "path": "authorizations/forged.json"}},
        "basis": {"kind": "pilot", "reference": "forged on purpose"}, "decided_at": "2026-01-01T00:00:00Z",
        "scope": {"confers": ["application-release-approval"]},
        "retention": {"class": "standard", "until": None}}))  # fmt: skip
    pv = ROOT / "tools" / "verify_release.py"
    base = [sys.executable, "-I", str(ROOT / "tools" / "verify_app_release.py"), str(rel), "--policy", str(policy),
            "--platform-verifier", str(pv), "--platform-verifier-sha256", sha(pv), "--mode", "release",
            "--source-revision", rev, "--root", str(cd), "--result", str(result),
            *[x for n in locks for x in ("--lock", str(cd / n))], "--artifact", f"source.tar={art}"]  # fmt: skip
    for key, extra in (
        ("app_release_state", []),
        ("app_release_forged_state", ["--authorization", str(forged)]),
    ):
        o = work / f"{key}.json"
        run([*base, *extra, "--out", str(o)])
        out[key] = json.loads(o.read_text())["approval"]["state"] if o.is_file() else "no-record"
    return out


def json_digest(doc) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write_evidence(out: Path, cd: Path, result: Path, proof: Path | None, rec: dict) -> str:
    """Bundle the consumer's execution evidence and judge it with the independent verifier against the
    consumer's own pins (dev-platform.toml in the throwaway checkout)."""
    import shutil

    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result, out / "result.json")
    shutil.copy2(cd / "dev-platform.toml", out / "dev-platform.toml")
    argv = [sys.executable, "-I", str(ROOT / "tools" / "verify_consumer_evidence.py"),
            "--result", str(out / "result.json"), "--config", str(out / "dev-platform.toml"),
            "--allow-uncertified", "--out", str(out / "verification.json")]  # fmt: skip
    if proof and proof.is_file():
        shutil.copy2(proof, out / "bazel-rust-proof.json")
        argv += ["--bazel-proof", str(out / "bazel-rust-proof.json"), "--require-bazel-proof"]
    run(argv)
    verdict = (
        json.loads((out / "verification.json").read_text())["verdict"]
        if (out / "verification.json").is_file()
        else "no-record"
    )
    (out / "pilot-result.json").write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
    return verdict


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--consumer-id", required=True)
    ap.add_argument("--consumer-dir", type=Path, required=True)
    ap.add_argument(
        "--work", type=Path, required=True, help="scratch directory (store, trust files, results)"
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mode", choices=["release", "head"], default="release")
    ap.add_argument("--evidence-dir", type=Path, help="write the consumer evidence bundle here")
    a = ap.parse_args(argv)
    plan = json.loads((ROOT / "pilot" / "consumers.json").read_text())
    c = next(x for x in plan["consumers"] if x["id"] == a.consumer_id)
    ver = plan["release"]["version"]
    ident = json.loads((ROOT / "releases" / ver / "identity.json").read_text())
    findings: list[dict] = []
    rec: dict = {
        "schema": "dev-platform.pilot-result/v1",
        "mode": a.mode,
        "consumer": {k: c.get(k) for k in ("id", "repo", "commit", "fixture", "profile") if c.get(k)},
        "steps": {},
        "findings": findings,
        "claims": "evidence about adoption friction only; no qualification, certification or acceptance claim",
    }
    work = a.work.resolve()

    def finish() -> int:
        import platform as _pl

        plat = f"{sys.platform}-{_pl.machine()}"
        ex = c.get("expect", {})
        expect = {**ex.get(a.mode, {}), **ex.get(f"{a.mode}@{plat}", {})}
        rec["expectations"] = {k: {"expected": v, "actual": rec["steps"].get(k)} for k, v in expect.items()}
        rec["matches_expectations"] = all(rec["steps"].get(k) == v for k, v in expect.items())
        a.out.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
        if a.evidence_dir and a.evidence_dir.is_dir():
            (a.evidence_dir / "pilot-result.json").write_text(
                json.dumps(rec, indent=2, sort_keys=True) + "\n"
            )
        print(json.dumps({k: rec[k] for k in ("steps", "findings", "matches_expectations")}, indent=2))
        return 0 if rec["matches_expectations"] else 1

    if a.mode == "head":
        ok, detail, ver, tree = build_head(work)
        rec["release"] = {"version": ver, "tree_digest": tree, "provenance": "unattested workspace build"}
    else:
        ok, detail = install_release(plan, ident, ver, work, findings)
        tree = ident["tree_digest_pin"]
        rec["release"] = {"version": ver, "archive_sha256": ident["archive_sha256"], "tree_digest": tree}
    rec["steps"]["installed"] = ok
    rec["steps"]["install_output"] = detail
    if not ok:
        findings.append({"step": "install", "detail": detail[-400:]})
        return finish()
    env = {
        **os.environ,
        "DEV_PLATFORM_STORE": str(work / "store"),
        "PYTHONPATH": str(work / "store" / ver / "src"),
    }
    cd = a.consumer_dir.resolve()
    if c.get("fixture"):
        make_fixture_consumer(c, cd)
    feats = has_consumer_features(a.mode, ver)
    r = run([sys.executable, "-m", "dev_platform", "init", "--platform-version", ver, "--sha256", tree,
             "--profile", c["profile"], "--project", str(cd)], env=env)  # fmt: skip
    rec["steps"]["init_exit"] = r.returncode
    if r.returncode:
        findings.append({"step": "init", "detail": r.stderr.strip()[-400:]})
        return finish()
    # consumer path: the pinned release provisions its own profile (`toolchain provision --pinned`)
    dest = work / "devenv"
    prov = [sys.executable, "-m", "dev_platform", "toolchain", "provision", "--pinned", "--project", str(cd),
            "--profile", c["profile"], "--dest"]  # fmt: skip
    r = run([*prov, str(dest), *(["--verify"] if feats else [])], env=env)
    rec["steps"]["provision_exit"] = r.returncode if not feats else (0 if r.stdout.strip() else r.returncode)
    if feats and r.stdout.strip():
        v1 = json.loads(r.stdout.strip().splitlines()[0]).get("verification") or {}
        rec["steps"]["toolchain_verification"] = v1
        # determinism: a second, clean provisioning of the same pinned release gives the same identity
        r2 = run([*prov, str(work / "devenv2"), "--verify"], env=env)
        v2 = (
            (json.loads(r2.stdout.strip().splitlines()[0]).get("verification") or {})
            if r2.stdout.strip()
            else {}
        )
        rec["steps"]["provision_deterministic"] = bool(v1.get("identity_digest")) and v1 == v2
    if rec["steps"]["provision_exit"]:
        findings.append({"step": "provision", "detail": (r.stderr or r.stdout).strip()[-400:]})
        return finish()
    extra = [str(dest / "bin")] + [str(p / "bin") for p in sorted(dest.iterdir()) if (p / "bin").is_dir()]
    env["PATH"] = os.pathsep.join([*extra, env["PATH"]])
    cfg = (cd / "dev-platform.toml").read_text()
    rec["steps"]["generated_checks"] = re.findall(r'^id = "([^"]+)"', cfg, re.M)
    if c.get("config_append"):
        # consumer-declared additions (the release under test must understand them: 0.2.1 or later)
        (cd / "dev-platform.toml").write_text(cfg.rstrip("\n") + "\n\n" + c["config_append"])
        rec["steps"]["config_append"] = True
    infra_args: list[str] = []
    if feats and c.get("infra"):
        inf = c["infra"]
        vend = cd / ".dev-platform" / "infra-profile.json"
        vend.parent.mkdir(exist_ok=True)
        vend.write_bytes((ROOT / inf["profile"]).read_bytes())
        digest = run(
            [sys.executable, "-m", "dev_platform", "infra", "digest", str(vend)], env=env
        ).stdout.strip()
        with (cd / "dev-platform.toml").open("a") as f:
            f.write(f'\n[infra]\nprovider = "{inf["provider"]}"\nconfig_release = "{inf["config_release"]}"\n'
                    f'config_digest = "{digest}"\n')  # fmt: skip
        infra_args = ["--infra-profile", str(vend)]
        rec["steps"]["infra_pinned"] = True
    run(["git", "-C", str(cd), "add", "-A"])
    run(["git", "-C", str(cd), "-c", "user.name=pilot", "-c", "user.email=pilot@invalid", "commit", "-q",
         "-m", "pilot: generated dev-platform.toml (local only)"])  # fmt: skip
    d = run([sys.executable, "-m", "dev_platform", "doctor", "--project", str(cd)], env=env)
    rec["steps"]["doctor_exit"] = d.returncode
    rec["steps"]["config_valid"] = "valid" in d.stdout
    rec["steps"]["doctor"] = d.stdout.strip().splitlines()[-12:]
    result = work / "result.json"
    r = run([sys.executable, "-m", "dev_platform", "check", "--project", str(cd), "--stage", "full",
             "--result", str(result), *infra_args], env=env)  # fmt: skip
    rec["steps"]["check_exit"] = r.returncode
    rec["steps"]["check_tail"] = (r.stdout + r.stderr).strip().splitlines()[-15:]
    if result.is_file():
        doc = json.loads(result.read_text())
        cert = doc.get("certification") or {}
        rec["steps"].update(
            admission=doc.get("admission"),
            certified=cert.get("certified"),
            blockers=cert.get("blockers"),
            result_sha256=sha(result),
            checks=[
                {"id": x.get("id"), "outcome": x.get("outcome") or x.get("status")}
                for x in doc.get("checks", [])
            ],
        )
        if feats:
            rec["steps"]["infra_status"] = (doc.get("infra") or {}).get("status")
            rec["steps"]["infra_source"] = (doc.get("infra") or {}).get("source")
        proof_file = None
        if feats and c["profile"].startswith("rust-bazel"):
            proof_file = work / "bazel-rust-proof.json"
            run([sys.executable, "-m", "dev_platform", "toolchain", "prove-bazel-rust", "--project", str(cd),
                 "--out", str(proof_file)], env=env)  # fmt: skip
            pf = json.loads(proof_file.read_text()) if proof_file.is_file() else {}
            rec["steps"]["bazel_rust_proof"] = bool(pf.get("ok"))
        if feats and a.evidence_dir:
            rec["steps"]["evidence_verdict"] = write_evidence(a.evidence_dir, cd, result, proof_file, rec)
        if not cert.get("certified"):
            findings.append(
                {"step": "certification", "detail": "not certified", "blockers": cert.get("blockers")}
            )
        if not c.get("skip_app_release"):
            rec["steps"].update(app_release_step(c, cd, work, result, env, ver, tree))
    else:
        findings.append({"step": "check", "detail": "no result record produced"})
    return finish()


if __name__ == "__main__":
    sys.exit(main())
