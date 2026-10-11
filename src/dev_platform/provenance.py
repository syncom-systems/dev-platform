"""Application-release provenance assembly and rollback selection (M4 groundwork).

Principle (ADR 0012): rollback selects a *previously approved, immutable* application release whose
source, dependency resolution, platform/toolchain identity, evidence and authorization are already
linked by digest. Nothing here deploys; it assembles records and answers the selection query, failing
closed: an incomplete or unverifiable link makes a candidate ineligible, with the reason.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from dev_platform import records
from dev_platform.errors import ConfigError


def resolution_digest(files: list[Path], root: Path) -> str:
    """Digest of dependency resolution inputs (lock files): names and bytes, order-independent."""
    h = hashlib.sha256()
    for f in sorted(files, key=lambda p: Path(p).resolve().relative_to(root.resolve()).as_posix()):
        rel = Path(f).resolve().relative_to(root.resolve()).as_posix().encode()
        data = Path(f).read_bytes()
        h.update(len(rel).to_bytes(8, "big") + rel + len(data).to_bytes(8, "big") + data)
    return h.hexdigest()


def certified_problems(result: dict) -> list[str]:
    """Why a result record cannot back an application release (empty when it can)."""
    p = []
    cert = result.get("certification") or {}
    env = result.get("environment") or {}
    if result.get("schema") != "dev-platform.result/v1":
        p.append("not a dev-platform.result/v1 record")
    if result.get("stage") != "full" or not result.get("executed"):
        p.append("result is not an executed full-stage run")
    if not cert.get("certified"):
        p.append(f"result is not certified: {cert.get('blockers')}")
    if (result.get("platform") or {}).get("mode") != "pinned":
        p.append("platform was not a pinned release")
    if env.get("assurance") != "certifiable":
        p.append("environment is not certifiable")
    if not result.get("revision"):
        p.append("source revision unknown")
    return p


def assemble(
    result: dict,
    *,
    name: str,
    version: str,
    source_uri: str,
    artifacts: list[dict],
    resolution: str,
) -> dict:
    """Build an app-release/v1 record from a certified result. Refuses anything else."""
    problems = certified_problems(result)
    if problems:
        raise ConfigError([f"cannot assemble application release: {p}" for p in problems])
    env = result["environment"]
    doc = {
        "schema": records.APP_RELEASE,
        "application": {"name": name, "version": version},
        "source": {"uri": source_uri, "revision": result["revision"]},
        "dependencies": {"resolution_digest": resolution},
        "platform": {
            "release_version": env["release"]["version"],
            "release_tree_digest": env["release"]["tree_digest"],
            "profile": env["profile"],
            "toolchain_identity_digest": env["identity_digest"],
        },
        "artifacts": sorted(artifacts, key=lambda a: a["name"]),
        "evidence": [{"kind": "result", "sha256": records.canonical_digest(result)}],
    }
    errs = records.validate_app_release(doc)
    if errs:
        raise ConfigError(errs)
    return doc


def link_problems(
    rel: dict,
    results: dict[str, dict],
    authorizations: list[dict],
    advisories: list[dict],
    platform_releases: dict,
) -> list[str]:
    """Everything that stops this release from being a rollback target. Empty means eligible."""
    problems = [f"invalid record: {e}" for e in records.validate_app_release(rel)]
    if problems:
        return problems
    for ev in rel["evidence"]:
        res = results.get(ev["sha256"])
        if res is None:
            problems.append(f"evidence {ev['sha256'][:12]} not available (cannot be verified)")
            continue
        if records.canonical_digest(res) != ev["sha256"]:
            problems.append(f"evidence {ev['sha256'][:12]} does not match its digest")
            continue
        problems += [f"evidence: {p}" for p in certified_problems(res)]
        env = res.get("environment", {})
        checks = [
            (res.get("revision"), rel["source"]["revision"], "source revision"),
            (env.get("identity_digest"), rel["platform"]["toolchain_identity_digest"], "toolchain identity"),
            (
                (env.get("release") or {}).get("tree_digest"),
                rel["platform"]["release_tree_digest"],
                "platform tree",
            ),
            (env.get("profile"), rel["platform"]["profile"], "profile"),
        ]
        problems += [f"evidence {what} differs from the release" for got, want, what in checks if got != want]
    digest = records.canonical_digest(rel)
    subject_auth = [
        a
        for a in authorizations
        if a["subject"]["kind"] == "application-release" and not records.validate_authorization(a)
    ]
    if records.effective_decision(subject_auth, digest) is None:
        problems.append("no effective approval bound to this exact release record")
    ver = rel["platform"]["release_version"]
    plat = platform_releases.get(ver)
    for adv in advisories:
        hit = records.releases_affected(adv, {ver: plat or {}})
        if hit:
            problems.append(f"platform release {ver} is affected by advisory {adv['id']}")
    return problems


def _auth_reasons(approval: dict) -> list[str]:
    """What each supplied/discovered authorization record amounted to, from the verifier's own evidence."""
    out = []
    for v in approval.get("authorization_evidence", []):
        if v.get("status") == "authentic":
            out.append(f"{v['file']}: authentic {v.get('decision')} by {v.get('approver')}")
        elif v.get("problems") and not any("subject.digest" in p for p in v["problems"]):
            out.append(f"{v['file']}: ignored ({'; '.join(v['problems'])})")
    return out


