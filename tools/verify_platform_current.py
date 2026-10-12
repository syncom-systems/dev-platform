#!/usr/bin/env python3
"""Is this Dev Platform release CURRENTLY accepted? (current-state wrapper over tools/verify_release.py)

`tools/verify_release.py` (the trust anchor the owner pins; unchanged) judges the authorization records it is handed.
For a current decision that is not enough: an acceptance revoked after the supplied records were collected would
still read `accepted`. This wrapper loads the pinned platform verifier and the pinned application verifier (for the
shared snapshot code, so there is one freshness mechanism, not two), reads every record in the policy's evidence
repository at ONE commit, audits the history for deleted records, hands all of it to the platform verifier, and
refuses (`failed`) when the current state cannot be established.

  default       current decision: `current_decision.state` is `accepted` only if the platform verifier says accepted
                over the current state; `verified-unaccepted` when it is not; `failed` when it cannot be established
  --historical  supplied records only; an acceptance is reported as `historical-acceptance`, never `accepted`

The platform verifier's own record is included unchanged under `verification`. Exit: 0 accepted, 1 failed,
3 verified-unaccepted, 4 historical-acceptance, 2 usage.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _load(path: Path, pin: str, what: str):
    got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if got != pin:
        raise SystemExit(f"{what} sha256 {got} does not match the pin {pin}")
    spec = importlib.util.spec_from_file_location(f"_pinned_{what.replace(' ', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def current_acceptance(V, A, archive: Path, exp: dict, policy: dict, *, historical=False, supplied=(), gh=None,
                       now: datetime | None = None, **verify_kw) -> dict:  # fmt: skip
    now = now or datetime.now(UTC)
    gh = A.Observed(gh or V.default_gh)
    auths = list(supplied)
    currency: dict = {
        "purpose": "historical" if historical else "operational",
        "observed_at": now.isoformat(),
    }
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="current-platform-") as td:
        pol = policy
        if not historical:
            snap, pinned, problems = A.current_authorizations(
                V, gh, policy.get("authorization") or {}, Path(td), "authorization state"
            )
            auths += list(snap.get("files", []))
            pol = {**policy, "authorization": pinned}
            if snap and not A.still_current(V, gh, policy["authorization"], snap["head_commit"]):
                problems.append("the evidence ref moved while it was being read (fail closed; re-run)")
            if gh.failures:
                problems.append(f"{len(gh.failures)} GitHub call(s) failed, e.g. {gh.failures[0]}")
            ok = not problems
            currency |= {
                "status": "current" if ok else "unverifiable",
                "max_age_seconds": A.DEFAULT_MAX_AGE,
                "valid_until": (now + timedelta(seconds=A.DEFAULT_MAX_AGE)).isoformat() if ok else None,
                "evidence": {k: v for k, v in snap.items() if k != "files"},
            }
        else:
            currency["status"] = "historical"
        doc = V.verify(archive, exp, pol, gh=gh, authorizations=auths, now=now, **verify_kw)
    acc = doc["acceptance"]["state"]
    if problems:
        state, why = "failed", problems
    elif acc != "accepted":
        state, why = acc, doc["acceptance"]["reasons"]
    elif historical:
        state, why = (
            "historical-acceptance",
            ["accepted against the supplied records only: NOT a current acceptance"],
        )
    else:
        state, why = "accepted", doc["acceptance"]["reasons"]
    return {"verification": doc, "currency": currency, "current_decision": {"state": state, "reasons": why}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("archive", type=Path)
    ap.add_argument("--verify-release", type=Path, required=True)
    ap.add_argument("--verify-release-sha256", required=True, help="operator pin")
    ap.add_argument(
        "--app-verifier", type=Path, required=True, help="tools/verify_app_release.py (snapshot code)"
    )
    ap.add_argument("--app-verifier-sha256", required=True, help="operator pin")
    ap.add_argument("--version", required=True)
    ap.add_argument("--source-revision", required=True)
    ap.add_argument("--archive-sha256", required=True)
    ap.add_argument("--tree-digest")
    ap.add_argument("--policy", type=Path, required=True)
    ap.add_argument("--policy-sha256", required=True, help="operator pin of the trust policy")
    ap.add_argument("--authorization", type=Path, action="append", default=[])
    ap.add_argument("--environment", type=Path)
    ap.add_argument("--continuity", type=Path)
    ap.add_argument("--bundle", type=Path)
    ap.add_argument("--sbom-bundle", type=Path)
    ap.add_argument("--historical", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    V = _load(a.verify_release, a.verify_release_sha256, "platform verifier")
    A = _load(a.app_verifier, a.app_verifier_sha256, "application verifier")
    if hashlib.sha256(a.policy.read_bytes()).hexdigest() != a.policy_sha256:
        print("trust policy does not match its operator pin", file=sys.stderr)
        return 2
    exp = {"version": a.version, "source_revision": a.source_revision, "archive_sha256": a.archive_sha256,
           "ref": f"refs/tags/v{a.version}", **({"tree_digest": a.tree_digest} if a.tree_digest else {})}  # fmt: skip
    doc = current_acceptance(
        V, A, a.archive, exp, json.loads(a.policy.read_text()), historical=a.historical, supplied=a.authorization,
        environment=a.environment, continuity=a.continuity, bundle=a.bundle, sbom_bundle=a.sbom_bundle,
    )  # fmt: skip
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if a.out:
        a.out.write_text(text)
    for c in doc["verification"]["checks"]:
        print(
            f"{c['status'].upper():7} {c['id']}"
            + (f"  ({c['detail']})" if c["detail"] and c["status"] == "failed" else "")
        )
    cd = doc["current_decision"]
    print(f"current acceptance: {cd['state']}  {'; '.join(cd['reasons'])}")
    return {"accepted": 0, "failed": 1, "verified-unaccepted": 3, "historical-acceptance": 4}.get(
        cd["state"], 1
    )


if __name__ == "__main__":
    sys.exit(main())
