"""Consumer-owned infrastructure configuration pin and provider resolution (issue #99, ADR 0021).

The consumer declares exactly which infrastructure configuration release it expects
(`[infra] provider/config_release/config_digest`, no "latest"). The platform never trusts what a provider
volunteers: it compares the resolved identity with the pin and refuses a mismatch, so a provider cannot
silently supply a newer configuration. Resolution needs no private access in untrusted CI:

- untrusted events never invoke a provider; a vendored profile file is used only if its sha256 equals the pin
  (profiles carry runner labels and credential class names, never values), otherwise routing is hosted-only;
- trusted events may invoke an operator-supplied resolver (never a command from project configuration)
  or use the same vendored file.

`evaluate` is a pure function over (pin, request, result, profile bytes) so a provider can run the same
conformance cases (contracts/infra/v1/resolution-cases.json) in its own CI, without this repository's code.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config import InfraPin
from .runners import INFRA_SCHEMA, validate_profile

RESOLVE_REQUEST = "dev-platform.infra-resolve-request/v1"
RESOLVE_RESULT = "dev-platform.infra-resolve-result/v1"
DECISIONS = ("resolved", "public-default", "denied")


# status values recorded in the result record
RESOLVED, HOSTED_ONLY, UNAVAILABLE, UNPINNED = "resolved", "hosted-only", "unavailable", "unpinned"


@dataclass
class InfraResolution:
    """What was resolved, as evidence. `profile` is the validated runner profile (never logged)."""

    status: str
    source: str  # "none" | "vendored-file" | "resolver"
    reasons: list[str] = field(default_factory=list)
    pin: InfraPin | None = None
    resolved: dict | None = None
    authorization_policy: dict | None = None
    effective_profile_digest: str | None = None
    profile: dict | None = None
    profile_path: Path | None = None

    @property
    def blocks(self) -> bool:
        """A declared pin that could not be honoured blocks admission (ADR 0006); hosted-only does not."""
        return self.status in (UNAVAILABLE, UNPINNED)

    def evidence(self) -> dict:
        return {
            "status": self.status,
            "source": self.source,
            "pinned": (
                {
                    "provider": self.pin.provider,
                    "config_release": self.pin.config_release,
                    "config_digest": self.pin.config_digest,
                }
                if self.pin
                else None
            ),
            "resolved": self.resolved,
            "authorization_policy": self.authorization_policy,
            "effective_profile_digest": self.effective_profile_digest,
            "contract": INFRA_SCHEMA,
            "reasons": list(self.reasons),
        }


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def request_for(pin: InfraPin, *, repo: str | None, event_trust: str) -> dict:
    return {
        "schema_version": RESOLVE_REQUEST,
        "repo": repo,
        "event_trust": event_trust,
        "contract": INFRA_SCHEMA,
        "requested": {"version": pin.config_release, "digest": pin.config_digest},
    }


def _unavailable(pin, source, *reasons, **kw) -> InfraResolution:
    return InfraResolution(UNAVAILABLE, source, list(reasons), pin, **kw)


def evaluate(pin: InfraPin, request: dict, result: object, profile_bytes: bytes | None) -> InfraResolution:
    """Judge one provider result against the consumer's pin. Fail closed: surprises are unavailable."""
    src = "resolver"
    if not isinstance(result, dict):
        return _unavailable(pin, src, "resolver result is not a JSON object")
    if result.get("schema_version") != RESOLVE_RESULT:
        return _unavailable(pin, src, f"resolver result schema must be {RESOLVE_RESULT}")
    if result.get("contract", INFRA_SCHEMA) != INFRA_SCHEMA:
        return _unavailable(
            pin, src, f"unsupported contract {result.get('contract')!r}; this platform speaks {INFRA_SCHEMA}"
        )
    decision = result.get("decision")
    reasons = [str(r) for r in result.get("reasons", []) if isinstance(r, str)]
    if decision not in DECISIONS:
        return _unavailable(pin, src, f"unknown decision {decision!r}")
    if result.get("requested") != request["requested"]:
        return _unavailable(pin, src, "provider did not echo the requested version and digest", *reasons)
    policy = result.get("authorization_policy")
    if decision == "denied":
        return _unavailable(pin, src, "provider denied the request", *reasons, authorization_policy=policy)
    if decision == "public-default":
        return InfraResolution(
            HOSTED_ONLY,
            src,
            reasons or ["provider selected the public default"],
            pin,
            authorization_policy=policy,
        )
    # decision == "resolved": the identity must equal the pin exactly, and the profile must be the one named
    resolved = result.get("resolved")
    want = {"version": pin.config_release, "digest": pin.config_digest}
    if resolved != want:
        return _unavailable(
            pin,
            src,
            f"resolved {resolved!r} is not the pinned {want!r}",
            *reasons,
            resolved=resolved if isinstance(resolved, dict) else None,
        )
    if profile_bytes is None:
        return _unavailable(pin, src, "provider resolved but supplied no profile", resolved=resolved)
    eff = "sha256:" + hashlib.sha256(profile_bytes).hexdigest()
    if result.get("effective_profile_digest") != eff:
        return _unavailable(
            pin, src, "effective_profile_digest does not match the supplied profile", resolved=resolved
        )
    try:
        doc = json.loads(profile_bytes)
    except json.JSONDecodeError as e:
        return _unavailable(pin, src, f"profile is not JSON: {e}", resolved=resolved)
    problems = validate_profile(doc)
    if problems:
        return _unavailable(pin, src, *(f"profile: {p}" for p in problems), resolved=resolved)
    return InfraResolution(
        RESOLVED,
        src,
        reasons,
        pin,
        resolved=resolved,
        authorization_policy=policy,
        effective_profile_digest=eff,
        profile=doc,
    )


