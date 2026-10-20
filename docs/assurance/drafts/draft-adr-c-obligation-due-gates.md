# Draft ADR C: Obligation due-gates and admission

Status: **Draft for owner review — not an ADR, unnumbered, not ratified.** Option B1 below would **amend ratified
ADR 0006 §2**; option A changes nothing. The owner chooses; this draft does not. Register entries: R-7, R-17.
Evidence: [reconciliation](../reconciliation.md) §6.1, §7; design: [proposal](../architecture-proposal.md) §5.

## Context
ADR 0006 §2 requires every mandatory (`always`/`change`) check to be admissible at `pre-merge`. The RFC (§10) frames
MCP-RE's bounded merge selection as conflicting with it. Investigation shows the conflict is narrower than stated:
MCP-RE is not a Dev Platform consumer; as wired, its 20-unit cap triggers a *full* pre-merge run, which is compatible;
the real differences are (i) its mutation lane is deferred to the weekly complete run when over cap or
platform-touching, (ii) an unmapped path yields an empty scope (handled by draft ADR B §6), and (iii) its verification
jobs are not required status checks (consumer policy). No deferred obligation is recorded anywhere.

## Options

**A — No change (recommended now).** ADR 0006 §2 stands. Slow mandatory lanes run at pre-merge or are declared
`periodic` (uncoupled to inputs). A cap that *increases* work needs no exception.

**B1 — Explicit release-due obligations (drafted for decision).**
1. A check may declare `due = "release"` (default `due = "merge"`, which is today's rule). Only consumer policy sets it;
   selection, the planner and budgets never change it.
2. A release-due check keeps its obligation kind (`always`/`change`) and must include `full`.
3. At `pre-merge` it is selected as today but reported *owed, not due*; its non-pass does not block admission.
4. Each owed-not-discharged release-due obligation is recorded as an outstanding obligation bound to the revision in
   the result (and observable by later runs).
5. Certification (and therefore release eligibility) is blocked while any outstanding obligation for an ancestor
   revision is undischarged; discharge requires a pass at `full` at or after that revision (in practice: the certifying
   run, which runs everything — draft ADR B §5).
6. Unknown impact never empties the obligation set; it makes every owed check owed at its due gate.

**B2 — Conditional deferral by runtime predicate (scope size, cost).** Rejected: admission would depend on cost
(contradicting ADR 0006 §1), and larger changes would owe less at merge than small ones.

**C — Adopt MCP-RE semantics generally.** Rejected: weakens existing guarantees.

## Stages, after either option
| Gate | Owed | Blocks |
|---|---|---|
| development (`edit`, `pre-commit`) | nothing mandatory; planner-ordered feedback | nothing |
| merge (`pre-merge`) | all `due = merge` owed checks, in this run | admission |
| release (`full` + release policy) | every check, fresh, one run; consumer's assurance-closure scope; review currency; then release verification and owner acceptance as separate records | certification, release eligibility, acceptance |

## Consequences
- A: simplest; MCP-RE's mutation-lane policy remains inexpressible in Dev Platform terms.
- B1: makes deferred debt explicit, persistent and release-blocking; needs result-schema additions and a rule for
  finding ancestor obligations (the result chain or the evidence store).

## Compatibility
B1 is additive (new optional key, default preserves today's behaviour) but amends the wording of a ratified rule.
Consumer compatibility: unaffected unless a consumer opts in.

## Owner decisions required
R-7: choose A or B1 (and, if B1, confirm persistence and certification blocking). R-17: the release composition rule.
