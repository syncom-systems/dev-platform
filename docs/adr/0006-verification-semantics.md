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

## Clarification (2026-10-21, owner-authorized): selection-configuration changes

Decision 3 covers a change to the project's root `dev-platform.toml`: at every non-`full` stage it selects every
owed (non-periodic) check defined for the stage, ahead of `impact.global`, `impact.ignore` and check `inputs`,
because the changed file declares the rules that would otherwise select. It does not compare against the
previous configuration: deleting a check or weakening an obligation remains a configuration-governance concern.
It does not make declared inputs complete. Unknown change sets, `full`, admission, certification and carry are
unchanged.

## Clarification (2026-10-21, owner-authorized): change-set path coordinates

Decision 3's unknown impact also covers a change set that cannot be read in project coordinates: a git-derived set
for a project that is not at its git worktree root, and explicit `--changed` paths that are absolute or leave the
project. Patterns and explicit paths are project-relative. Nested projects therefore select every owed check; no
repository-to-project path translation is made. Selection, obligations, `full`, admission, certification and carry
are otherwise unchanged.
