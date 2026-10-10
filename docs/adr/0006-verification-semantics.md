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
6. Certification and release eligibility require a full-stage run, all checks verified, a known
   revision and a non-override platform.
