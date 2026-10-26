"""The provider side of the infrastructure resolution contract (ADR 0021, ADR 0023), for any organization.

`resolve(root, request)` answers a `dev-platform.infra-resolve-request/v1` from a configuration root (a
configuration repository checkout or a local store, `infra_release` layout) and the current authorization
policy (`authorization/current.v1.json`). The engine judges the answer with `infra.evaluate`; this module is
the generic implementation an operator can name as `--infra-resolver "dev-platform infra resolve --root
DIR"`.

Rules, all fail closed (a denial is a result, never an exception):
- the selection is the consumer's exact version and release-tree digest; nothing defaults to "latest";
- an untrusted event gets `public-default`: no policy is needed or read, and no release is read;
- for a trusted event, without a valid current authorization policy nothing resolves;
- the release is verified from the same bytes that are parsed, must be a supported format, must serve the
  requesting owner and repository, and must be admitted by the current policy (floor, revocation, enablement);
- the effective profile is the release's profile narrowed by the policy, never widened.

Returns {"result": the exact public result, "evidence": an audit record with stable denial codes (identities
and digests only, safe to log), "profile": the effective profile, "profile_bytes": its exact bytes}. The
profile goes only to the trusted caller's `profile_out`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from dev_platform import infra_authz
from dev_platform.infra import RESOLVE_REQUEST, RESOLVE_RESULT
from dev_platform.infra_release import (
    INDEX,
    WIRE_DIGEST_RE,
    ReleaseError,
    canonical,
    digest_of,
    load_index,
    manifest_of,
    read_tree,
    version_key,
    wire,
)
from dev_platform.runners import INFRA_SCHEMA

RESOLUTION = "dev-platform.infra-resolution/v1"
POLICY = "authorization/current.v1.json"
_REQ_KEYS = {"schema_version", "repo", "event_trust", "contract", "requested", "profile_out"}
_REPO = re.compile(r"([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9][A-Za-z0-9._-]{0,99})")


def _finish(ev: dict, code: str | None = None, detail: str | None = None, profile=None, data=None) -> dict:
    if code is not None:
        ev["decision"] = "denied"
        ev["reasons"].append({"code": code, "detail": detail})
    pol = ev["authorization_policy"]
    result = {
        "schema_version": RESOLVE_RESULT,
        "contract": INFRA_SCHEMA,
        "decision": ev["decision"],
        "reasons": [f"{r['code']}: {r['detail']}" for r in ev["reasons"]],
        "requested": ev["requested"],
        "resolved": ev["resolved"] if ev["decision"] == "resolved" else None,
        "authorization_policy": (
            {"id": pol["id"], "revision": str(pol["revision"]), "digest": pol["digest"]} if pol else None
        ),
    }
    if ev["decision"] == "resolved":
        result["effective_profile_digest"] = ev["effective_profile_digest"]
    else:
        profile = data = None
    return {"result": result, "evidence": ev, "profile": profile, "profile_bytes": data}


def load_policy(path: Path) -> dict:
    try:
        doc = json.loads(Path(path).read_bytes())
    except OSError as e:
        raise ReleaseError(
            "policy-invalid", f"current authorization policy unavailable: {e.strerror or e}"
        ) from None
    except ValueError as e:
        raise ReleaseError("policy-invalid", f"current authorization policy is not JSON: {e}") from None
    return infra_authz.validate(doc)


def resolve(root: Path, request: object, policy_path: Path | None = None) -> dict:
    root = Path(root)
    ev: dict = {
        "schema": RESOLUTION,
        "decision": None,
        "reasons": [],
        "repo": None,
        "event_trust": None,
        "contract": INFRA_SCHEMA,
        "requested": None,
        "resolved": None,
        "authorization_policy": None,
        "narrowed_by_policy": [],
        "effective_profile_digest": None,
    }

    def deny(code: str, detail: str) -> dict:
        return _finish(ev, code, detail)

    if isinstance(request, dict) and isinstance(request.get("requested"), dict):
        ev["requested"] = request["requested"]  # echoed verbatim so the engine can compare
    # 1. the request: strict; the selection must be explicit and complete
    if (
        not isinstance(request, dict)
        or set(request) != _REQ_KEYS
        or request.get("schema_version") != RESOLVE_REQUEST
    ):
        return deny("request-invalid", f"expected {RESOLVE_REQUEST} with exactly {sorted(_REQ_KEYS)}")
    ev["repo"], ev["event_trust"] = request["repo"], request["event_trust"]
    if (
        request["event_trust"] not in ("trusted", "untrusted")
        or not isinstance(request["repo"], str)
        or not _REPO.fullmatch(request["repo"])
    ):
        return deny("request-invalid", "repo must be owner/name; event_trust trusted|untrusted")
    owner, name = request["repo"].split("/")
    # 2. untrusted events: public-default, with no policy and no release read (the engine never asks a
    # provider for an untrusted event; this answers a direct caller the same way). The request is strict.
    if request["event_trust"] == "untrusted":
        ev["decision"] = "public-default"
        ev["reasons"].append(
            {"code": "untrusted-event", "detail": "hosted-only public default; no private release loaded"}
        )
        return _finish(ev)
    # 3. a trusted event needs the current authorization policy: without a valid one nothing resolves
    try:
        pol = load_policy(policy_path or root / POLICY)
    except ReleaseError as e:
        return deny("policy-invalid", e.detail)
    ev["authorization_policy"] = {
        "id": pol["policy_id"],
        "revision": pol["revision"],
        "digest": infra_authz.policy_digest(pol),
    }
    if request["contract"] != INFRA_SCHEMA:
        return deny("unsupported-contract", f"supported: {INFRA_SCHEMA}")
    req = request["requested"]
    if (
        not isinstance(req, dict)
        or set(req) != {"version", "digest"}
        or not all(isinstance(v, str) for v in req.values())
    ):
        return deny(
            "selection-missing", "an exact {version, digest} selection is required; no default is applied"
        )
    try:
        version_key(req["version"])
    except ReleaseError as e:
        return deny("request-invalid", e.detail)
    if not WIRE_DIGEST_RE.fullmatch(req["digest"]):
        return deny("request-invalid", "digest must be 'sha256:' + 64 lowercase hex")
    # 4. identify and verify the release
    try:
        entry = next(
            (r for r in load_index(root / INDEX)["releases"] if r["version"] == req["version"]), None
        )
    except ReleaseError as e:
        return deny("index-invalid", e.detail)
    if entry is None:
        return deny("version-unknown", f"no release {req['version']}")
    if wire(entry["digest"]) != req["digest"]:
        return deny("digest-mismatch", "requested digest differs from the release index")
    if entry["contract"] != INFRA_SCHEMA:
        return deny("unsupported-contract", f"release implements {entry['contract']}")
    try:
        files = read_tree(root / "releases" / req["version"])
    except ReleaseError as e:
        return deny(e.code, e.detail)  # release-unreadable or release-tampered (#140)
    except OSError as e:
        return deny("release-unreadable", str(e))
    if digest_of(files) != entry["digest"]:
        return deny("release-tampered", "release content does not match its indexed digest")
    ev["resolved"] = {"version": req["version"], "digest": req["digest"]}
    try:
        manifest, release_owner = manifest_of(files, req["version"], INFRA_SCHEMA)
    except ReleaseError as e:
        return deny(e.code, e.detail)
    # 5. the current policy: floor, revocation, enablement; then the release's own assignment
    if why := infra_authz.admits(pol, req["version"], name):
        return deny(*why)
    if owner != release_owner:
        return deny("repo-not-enabled", "repository is not authorized by current policy")
    if name not in manifest["repositories"] or f"profiles/{name}.json" not in files:
        return deny("repo-not-in-release", "release has no assignment for this repository")
    # 6. narrowing: the policy can only remove
    try:
        release_profile = json.loads(files[f"profiles/{name}.json"])
        profile, narrowed = infra_authz.narrow(release_profile, pol, name)
    except (ValueError, KeyError, TypeError, AttributeError):
        return deny("unsupported-format", f"profiles/{name}.json is not a dev-platform.infra/v1 profile")
    ev["narrowed_by_policy"] = narrowed
    data = canonical(profile)
    ev["decision"] = "resolved"
    ev["effective_profile_digest"] = "sha256:" + hashlib.sha256(data).hexdigest()
    return _finish(ev, profile=profile, data=data)


def write_private(path: str, data: bytes) -> None:
    """The profile for the trusted caller: mode 0600, never through a symlink."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)


__all__ = ["POLICY", "RESOLUTION", "load_policy", "resolve", "write_private"]
