"""Verification model: vocabulary and evidence state transitions.

Cost and obligation are independent axes. `cost` says how expensive a check is;
`obligation` says when it is owed. Nothing here derives one from the other.
"""

from __future__ import annotations

from enum import StrEnum


class Stage(StrEnum):
    EDIT = "edit"  # editor/agent diagnostics on the file just changed
    PRE_COMMIT = "pre-commit"  # staged change, before the commit exists
    PRE_MERGE = "pre-merge"  # admission of a change into the protected branch
    FULL = "full"  # asynchronous comprehensive validation of a revision


class Obligation(StrEnum):
    ALWAYS = "always"  # owed at every admission, regardless of the change
    CHANGE = "change"  # owed whenever the change can reach the check's inputs
    PERIODIC = "periodic"  # owed on a schedule; not coupled to repository inputs


class Cost(StrEnum):
    FAST = "fast"
    SLOW = "slow"


class Outcome(StrEnum):
    """What happened when a selected check was attempted."""

    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"  # tool missing or not attempted: not a pass
    NOT_RUN = "not_run"  # not selected in this run


class EvidenceState(StrEnum):
    PENDING = "pending"  # no result yet
    VERIFIED = "verified"  # passed at this revision, or carried with no affecting change
    FAILED = "failed"
    INVALIDATED = "invalidated"  # was verified; a change reaches it and it has not re-run


ADMISSION_STAGES = frozenset({Stage.PRE_MERGE, Stage.FULL})


def advance(prev: EvidenceState | None, *, impacted: bool, outcome: Outcome) -> EvidenceState:
    """The evidence state machine for one check across one run.

    Invariants (enforced by tests):
      * VERIFIED is only produced by a PASSED outcome, or by carrying VERIFIED
        when the change does not reach the check.
      * An impacted check that did not pass can never end up VERIFIED.
      * FAILED persists until the check passes; being unreached does not heal it.
    """
    if outcome is Outcome.PASSED:
        return EvidenceState.VERIFIED
    if outcome is Outcome.FAILED:
        return EvidenceState.FAILED
    # UNAVAILABLE or NOT_RUN: no new evidence.
    if prev is None:
        return EvidenceState.PENDING
    if prev is EvidenceState.FAILED:
        return EvidenceState.FAILED
    if impacted:
        if prev in (EvidenceState.VERIFIED, EvidenceState.INVALIDATED):
            return EvidenceState.INVALIDATED
        return EvidenceState.PENDING
    return prev
