# Draft ADR D: Verification planner and verification budgets

Status: **Draft for owner review — not an ADR, unnumbered, not ratified.** Consistent with ratified ADR 0006 and
ADR 0007; amends neither. Register entries: R-13, R-14, R-18.
Evidence: [reconciliation](../reconciliation.md) §3.4, §4.8; design: [proposal](../architecture-proposal.md) §7–§8;
evaluation: [plan](../evaluation-plan.md).

## Context
The initiating failure (RFC §2.1) was unbounded agent-initiated verification with no purpose, budget or stopping
condition. Neither repository has budgets: Dev Platform checks have no timeout (`engine.py:31`); MCP-RE limits only by
CI `timeout-minutes`. Neither uses cost to sequence work. A CLI cannot see model tokens or shell commands outside it.

## Decision (proposed)
### Planner
1. The planner is **advisory**. Inputs: the assurance report (draft ADR A), the selection result, execution
   observations. Output: an ordered recommendation or an abstention. Nothing it writes is evidence or policy.
2. **Deterministic baseline:** owed checks ordered by ascending expected cost per detected failure (`c/p`, proposal
   §7.2); gap actions ("author a test/contract/proof") for affected claims with no support; abstain without data.
3. Ordering changes when a failure is seen, never whether an owed check runs.
4. An LLM or Jev ranker may be added only for *permitted optional* candidates and only after the reference evaluation
   shows a net time/token gain over the deterministic planner with no loss on residual-risk metrics, on held-out
   changes; its output is `inferred` provenance; it must support abstention; scores are not calibrated probabilities.

### Execution observations
5. Wall-clock, exit, environment digest and runner are recorded in a separate `execution-observation` record, never in
   `result/v1` (which stays deterministic) and never read by admission or certification.

### Budgets and activity classes
6. Activities are **mandatory** (policy at a gate; budget never waives), **planned** (permitted at the checkpoint,
   within budget) or **exploratory** (stated hypothesis, expected information, resources, stopping condition, and an
   authorization when beyond allowance).
7. **CLI-enforced:** per-check `timeout` (new optional key; a timeout is `unavailable`, never a pass); only declared
   checks run through the CLI; an exploratory action run through the CLI is refused without a matching authorization
   record; a session ledger records counts, wall-clock and purpose.
8. **Not CLI-enforceable, stated as such:** model tokens, commands run outside the CLI, cumulative compute across tools.
   These need agent-runtime permission rules/hooks, a sandbox, CI-only execution of expensive lanes or reduced
   credentials. Agent instructions remain non-enforcing (ADR 0007).
9. **On exhaustion:** stop optional execution, keep outstanding obligations visible, report the blocker, request renewed
   authority. Never report success.

## Consequences
- A bounded, auditable loop for agents using the CLI; honest limits where the CLI cannot see.
- New config keys (`timeout`, optional `permitted` stages) and two new record kinds (observation, session ledger).

## Compatibility
Additive. Default without a `timeout` is today's behaviour. Whether exploratory authorization reuses `authorization/v1`
(subject kind `exploration`) is an owner choice (R-13).

## Owner decisions required
R-13 enforcement split and the authorization record; R-14 deterministic-first and the LLM gate; R-18 observation record.
