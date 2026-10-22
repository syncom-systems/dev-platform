#!/usr/bin/env python3
"""Produce a predecessor-continuity record (dev-platform.continuity/v1, issue #4, ADR 0014).

Release N-1 (named and digest-pinned by trust/policy.json) re-runs the full stage over release N's source.
Steps: download N-1's archive; verify its pinned digests, attestations and environment with the independent
verifier; extract it; run its own `dev_platform check --stage full` in N's checkout. The record is *evidence*
for tools/verify_release.py (which checks it against the policy and its attestation); it never confers
authority and a failing predecessor run fails the release verification.

Runs predecessor code, so the workflow gives this job no write or token permissions beyond read access.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_verifier():
    spec = importlib.util.spec_from_file_location("verify_release", HERE / "verify_release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sh(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--source", type=Path, default=Path("."), help="checkout of release N's source")
    ap.add_argument("--source-revision", required=True)
    ap.add_argument("--version", required=True, help="release N version")
    ap.add_argument("--archive-sha256", required=True, help="release N archive digest")
    ap.add_argument("--repo", default="syncom-systems/dev-platform")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    policy = json.loads(a.policy.read_text())
    pred = (policy.get("continuity") or {}).get("predecessor")
    if not pred:
        print("policy declares no predecessor (first release); no continuity record produced")
        return 0
    V = load_verifier()
    ver = pred["version"]
    with tempfile.TemporaryDirectory(prefix="continuity-") as td:
        td = Path(td)
        dl = td / "dl"
        dl.mkdir()
        r = sh(["gh", "release", "download", f"v{ver}", "--repo", a.repo, "-D", str(dl),
                "-p", f"dev-platform-{ver}.tar.gz", "-p", f"dev-platform-{ver}.build-environment.json"])  # fmt: skip
        if r.returncode:
            print(f"cannot download v{ver}: {r.stderr.strip()}", file=sys.stderr)
            return 1
        archive = dl / f"dev-platform-{ver}.tar.gz"
        env = dl / f"dev-platform-{ver}.build-environment.json"
        rev = sh(["git", "-C", str(a.source), "rev-parse", f"v{ver}^{{commit}}"]).stdout.strip()
        exp = {"version": ver, "source_revision": rev, "archive_sha256": pred["archive_sha256"],
               "tree_digest": pred["tree_digest"], "ref": f"refs/tags/v{ver}"}  # fmt: skip
        vrec = V.verify(
            archive,
            exp,
            {k: v for k, v in policy.items() if k != "continuity"},
            environment=env if env.is_file() else None,
        )
        passed = all(c["status"] == "passed" for c in vrec["checks"])
        state = vrec["acceptance"]["state"]
        # N-1's own verified bytes: extract and run its code over N's source
        root = td / "pred"
        stage = {"name": "full", "exit": None, "admission": None, "revision": None, "result_sha256": None}
        if passed and hashlib.sha256(archive.read_bytes()).hexdigest() == pred["archive_sha256"]:
            with tarfile.open(archive, "r:gz") as t:
                t.extractall(root, filter="data")
            home = td / "home"
            home.mkdir()
            result = td / "result.json"
            e = {"PATH": os.environ.get("PATH", ""), "HOME": str(home), "PYTHONPATH": str(root / ver / "src"),
                 "TMPDIR": str(td)}  # fmt: skip
            p = subprocess.run([sys.executable, "-m", "dev_platform", "check", "--stage", "full",
                                "--result", str(result)], cwd=a.source, env=e)  # fmt: skip
            stage["exit"] = p.returncode
            if result.is_file():
                doc = json.loads(result.read_text())
                stage.update(admission=doc.get("admission"), revision=doc.get("revision"),
                             result_sha256=hashlib.sha256(result.read_bytes()).hexdigest())  # fmt: skip
    out = {
        "schema": V.CONTINUITY_SCHEMA,
        "subject": {
            "version": a.version,
            "archive_sha256": a.archive_sha256,
            "source_revision": a.source_revision,
        },
        "predecessor": {**pred, "verification": {"state": state, "all_checks_passed": passed}},
        "stage": stage,
        "limitations": [
            "evidence, not authority",
            "predecessor code ran in the CI runner environment (not hermetic) with its own toolchain bootstrap",
        ],
    }
    a.out.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(
        f"predecessor {ver}: verification {state} (all checks passed: {passed}); full stage exit {stage['exit']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
