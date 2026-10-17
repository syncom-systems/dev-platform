"""Current infrastructure authorization policy: it narrows or revokes, it never grants (ADR 0023).

A configuration release is immutable, but what an organization authorizes changes: a runner is withdrawn, a
credential class is revoked, a release turns out to be unsafe. That is a separate, mutable document with its
own identity (`policy_id`, `revision`, digest), kept outside every release so it never changes a release's
identity:

    {"schema_version": 1, "policy_id": "...", "revision": 3,
     "minimum_release": "YYYY.MM.N",                      releases below are denied (stale)
     "revoked_releases": [{"version": "...", "reason": "..."}],
     "repositories_enabled": ["name", ...],               only these repositories resolve at all
     "withdrawn": {"runner_classes": [...], "credentials": [...]},
     "repository_withdrawn": {"name": {"runner_classes": [...], "credentials": [...]}}}

Exactly these keys: the format has no field that adds anything, and an unknown key is invalid (fail closed),
so a newer policy can never reinstate or widen what a pinned release grants. The effective profile is the
release's profile minus the withdrawals; a stale or revoked release is denied, not narrowed. Without a valid
policy nothing resolves.
"""

from __future__ import annotations

import hashlib
import json

from dev_platform.infra_release import ReleaseError, version_key

KEYS = {
    "schema_version",
    "policy_id",
    "revision",
    "minimum_release",
    "revoked_releases",
    "repositories_enabled",
    "withdrawn",
    "repository_withdrawn",
}
_WITHDRAWN = {"runner_classes", "credentials"}


def policy_digest(doc: dict) -> str:
    """Identity of a policy document: sha256 of its compact, key-sorted JSON (independent of formatting)."""
    return (
        "sha256:"
        + hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )


def _strs(v: object) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) and x for x in v)


def problems(p: object) -> list[str]:
    if not isinstance(p, dict) or set(p) != KEYS:
        return [f"authorization policy: exactly the keys {sorted(KEYS)}"]
    errs: list[str] = []
    if p["schema_version"] != 1 or isinstance(p["schema_version"], bool):
        errs.append("schema_version must be 1")
    if not isinstance(p["policy_id"], str) or not p["policy_id"]:
        errs.append("policy_id: non-empty string")
    if not isinstance(p["revision"], int) or isinstance(p["revision"], bool) or p["revision"] < 1:
        errs.append("revision: positive integer")
    try:
        version_key(p["minimum_release"])
    except ReleaseError as e:
        errs.append(f"minimum_release: {e.detail}")
    if not isinstance(p["revoked_releases"], list):
        errs.append("revoked_releases: list")
    else:
        for r in p["revoked_releases"]:
            if not isinstance(r, dict) or "version" not in r or set(r) - {"version", "reason"}:
                errs.append("revoked_releases: entries {version, reason?}")
                continue
            try:
                version_key(r["version"])
            except ReleaseError as e:
                errs.append(f"revoked_releases: {e.detail}")
    if not _strs(p["repositories_enabled"]):
        errs.append("repositories_enabled: list of repository names")
    w = p["withdrawn"]
    if not isinstance(w, dict) or set(w) != _WITHDRAWN or not all(_strs(v) for v in w.values()):
        errs.append("withdrawn: {runner_classes: [..], credentials: [..]}")
    rw = p["repository_withdrawn"]
    if not isinstance(rw, dict) or not all(
        isinstance(v, dict) and set(v) <= _WITHDRAWN and all(_strs(x) for x in v.values())
        for v in rw.values()
    ):
        errs.append("repository_withdrawn: {repository: {runner_classes?: [..], credentials?: [..]}}")
    return errs


def validate(p: object) -> dict:
    if errs := problems(p):
        raise ReleaseError("policy-invalid", "; ".join(errs))
    return p  # type: ignore[return-value]


def identity(p: dict) -> dict:
    """The policy identity as recorded in evidence and on the wire (`revision` is a string there)."""
    return {"id": p["policy_id"], "revision": str(p["revision"]), "digest": policy_digest(p)}


def admits(p: dict, version: str, repository: str) -> tuple[str, str] | None:
    """None if the policy admits this release for this repository, else (denial code, detail)."""
    if version_key(version) < version_key(p["minimum_release"]):
        return "release-stale", f"below the current minimum release {p['minimum_release']}"
    if any(r["version"] == version for r in p["revoked_releases"]):
        return "release-revoked", "release revoked by current authorization policy"
    if repository not in p["repositories_enabled"]:
        return "repo-not-enabled", "repository is not authorized by current policy"
    return None


def narrow(profile: dict, p: dict, repository: str) -> tuple[dict, list[str]]:
    """(effective profile, what was withdrawn). Only removes runners and credential classes; everything else
    in the profile is copied unchanged, so the result is never wider than the release's profile."""
    rw = p["repository_withdrawn"].get(repository, {})
    gone_runners = set(p["withdrawn"]["runner_classes"]) | set(rw.get("runner_classes", []))
    gone_creds = set(p["withdrawn"]["credentials"]) | set(rw.get("credentials", []))
    runners, narrowed = [], []
    for r in profile.get("runners", []):
        if r["id"] in gone_runners:
            narrowed.append(f"runner_class:{r['id']}")
            continue
        creds = r.get("credentials", [])
        narrowed += [f"credential:{r['id']}:{c}" for c in sorted(set(creds) & gone_creds)]
        runners.append({**r, "credentials": [c for c in creds if c not in gone_creds]})
    return {**profile, "runners": runners}, narrowed


def is_narrower(effective: dict, release: dict) -> bool:
    """Does `effective` grant nothing `release` does not: same runners or fewer, each identical except for a
    subset of its credentials, and the same admission section."""
    if effective.get("schema") != release.get("schema") or effective.get("admission") != release.get(
        "admission"
    ):
        return False
    base = {r["id"]: r for r in release.get("runners", [])}
    for r in effective.get("runners", []):
        b = base.get(r["id"])
        if b is None:
            return False
        if {k: v for k, v in r.items() if k != "credentials"} != {
            k: v for k, v in b.items() if k != "credentials"
        }:
            return False
        if not set(r.get("credentials", [])) <= set(b.get("credentials", [])):
            return False
    return True


__all__ = ["admits", "identity", "is_narrower", "narrow", "policy_digest", "problems", "validate"]
