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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--consumer-id", required=True)
    ap.add_argument("--consumer-dir", type=Path, required=True)
    ap.add_argument(
        "--work", type=Path, required=True, help="scratch directory (store, trust files, results)"
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mode", choices=["release", "head"], default="release")
    a = ap.parse_args(argv)
    plan = json.loads((ROOT / "pilot" / "consumers.json").read_text())
    c = next(x for x in plan["consumers"] if x["id"] == a.consumer_id)
    ver = plan["release"]["version"]
    ident = json.loads((ROOT / "releases" / ver / "identity.json").read_text())
    findings: list[dict] = []
    rec: dict = {
        "schema": "dev-platform.pilot-result/v1",
        "mode": a.mode,
        "consumer": {"id": c["id"], "repo": c["repo"], "commit": c["commit"], "profile": c["profile"]},
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
    r = run([sys.executable, "-m", "dev_platform", "init", "--platform-version", ver, "--sha256", tree,
             "--profile", c["profile"], "--project", str(cd)], env=env)  # fmt: skip
    rec["steps"]["init_exit"] = r.returncode
    if r.returncode:
        findings.append({"step": "init", "detail": r.stderr.strip()[-400:]})
        return finish()
    cfg = (cd / "dev-platform.toml").read_text()
    rec["steps"]["generated_checks"] = re.findall(r'^id = "([^"]+)"', cfg, re.M)
    run(["git", "-C", str(cd), "add", "dev-platform.toml"])
    run(["git", "-C", str(cd), "-c", "user.name=pilot", "-c", "user.email=pilot@invalid", "commit", "-q",
         "-m", "pilot: generated dev-platform.toml (local only)"])  # fmt: skip
    d = run([sys.executable, "-m", "dev_platform", "doctor", "--project", str(cd)], env=env)
    rec["steps"]["doctor_exit"] = d.returncode
    rec["steps"]["config_valid"] = "valid" in d.stdout
    rec["steps"]["doctor"] = d.stdout.strip().splitlines()[-12:]
    result = work / "result.json"
    r = run([sys.executable, "-m", "dev_platform", "check", "--project", str(cd), "--stage", "full",
             "--result", str(result)], env=env)  # fmt: skip
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
        if not cert.get("certified"):
            findings.append(
                {"step": "certification", "detail": "not certified", "blockers": cert.get("blockers")}
            )
    else:
        findings.append({"step": "check", "detail": "no result record produced"})
    return finish()


if __name__ == "__main__":
    sys.exit(main())
