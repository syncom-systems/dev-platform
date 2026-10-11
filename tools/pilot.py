#!/usr/bin/env python3
"""Run one consumer pilot end to end and write a findings record (dev-platform.pilot-result/v1).

install:   the release under test via the trusted installer (pinned verifier/policy bytes taken from the
           release's own git tag, pinned digests from releases/<version>/identity.json), unaccepted allowed
           only because the pilot says so
configure: `dev-platform init` in the consumer checkout (commit stays local to the throwaway checkout)
execute:   `check --stage full --result` through the installed, pinned release
record:    result facts (admission, certification, blockers) and findings against pilot/consumers.json `expect`

A pilot never changes acceptance, never pushes to the consumer and never claims qualification: its output
is evidence about adoption friction. Exit 0 when the recorded outcome matches `expect`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--consumer-id", required=True)
    ap.add_argument("--consumer-dir", type=Path, required=True)
    ap.add_argument(
        "--work", type=Path, required=True, help="scratch directory (store, trust files, results)"
    )
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    plan = json.loads((ROOT / "pilot" / "consumers.json").read_text())
    c = next(x for x in plan["consumers"] if x["id"] == a.consumer_id)
    ver = plan["release"]["version"]
    ident = json.loads((ROOT / "releases" / ver / "identity.json").read_text())
    pins = ident["verifier_pins"]
    findings: list[dict] = []
    rec: dict = {
        "schema": "dev-platform.pilot-result/v1",
        "consumer": {"id": c["id"], "repo": c["repo"], "commit": c["commit"], "profile": c["profile"]},
        "release": {"version": ver, "archive_sha256": ident["archive_sha256"], "tree_digest": ident["tree_digest_pin"]},
        "steps": {},
        "findings": findings,
        "claims": "evidence about adoption friction only; no qualification, certification or acceptance claim",
    }  # fmt: skip

    def finish(code: int) -> int:
        expect = c.get("expect", {})
        rec["expectations"] = {k: {"expected": v, "actual": rec["steps"].get(k)} for k, v in expect.items()}
        rec["matches_expectations"] = all(rec["steps"].get(k) == v for k, v in expect.items())
        a.out.write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n")
        print(json.dumps({k: rec[k] for k in ("steps", "findings", "matches_expectations")}, indent=2))
        return 0 if rec["matches_expectations"] else 1

    work = a.work.resolve()
    trust = work / "trust"
    (trust / "tools").mkdir(parents=True, exist_ok=True)
    for src, dst in (("tools/verify_release.py", trust / "tools" / "verify_release.py"),
                     ("trust/policy.json", trust / "policy.json"),
                     ("tools/install_release.py", trust / "tools" / "install_release.py")):  # fmt: skip
        r = run(["git", "-C", str(ROOT), "show", f"v{ver}:{src}"] if src != "tools/install_release.py"
                else ["cat", str(ROOT / src)])  # fmt: skip
        if r.returncode:
            findings.append(
                {"step": "trust-files", "detail": f"cannot read {src} from v{ver}: {r.stderr.strip()}"}
            )
            rec["steps"]["installed"] = False
            return finish(1)
        dst.write_text(r.stdout)
    got = {"verify": sha(trust / "tools" / "verify_release.py"), "policy": sha(trust / "policy.json"),
           "install": sha(trust / "tools" / "install_release.py")}  # fmt: skip
    want = {"verify": pins["verify_release.py_sha256"], "policy": pins["trust_policy_sha256"],
            "install": pins["install_release.py_sha256"]}  # fmt: skip
    if got != want:
        findings.append({"step": "trust-files", "detail": f"pin mismatch: {got} != {want}"})
        rec["steps"]["installed"] = False
        return finish(1)
    store = work / "store"
    inst = [sys.executable, str(trust / "tools" / "install_release.py"), "--version", ver, "--store", str(store),
            "--verifier-sha256", want["verify"], "--policy", str(trust / "policy.json"),
            "--policy-sha256", want["policy"], "--archive-sha256", ident["archive_sha256"],
            "--tree-sha256", ident["tree_digest_pin"], "--source-revision", ident["source_revision"]]  # fmt: skip
    if plan["release"].get("allow_unaccepted"):
        inst.append("--allow-unaccepted")
    r = run(inst)
    rec["steps"]["installed"] = r.returncode == 0
    rec["steps"]["install_output"] = (r.stdout + r.stderr).strip().splitlines()[-3:]
    if r.returncode:
        findings.append({"step": "install", "detail": "installer refused", "output": r.stderr.strip()[-400:]})
        return finish(1)
    env = {**os.environ, "DEV_PLATFORM_STORE": str(store), "PYTHONPATH": str(store / ver / "src")}
    cd = a.consumer_dir.resolve()
    r = run([sys.executable, "-m", "dev_platform", "init", "--platform-version", ver,
             "--sha256", ident["tree_digest_pin"], "--profile", c["profile"], "--project", str(cd)], env=env)  # fmt: skip
    rec["steps"]["init_exit"] = r.returncode
    if r.returncode:
        findings.append({"step": "init", "detail": r.stderr.strip()[-400:]})
        return finish(1)
    ident_args = ["-c", "user.name=pilot", "-c", "user.email=pilot@invalid"]
    run(["git", "-C", str(cd), "add", "dev-platform.toml"])
    run(
        [
            "git",
            "-C",
            str(cd),
            *ident_args,
            "commit",
            "-q",
            "-m",
            "pilot: generated dev-platform.toml (local only)",
        ]
    )
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
        rec["steps"].update(admission=doc.get("admission"), certified=cert.get("certified"),
                            blockers=cert.get("blockers"), result_sha256=sha(result),
                            checks=[{"id": x.get("id"), "outcome": x.get("outcome") or x.get("status")} for x in doc.get("checks", [])])  # fmt: skip
        if not cert.get("certified"):
            findings.append(
                {"step": "certification", "detail": "not certified", "blockers": cert.get("blockers")}
            )
    else:
        findings.append({"step": "check", "detail": "no result record produced"})
    return finish(0)


if __name__ == "__main__":
    sys.exit(main())
