"""Portable evidence/governance records and supply-chain queries.

These are *contracts*, not a deployment manager or QMS: external release and governance systems
produce/consume them. Technical identity (a result), verification evidence, change authorization and
release approval are separate record kinds that reference each other only by digest.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from datetime import datetime
from pathlib import Path

APP_RELEASE = "dev-platform.app-release/v1"
AUTHORIZATION = "dev-platform.authorization/v1"
ADVISORY = "dev-platform.advisory/v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
# Explicit registry: an identity provider is supported only if listed here AND the consuming verifier
# implements its verification. Anything else (including git authorship) fails closed. Note: this checks the
# shape only; it does not authenticate. See tools/verify_release.py for the authoritative verification.
IDENTITY_PROVIDERS = {"github-signed-commit"}


def canonical_digest(doc: object) -> str:
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _req(d: dict, keys: list[str], where: str, errs: list[str]) -> None:
    for k in keys:
        if d.get(k) in (None, "", []):
            errs.append(f"{where}.{k}: required")


def _sha(v: object, where: str, errs: list[str]) -> None:
    if not (isinstance(v, str) and _SHA.match(v)):
        errs.append(f"{where}: must be 64 lowercase hex characters")


def _ts(v: object, where: str, errs: list[str]) -> None:
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if t.tzinfo is None or t.utcoffset().total_seconds() != 0:
            raise ValueError
    except ValueError:
        errs.append(f"{where}: RFC 3339 UTC timestamp required (e.g. 2026-10-10T12:00:00Z)")


def validate_app_release(d: dict) -> list[str]:
    e: list[str] = []
    if d.get("schema") != APP_RELEASE:
        return [f"schema must be {APP_RELEASE!r}"]
    for sec, keys in (
        ("application", ["name", "version"]),
        ("source", ["uri", "revision"]),
        ("dependencies", ["resolution_digest"]),
        ("platform", ["release_version", "release_tree_digest", "profile", "toolchain_identity_digest"]),
    ):
        _req(d.get(sec) or {}, keys, sec, e)
    for path in (
        "dependencies.resolution_digest",
        "platform.release_tree_digest",
        "platform.toolchain_identity_digest",
    ):
        a, b = path.split(".")
        _sha((d.get(a) or {}).get(b), path, e)
    if not d.get("artifacts"):
        e.append("artifacts: at least one built artifact with a digest is required")
    for i, a in enumerate(d.get("artifacts") or []):
        _req(a, ["name"], f"artifacts[{i}]", e)
        _sha(a.get("sha256"), f"artifacts[{i}].sha256", e)
    if not d.get("evidence"):
        e.append("evidence: at least one verification result reference is required")
    for i, v in enumerate(d.get("evidence") or []):
        _req(v, ["kind"], f"evidence[{i}]", e)
        _sha(v.get("sha256"), f"evidence[{i}].sha256", e)
    for i, a in enumerate(d.get("authorizations") or []):
        _sha(a.get("record_sha256"), f"authorizations[{i}].record_sha256", e)
    return e


def validate_authorization(d: dict) -> list[str]:
    e: list[str] = []
    if d.get("schema") != AUTHORIZATION:
        return [f"schema must be {AUTHORIZATION!r}"]
    _req(d, ["id", "subject", "decision", "decided_by", "basis", "decided_at", "retention"], "", e)
    if d.get("decision") not in ("approved", "rejected", "revoked"):
        e.append("decision: approved|rejected|revoked")
    sub = d.get("subject") or {}
    if sub.get("kind") not in ("application-release", "platform-release", "change"):
        e.append("subject.kind: application-release|platform-release|change")
    _sha(sub.get("digest"), "subject.digest", e)
    by = d.get("decided_by") or {}
    _req(by, ["id", "role"], "decided_by", e)
    ia = by.get("identity_assertion") or {}
    if not ia.get("provider") or not ia.get("reference"):
        e.append(
            "decided_by.identity_assertion: provider and reference required "
            "(a name in a commit is not an approval identity)"
        )
    elif ia["provider"] not in IDENTITY_PROVIDERS:
        e.append(f"decided_by.identity_assertion.provider {ia['provider']!r} is not a supported provider")
    _req(d.get("basis") or {}, ["kind", "reference"], "basis", e)
    _ts(d.get("decided_at"), "decided_at", e)
    ret = d.get("retention") or {}
    if "class" not in ret or "until" not in ret:
        e.append("retention: class and until (timestamp or null for indefinite) required")
    elif ret["until"] is not None:
        _ts(ret["until"], "retention.until", e)
    return e


def validate_advisory(d: dict) -> list[str]:
    e: list[str] = []
    if d.get("schema") != ADVISORY:
        return [f"schema must be {ADVISORY!r}"]
    _req(d, ["id", "summary", "severity", "affected"], "", e)
    for i, a in enumerate(d.get("affected") or []):
        if not a.get("component") or not a.get("versions"):
            e.append(f"affected[{i}]: component and versions required")
    return e


_VALIDATORS = {
    APP_RELEASE: validate_app_release,
    AUTHORIZATION: validate_authorization,
    ADVISORY: validate_advisory,
}


def validate_file(path: Path) -> list[str]:
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as ex:
        return [f"{path}: {ex}"]
    fn = _VALIDATORS.get(doc.get("schema"))
    return [f"unknown schema {doc.get('schema')!r}"] if fn is None else fn(doc)


def effective_decision(records: list[dict], subject_digest: str) -> dict | None:
    """The current decision for a subject: the latest record not superseded by another.

    Supersession is explicit (`supersedes` ids), never inferred from time alone. Returns None if
    nothing applies or the effective decision is not 'approved'.
    """
    mine = [r for r in records if r["subject"]["digest"] == subject_digest]
    superseded = {s for r in mine for s in r.get("supersedes", [])}
    live = sorted((r for r in mine if r["id"] not in superseded), key=lambda r: r["decided_at"])
    return live[-1] if live and live[-1]["decision"] == "approved" else None


def releases_affected(advisory: dict, releases: dict[str, dict]) -> dict[str, list[str]]:
    """version -> matched components, for releases whose SBOM or platform version is listed."""
    out: dict[str, list[str]] = {}
    for ver, rel in releases.items():
        sbom = rel.get("sbom_doc", {})
        have = {("dev-platform", ver)} | {(c["name"], c["version"]) for c in sbom.get("components", [])}
        hits = [
            f"{a['component']}@{v}"
            for a in advisory["affected"]
            for v in a["versions"]
            if (a["component"], v) in have
        ]
        if hits:
            out[ver] = sorted(hits)
    return out


def consumer_release(path: Path) -> str | None:
    """Platform release version a consumer artifact refers to (config pin, result or app-release)."""
    p = Path(path)
    try:
        if p.suffix == ".toml":
            return tomllib.loads(p.read_text()).get("platform", {}).get("version")
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if d.get("schema") == APP_RELEASE:
        return d["platform"]["release_version"]
    if str(d.get("schema", "")).startswith("dev-platform.result/"):
        return d["environment"]["release"]["version"]
    return None
