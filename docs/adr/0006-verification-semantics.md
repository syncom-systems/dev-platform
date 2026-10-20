# ADR 0006: Verification semantics: obligation is independent of cost

Status: Ratified

Full model in [verification-model.md](../verification-model.md). Decisions:

1. `cost` (fast/slow) and `obligation` (always/change/periodic) are independent. Selection never
   reads cost.
2. A mandatory (`always`/`change`) check must be admissible at `pre-merge`; the validator rejects a
   configuration that defers one to `full` only.
3. Unknown or unmapped change impact selects every owed check (fail closed).
4. Evidence is a state machine (`pending | verified | failed | invalidated`). `verified` comes only
   from a pass or from carrying `verified` across a change that provably does not reach the check.
5. A check has exactly one definition (unique id); stages are a property of that definition.
6. Certification and release eligibility require a full-stage run in which every configured check
   passed, a known revision and a pinned platform. A `verified` state carried from a previous record
   never substitutes for passing in the certifying run, so a check not defined for `full` blocks
   certification. Self mode and overrides are never certifiable.

## Clarification (2026-10-20, owner-authorized)

Decision 6 previously read "all checks verified … and a non-override platform". The intent, consistent
with decision 4, is that the certifying run is itself the evidence: the engine had accepted a carried
`verified` state for a check that did not run at `full`, and self mode was never certifiable in code.
The wording now states that intent; no other semantics change. Development-stage carry and `pre-merge`
admission (decisions 2-4) are unchanged.