def select_rollback(
    application: str,
    current: str,
    releases: list[dict],
    results: dict[str, dict],
    authorizations: list[dict],
    *,
    advisories: list[dict] = (),
    platform_releases: dict | None = None,
    authenticate=None,
    immutable: set[str] | None = None,
) -> dict:
    """Eligible earlier releases (most recently approved first) and why each other one is not.

    With `authenticate` (an `appverify.AppVerifier`) every candidate is judged by the independent verifier:
    authenticated, authorized, exactly bound, in force. Without it only the shape of the approval records is
    checked and the output says `approval_authentication: unverified`; that mode is diagnostic and is never
    an approval (ADR 0016, ADR 0019). With `immutable` (digests of releases from pinned evidence bundles)
    anything else is ineligible: a rollback target is an exact, previously approved, immutable release.
    """
    plat = platform_releases or {}
    eligible, rejected = [], []
    for rel in releases:
        app = rel.get("application") or {}
        if app.get("name") != application or app.get("version") == current:
            continue
        entry = {"version": app.get("version"), "release_sha256": records.canonical_digest(rel)}
        if immutable is not None and entry["release_sha256"] not in immutable:
            rejected.append(
                {**entry, "reasons": ["release record is not from a pinned evidence bundle (not immutable)"]}
            )
            continue
        if authenticate is not None:
            rec = authenticate(rel)
            ap = rec["approval"]
            if ap["state"] == "approved":
                eligible.append(
                    {
                        **entry,
                        "approved_at": ap["decided_at"],
                        "authorization": ap["authorization"],
                        "approver": ap["approver"],
                        "coverage": rec["coverage"],
                    }
                )
            else:
                failed = [f"{c['id']}: {c['detail']}" for c in rec["checks"] if c["status"] == "failed"]
                rejected.append({**entry, "reasons": (failed or ap["reasons"]) + _auth_reasons(ap)})
            continue
        probs = link_problems(rel, results, authorizations, list(advisories), plat)
        if probs:
            rejected.append({**entry, "reasons": probs})
            continue
        dec = records.effective_decision(
            [a for a in authorizations if a["subject"]["kind"] == "application-release"],
            entry["release_sha256"],
        )
        eligible.append({**entry, "approved_at": dec["decided_at"], "authorization": dec["id"]})
    eligible.sort(key=lambda e: e["approved_at"], reverse=True)
    return {
        "application": application,
        "current": current,
        "approval_authentication": "verified" if authenticate is not None else "unverified",
        "eligible": eligible,
        "rejected": rejected,
    }
