"""Release lifecycle and version policy. This module is a *reader*, never an authority.

States:   planned < implementation-complete < candidate-built < independently-verified < released;
          overlays: suspended (warning), revoked (authoritative).
`planned` and `implementation-complete` come from planning data (milestone state) and carry no trust.
Everything from `candidate-built` on is derived from verification records. `released` is a stable release
whose records say `verified` (trust/v2) and that is published as an immutable GitHub release (ADR 0024).
Releases verified under trust/v1 end in `verified-unaccepted` or `accepted` instead; `accepted` is observable
only from a result produced by running the pinned authoritative verifier (`run_verifier`): no planning input
(milestone closure, labels, merged PRs, a workflow result, a hand-written record) can produce it.
Overlays only narrow trust, but they are two different things: an unauthenticated safety *warning* suspends
use conservatively and is never recorded as a governance decision; *revocation* (and replacement of an
approval) is a governance decision, read only from authenticated, authorized records evaluated by the
pinned verifier.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError

STATES = (
    "planned",
    "implementation-complete",
    "candidate-built",
    "independently-verified",
    "released",
    "verified-unaccepted",  # trust/v1 releases (before 0.12.0)
    "accepted",  # trust/v1 releases (before 0.12.0)
)
OVERLAYS = ("suspended", "revoked")
# Forward edges only; there is deliberately no edge that targets `accepted`.
EDGES = {
    "planned": {"implementation-complete"},
    "implementation-complete": {"candidate-built"},
    "candidate-built": {"independently-verified"},
    "independently-verified": {"released", "verified-unaccepted"},
    "released": set(),
    "verified-unaccepted": set(),
}
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z]+)\.(\d+))?$")


class VerifierResult:
    """A verification record obtained by running the pinned verifier. Constructed only by run_verifier."""

    __slots__ = ("record",)
    _token = object()

    def __init__(self, record: dict, _token=None):
        if _token is not VerifierResult._token:
            raise TypeError("VerifierResult can only be produced by lifecycle.run_verifier")
        self.record = record


def run_verifier(verifier: Path, pinned_sha256: str, argv: list[str]) -> VerifierResult:
    """Run tools/verify_release.py after checking its bytes against an operator-supplied pin."""
    got = hashlib.sha256(Path(verifier).read_bytes()).hexdigest()
    if got != pinned_sha256:
        raise ConfigError([f"verifier sha256 {got} does not match the pin {pinned_sha256}"])
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "verification.json"
        subprocess.run(
            [sys.executable, "-I", str(verifier), *argv, "--out", str(out)], capture_output=True, text=True
        )
        if not out.is_file():
            raise ConfigError(["verifier produced no record"])
        return VerifierResult(json.loads(out.read_text()), VerifierResult._token)


# ---------------------------------------------------------------- state derivation


@dataclass
class Derivation:
    state: str
    reasons: list[str] = field(default_factory=list)
    overlay: str | None = None
    usable: bool = True
    governance_decision: bool = False  # True only for an authenticated, authorized decision
    decisions: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def doc(self) -> dict:
        return {
            "state": self.overlay or self.state,
            "base_state": self.state,
            "overlay": self.overlay,
            "usable": self.usable,
            "governance_decision": self.governance_decision,
            "decisions": self.decisions,
            "warnings": self.warnings,
            "reasons": self.reasons,
        }


def _passed(record) -> bool:
    return (
        isinstance(record, dict)
        and record.get("schema") == "dev-platform.verification/v1"
        and bool(record.get("checks"))
        and all(c.get("status") == "passed" for c in record["checks"])
        and (record.get("acceptance") or {}).get("state") not in (None, "failed")
    )


def _digest(record) -> str | None:
    return ((record or {}).get("subject") or {}).get("archive_sha256")


def derive(facts: dict) -> Derivation:
    """facts: planning {ready}, archive_sha256, ci_verification, independent_verification (records),
    published {immutable}, verifier (VerifierResult|None), notices [{kind, digest}]."""
    reasons: list[str] = []
    state = "planned"
    digest = facts.get("archive_sha256")
    if (facts.get("planning") or {}).get("ready") is True:
        state = "implementation-complete"
    ci = facts.get("ci_verification")
    if state == "implementation-complete" and digest and _passed(ci) and _digest(ci) == digest:
        state = "candidate-built"
    elif digest and not (_passed(ci) and _digest(ci) == digest):
        reasons.append("no passing CI verification bound to the archive digest")
    ind = facts.get("independent_verification")
    if state == "candidate-built":
        if _passed(ind) and _digest(ind) == digest and ind is not ci:
            state = "independently-verified"
        else:
            reasons.append("no passing independent verification bound to the archive digest")
    if state == "independently-verified":
        acc = (ind.get("acceptance") or {}).get("state")
        v = facts.get("verifier")
        if acc == "pre-release":
            reasons.append("pre-release: verified artifacts only")
        elif not (facts.get("published") or {}).get("immutable"):
            reasons.append("release is not published as an immutable GitHub release")
        elif acc == "verified":
            if (ci.get("acceptance") or {}).get("state") == "verified":
                state = "released"
                reasons.append("verified and published as an immutable release (ADR 0024)")
            else:
                reasons.append("the CI and independent verification records disagree on the release state")
        else:
            state = "verified-unaccepted"
            if acc == "accepted" and not isinstance(v, VerifierResult):
                reasons.append(
                    "an `accepted` claim in a record is not authority; only a run of the pinned verifier is"
                )
            if isinstance(v, VerifierResult):
                vrec = v.record
                if _passed(vrec) and _digest(vrec) == digest and vrec["acceptance"]["state"] == "accepted":
                    state = "accepted"
                    reasons.append(
                        "accepted by the pinned verifier on an authenticated, authorized authorization"
                    )
                else:
                    reasons.append(
                        "; ".join((vrec.get("acceptance") or {}).get("reasons", [])) or "not accepted"
                    )
            else:
                reasons.append("no authenticated authorization has been evaluated by the pinned verifier")
    d = Derivation(state, reasons)
    # Unauthenticated notices (any `kind`, even one that says "revoked") are warnings: they suspend use
    # conservatively but are not governance decisions and never change the authorization outcome.
    for n in facts.get("notices") or []:
        if n.get("digest") == digest:
            d.warnings.append(f"{n.get('kind', 'warning')}: {n.get('reference', '')}".strip())
    if d.warnings:
        d.overlay = "suspended"
    v = facts.get("verifier")
    if isinstance(v, VerifierResult):
        ev = [
            e
            for e in (v.record.get("acceptance") or {}).get("authorization_evidence", [])
            if e.get("status") == "authentic"
        ]
        replaced = {sid for e in ev for sid in e.get("supersedes", [])}
        live = sorted((e for e in ev if e.get("id") not in replaced), key=lambda e: e.get("decided_at", ""))
        d.decisions = [
            {
                "id": e.get("id"),
                "decision": e.get("decision"),
                "approver": e.get("approver"),
                "supersedes": e.get("supersedes", []),
            }
            for e in ev
        ]
        if live and live[-1].get("decision") == "revoked" and _digest(v.record) == digest:
            d.overlay = "revoked"
            d.governance_decision = True
    d.usable = d.overlay is None
    return d


def advance(current: str, target: str, facts: dict) -> Derivation:
    """Validate a requested transition. Refused unless the derived state already supports it."""
    if target not in STATES:
        raise ConfigError([f"unknown state {target!r}"])
    if target == "accepted":
        raise ConfigError(["`accepted` cannot be set; it is observed from the pinned verifier's result only"])
    if current not in STATES:
        raise ConfigError([f"unknown state {current!r}"])
    if target not in EDGES[current]:
        raise ConfigError([f"transition {current} -> {target} is not allowed"])
    d = derive(facts)
    # the end states are alternatives (trust/v2 `released`; trust/v1 `verified-unaccepted`, `accepted`)
    ends = {"released": {"released"}, "verified-unaccepted": {"verified-unaccepted", "accepted"}}
    if (target in ends and d.state not in ends[target]) or STATES.index(d.state) < STATES.index(target):
        raise ConfigError(
            [f"cannot advance to {target}: derived state is {d.state} ({'; '.join(d.reasons)})"]
        )
    return d


# ---------------------------------------------------------------- versioning


def parse_version(v: str) -> tuple[int, int, int, tuple[str, int] | None]:
    m = SEMVER.match(v)
    if not m:
        raise ConfigError([f"{v!r} is not MAJOR.MINOR.PATCH[-id.N]"])
    pre = (m.group(4), int(m.group(5))) if m.group(4) else None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), pre


def _precedence(v: str):
    a, b, c, pre = parse_version(v)
    return (a, b, c, 1, 0, 0) if pre is None else (a, b, c, 0, pre[0], pre[1])


def classify_bump(prev: str, new: str) -> str:
    p, n = parse_version(prev), parse_version(new)
    if p[3] is not None:
        raise ConfigError([f"previous version {prev} must be a stable release"])
    if n[0] != p[0]:
        return "major"
    return "minor" if n[1] != p[1] else "patch"


def required_level(kinds: list[str], policy: dict) -> str:
    vp = policy["versioning"]
    by_kind = {k: lvl for lvl, ks in vp["levels"].items() for k in ks}
    unknown = sorted(set(kinds) - set(by_kind))
    if unknown:
        raise ConfigError(
            [f"unknown change kinds {unknown} (fail closed; add to planning/release-policy.json)"]
        )
    order = ["patch", "minor", "major"]
    lvl = max((order.index(by_kind[k]) for k in kinds), default=0)
    level = order[lvl]
    if level == "major" and vp["phase"] == "0.x":
        level = "minor"  # 0.x: incompatible changes ship as a minor bump and must be declared
    return level


def check_version(
    prev: str, new: str, kinds: list[str], policy: dict, *, criteria_met: list[str] | None = None
) -> list[str]:
    """Problems with releasing `new` after stable `prev` given the declared change kinds ([] = ok)."""
    vp = policy["versioning"]
    problems: list[str] = []
    n = parse_version(new)
    if n[3] and n[3][0] not in vp["prerelease_identifiers"]:
        problems.append(f"pre-release identifier {n[3][0]!r} not in {vp['prerelease_identifiers']}")
    if _precedence(new) <= _precedence(prev):
        problems.append(f"{new} does not follow {prev}")
        return problems
    order = ["patch", "minor", "major"]
    need, have = required_level(kinds, policy), classify_bump(prev, new)
    if order.index(have) < order.index(need):
        problems.append(
            f"changes {sorted(set(kinds))} require at least a {need} bump; {prev} -> {new} is {have}"
        )
    if n[0] >= 1 and parse_version(prev)[0] == 0:
        missing = sorted(set(vp["one_zero_criteria"]) - set(criteria_met or []))
        if missing:
            problems.append(f"1.0.0 criteria not met: {missing}")
    return problems


def supported_lines(versions: list[str], policy: dict) -> list[str]:
    """`latest-minor`: only the newest MAJOR.MINOR line (stable releases) receives patches."""
    stable = [v for v in versions if parse_version(v)[3] is None]
    if not stable:
        return []
    top = max(stable, key=_precedence)
    return [f"{parse_version(top)[0]}.{parse_version(top)[1]}"]


def patch_plan(affected: list[str], existing: list[str], policy: dict) -> list[dict]:
    """For an advisory affecting `affected` versions: a proposed security patch per supported line; other
    affected lines get no patch (upgrade instead). Proposals are candidates to build, never releases."""
    lines = set(supported_lines(existing, policy))
    out = []
    for line in sorted({f"{parse_version(v)[0]}.{parse_version(v)[1]}" for v in affected}):
        if line not in lines:
            out.append({"line": line, "action": "no-patch", "reason": "line not supported; upgrade"})
            continue
        top = max(
            (
                v
                for v in existing
                if parse_version(v)[3] is None and f"{parse_version(v)[0]}.{parse_version(v)[1]}" == line
            ),
            key=_precedence,
        )
        a, b, c, _ = parse_version(top)
        out.append({"line": line, "action": "patch", "version": f"{a}.{b}.{c + 1}", "kind": "security-fix"})
    return out


def _vparts(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v.split("+")[0].split("-")[0])[:3])


def diff_manifests(old: dict, new: dict) -> list[str]:
    """Change kinds implied by two toolchain manifests. Any pin change requires a new release (ADR 0010)."""
    kinds: set[str] = set()
    if old.get("schema") != new.get("schema"):
        kinds.add("breaking-manifest")
    op, np_ = old.get("profiles", {}), new.get("profiles", {})
    kinds |= {"profile-added" for _ in set(np_) - set(op)} | {"profile-removed" for _ in set(op) - set(np_)}
    for name in set(op) & set(np_):
        ot, nt = op[name].get("tools", {}), np_[name].get("tools", {})
        kinds |= {"tool-added" for _ in set(nt) - set(ot)} | {"tool-removed" for _ in set(ot) - set(nt)}
        for tool in set(ot) & set(nt):
            if ot[tool] == nt[tool]:
                continue
            a, b = _vparts(ot[tool].get("version", "0")), _vparts(nt[tool].get("version", "0"))
            if a[:1] != b[:1]:
                kinds.add("toolchain-major")
            elif a[:2] != b[:2]:
                kinds.add("toolchain-minor")
            else:
                kinds.add("toolchain-patch")
    return sorted(kinds)


def diff_schemas(old_dir: Path, new_dir: Path) -> list[str]:
    old = {p.name: json.loads(p.read_text()) for p in Path(old_dir).glob("*.json")}
    new = {p.name: json.loads(p.read_text()) for p in Path(new_dir).glob("*.json")}
    kinds = {"schema-removed" for _ in set(old) - set(new)} | {"schema-added" for _ in set(new) - set(old)}
    for name in set(old) & set(new):
        if old[name].get("$id") != new[name].get("$id"):
            kinds.add("breaking-evidence-schema")
    return sorted(kinds)