def from_vendored_file(pin: InfraPin, path: Path) -> InfraResolution:
    """A profile file in the consumer's repository: identity is its digest, which must equal the pin."""
    src = "vendored-file"
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        return _unavailable(pin, src, f"cannot read {path}: {e}")
    eff = "sha256:" + hashlib.sha256(data).hexdigest()
    if eff != pin.config_digest:
        return _unavailable(
            pin,
            src,
            f"profile digest {eff} is not the pinned {pin.config_digest}",
            effective_profile_digest=eff,
        )
    try:
        doc = json.loads(data)
    except json.JSONDecodeError as e:
        return _unavailable(pin, src, f"profile is not JSON: {e}", effective_profile_digest=eff)
    problems = validate_profile(doc)
    if problems:
        return _unavailable(pin, src, *(f"profile: {p}" for p in problems), effective_profile_digest=eff)
    return InfraResolution(
        RESOLVED,
        src,
        ["digest equals the pin; release name is the consumer's declaration"],
        pin,
        resolved={"version": pin.config_release, "digest": pin.config_digest},
        effective_profile_digest=eff,
        profile=doc,
        profile_path=Path(path),
    )


def run_resolver(
    pin: InfraPin, argv: list[str], *, repo: str | None, event_trust: str, scratch: Path, timeout: int = 60
) -> InfraResolution:
    """Invoke an operator-supplied provider command: request JSON on stdin, result JSON on stdout, profile at
    the path named in the request. Only called for trusted events; the caller enforces that."""
    request = request_for(pin, repo=repo, event_trust=event_trust)
    profile_out = scratch / "infra-profile.json"
    request["profile_out"] = str(profile_out)
    try:
        cp = subprocess.run(
            argv, input=json.dumps(request), capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return _unavailable(pin, "resolver", f"resolver could not run: {type(e).__name__}")
    if cp.returncode != 0:
        return _unavailable(pin, "resolver", f"resolver exited {cp.returncode}")
    try:
        result = json.loads(cp.stdout)
    except json.JSONDecodeError:
        return _unavailable(pin, "resolver", "resolver output is not JSON")
    data = profile_out.read_bytes() if profile_out.is_file() else None
    r = evaluate(pin, request, result, data)
    if r.profile is not None:
        r.profile_path = profile_out
    return r


def resolve(
    pin: InfraPin | None,
    *,
    event_trust: str,
    repo: str | None,
    profile_file: Path | None,
    resolver_argv: list[str] | None,
    scratch: Path,
) -> InfraResolution:
    if pin is None:
        if profile_file is None and not resolver_argv:
            return InfraResolution(HOSTED_ONLY, "none", ["no [infra] pin: hosted runners only"], None)
        # A profile or resolver without a pin would let the provider choose the configuration silently.
        digest = file_digest(profile_file) if profile_file and Path(profile_file).is_file() else None
        return InfraResolution(
            UNPINNED,
            "none",
            ["an infra profile or resolver was supplied but dev-platform.toml has no [infra] pin; not used"],
            None,
            effective_profile_digest=digest,
        )
    if event_trust != "trusted":
        # Untrusted events never reach a provider. A vendored profile is public data: usable only if pinned.
        if profile_file is not None:
            r = from_vendored_file(pin, profile_file)
            if r.status == RESOLVED:
                return r
            return InfraResolution(
                UNAVAILABLE, r.source, r.reasons, pin, effective_profile_digest=r.effective_profile_digest
            )
        return InfraResolution(
            HOSTED_ONLY, "none", ["untrusted event: no provider consulted; hosted runners only"], pin
        )
    if resolver_argv:
        return run_resolver(pin, resolver_argv, repo=repo, event_trust=event_trust, scratch=scratch)
    if profile_file is not None:
        return from_vendored_file(pin, profile_file)
    return _unavailable(pin, "none", "an [infra] pin is declared but no profile or resolver was supplied")


def conformance(cases_file: Path, base: Path) -> list[str]:
    """Run resolution-cases.json; returns the failures (empty = all as expected)."""
    spec = json.loads(Path(cases_file).read_text())
    failures = []
    for c in spec["cases"]:
        pin = InfraPin(**c["pin"])
        profile = (base / c["profile"]).read_bytes() if c.get("profile") else None
        r = evaluate(pin, request_for(pin, repo="o/r", event_trust="trusted"), c["result"], profile)
        if r.status != c["expect"]["status"]:
            failures.append(f"{c['name']}: status {r.status} != {c['expect']['status']}")
        elif c["expect"].get("reason") and not any(c["expect"]["reason"] in x for x in r.reasons):
            failures.append(
                f"{c['name']}: expected reason containing {c['expect']['reason']!r}, got {r.reasons}"
            )
    return failures


__all__ = ["InfraResolution", "conformance", "evaluate", "file_digest", "resolve"]
