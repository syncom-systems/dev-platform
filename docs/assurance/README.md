# General assurance investigation: Phase 1–3 deliverables

> **Status:** Investigation output for owner review. **Not ratified, not an ADR, not implementation
> authorization.** Ratified ADRs (0004, 0005, 0006, 0007, 0013, 0015, …) and consumer-owned verification
> policy keep their authority. Nothing here changes code, CI, gates, proofs, reviews or release procedure.
>
> **Governing input:** [general-assurance-and-incremental-verification-rfc.md](../general-assurance-and-incremental-verification-rfc.md)
> (merged in PR #145).
>
> **Revisions examined (all citations refer to these):**
> - Dev Platform `syncom-systems/dev-platform` @ `6c0e7b4453e5b095f7a97c712a2cdb63b19acc1b` (main after #145;
>   executable code identical to the RFC snapshot `e548c6a8`).
> - MCP-RE `syncom-systems/mcp-re` @ `8262c5faad4c766513e473da90be135675a0c347` (origin/main, v0.18.1 records;
>   identical to the RFC snapshot). Read from a `git archive` of that commit; nothing in it was executed.
> - Live GitHub settings read on 2026-10-20 (GET only): repository rulesets of mcp-re, dev-platform, nga; Actions
>   run metadata and logs.
>
> **Method:** read source, tests, schemas, policy registries, workflows and committed records. No tests, builds,
> proofs, mutation, fingerprinting, benchmarking or other verification were run. Citations are `path:line` at the
> revisions above. Links into MCP-RE use the base
> `https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/`.

## Documents

| # | Document | Answers |
|---|---|---|
| 1 | [Architecture reconciliation](reconciliation.md) | What each repository actually implements, concept by concept; overlaps, gaps, conflicts, corrections to the RFC |
| 2 | [Refined architecture proposal](architecture-proposal.md) | The minimal generic model, authority boundaries, evidence semantics, the read-only projection, worked examples |
| 3 | [Decision register](decision-register.md) | Each open decision: alternatives, evidence, consequences, compatibility, recommendation, exact owner decision |
| 4 | Draft ADRs: [A assurance model and projection](drafts/draft-adr-a-assurance-model-and-projection.md), [B evidence identity and applicability](drafts/draft-adr-b-evidence-identity-and-applicability.md), [C obligation due-gates and admission](drafts/draft-adr-c-obligation-due-gates.md), [D planner and verification budgets](drafts/draft-adr-d-planner-and-budgets.md) | Decision-ready text; unnumbered so they cannot be mistaken for index entries |
| 5 | [Reference evaluation plan](evaluation-plan.md) | Baselines, datasets, metrics, equivalence / correction / specification controls, acceptance criteria, a bounded plan for separate authorization |
| 6 | [Certification carry defect report](certification-carry-defect.md) | Candidate defect in the current engine (by inspection, not reproduced): control flow, reproduction plan, regression test, fixes, authorization |
| 7 | [Owner decision package](owner-decision-package.md) | Decisions by readiness; the R-15 / E0 archival authorization proposal; recommended sequence |

## Revision 2 (owner review)

Focused corrections after the owner review; the examined source revisions above are unchanged (`dev-platform`
`6c0e7b4`, `mcp-re` `8262c5fa`; branch head before rev. 2 `4c9c5d9`). Changes: dependency-boundary classes and
gate-specific carry rules (draft ADR B, proposal §4.1/§7.1); explicit argument subset (draft ADR A §4a, proposal
§3); equivalence vs correction controls (evaluation §5–§6); planner behaviour on sparse/correlated/absent data
(proposal §7.2, draft ADR D); the standalone defect report; the decision package with the E0 proposal. ADR 0006
admission semantics are retained as the baseline; release-due obligations remain only in draft ADR C.

## Labels used throughout

- **IMPLEMENTED** — executable code with a test that exercises it (both cited).
- **WIRED** — behaviour that exists only in CI workflow YAML or repository settings, not in tested code.
- **DOCUMENTED-ONLY** — stated in a document; no corresponding code found (search terms given).
- **ABSENT** — searched for and not found.
- **Interpretation** — reasoning from code that was not confirmed by execution. Every such statement is marked.
- **Recommendation** — this investigation's proposal; never a decision.

## Time-sensitive item

MCP-RE's Actions job logs are the only record of historical selection decisions, per-lane outcomes, per-probe
kills and timings. Log retention is 90 days: the oldest `verification.yml` logs expire from about **2026-11-09**, the
`select-units` era (from 2026-09-25) from about 2026-12-24. Archiving them is a data-collection action outside this
mandate; it is decision **R-15** in the [register](decision-register.md#r-15-historical-data-preservation-and-consent).
