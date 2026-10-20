# Deliverable 3 — Architectural decision register

> Status: **for owner decision; nothing here is decided.** Each entry gives alternatives, evidence (citations in the
> [reconciliation](reconciliation.md)), consequences, compatibility, a recommendation and the precise decision asked
> for. Entries marked **⚠ ratified** would clarify or amend a ratified ADR and need explicit owner sign-off under
> `docs/adr/README.md`. RFC §15 question numbers are given as (Q#).

## Summary

| ID | Decision | Recommendation | Touches | Draft ADR |
|---|---|---|---|---|
| R-1 | Placement and authority of the assurance capability (Q1, Q9, Q12) | module inside Dev Platform; consumer evaluator stays authoritative when projected | — | A |
| R-2 | Native declaration format | defer; projection first, native TOML after equivalence | config/v1 later | A |
| R-3 | Projection contract and producer ownership (Q1, Q10) | `dev-platform.assurance-projection/v1`; MCP-RE owns its exporter | MCP-RE | A |
| R-4 | Core vocabulary, closure verdicts and argument subset (Q2) | four axes; `PASS/INCOMPLETE/FAILED/UNDECLARED`; scope per gate; explicit partial argument subset (ADR A §4a) | — | A |
| R-5 | Bind evidence carry to input identity (Q4) — (i) proposed in #148; (ii) open | (i) yes, refuse unbound carry; every carry states its boundary class; (ii) keep `declared` carry at admission until E4 | ⚠ ratified ADR 0006 §4 (clarification; (ii)=refuse would amend) | B |
| R-6 | Certification carry gap — **decided; fixed in #147** ([defect report](certification-carry-defect.md)) | certification requires a pass *in the certifying run* | ⚠ ratified ADR 0006 §6 (clarification) | B §5 |
| R-7 | ADR 0006 vs bounded merge selection (Q3) | keep ADR 0006; offer explicit, consumer-declared release-due obligations; reject size-conditional deferral | ⚠ ratified ADR 0006 §2 (amendment) | C |
| R-8 | Default for paths outside every provider read set | unmapped = unknown = owed; implicit ignore must become explicit | ⚠ ratified ADR 0006 §3 (scope statement) | B |
| R-9 | Claim review records and reviewer identity (Q6) | native: `authorization/v1` with a claim-review subject; projected: consumer's records | ADR 0013 record shape (Proposed part) | A |
| R-10 | Formal-methods boundary (Q5) | provers are checks or providers; nothing prover-specific in core | — | A |
| R-11 | Counterexample-control semantics | record `detects` + attribution level; registered vs exploratory | — | B |
| R-12 | Terminology collisions | "tool closure" vs "assurance closure"; "release verification" vs "release assurance" | ADR 0015 wording (no semantic change) | A |
| R-13 | Budget authority and enforcement split (Q7) | CLI: timeouts, refusal, reporting; runtime: hard caps | ADR 0007 (consistent) | D |
| R-14 | Planner authority and LLM gate (Q8) | deterministic baseline only; LLM after blinded evaluation | — | D |
| R-15 | Historical data preservation and consent — **time-sensitive** | authorize E0 ([package](owner-decision-package.md) §2) by ~2026-11-01; transcripts excluded, separate consent | none (data) | — |
| R-16 | Migration criterion for any MCP-RE gate (Q10) | equivalence + negative controls + consumer-owner approval; no replacement in scope now | MCP-RE | A |
| R-17 | Meaning of a full release run (Q11) | consumer-declared; fresh complete run; certification + release assurance + release verification + acceptance kept separate | — | C |
| R-18 | Duration/cost observations | separate `execution-observation` record; `result/v1` stays deterministic | — | D |
| R-19 | Documentation correction (self-mode certification) | correct `verification-model.md` and ADR 0006 §6 wording to match code | ⚠ ratified ADR 0006 §6 (wording) | — |

---

### R-1 Placement and authority of the assurance capability
- **Question.** Where does the generic evaluator live, and whose verdict is authoritative?
- **Alternatives.** (a) module in the Dev Platform package; (b) separate package/repository; (c) extract MCP-RE's
  tooling as the generic core.
- **Evidence.** Dev Platform has no plugin runtime by ratified decision (ADR 0004); its verification core is ~520
  lines of pure functions; MCP-RE's assurance tooling is consumer-coupled (paths, GitHub, prover names; reconciliation
  §4, §9); no second independent consumer of a separate package exists.
- **Consequences.** (a) ships through existing pinned releases, schemas and `test_schemas.py`; (b) adds a release
  line and trust chain with no demonstrated boundary; (c) imports security vocabulary and Apache-2.0 provenance
  obligations, and moves MCP-RE authority.
- **Compatibility.** (a) is additive (new command, new schema).
- **Recommendation.** (a). For a projected consumer, Dev Platform's evaluation is informational until R-16 is met;
  the consumer's own evaluator remains authoritative. CLI + JSON only (ADR 0007), usable without any agent.
- **Owner decision.** Approve (a) and the authority rule "projected consumer's verdict stays authoritative".

### R-2 Native declaration format
- **Question.** How does an ordinary consumer declare claims, units and premises?
- **Alternatives.** (a) new sections in `dev-platform.toml` (config/v1 → v2 or additive optional keys); (b) separate
  consumer file (e.g. `assurance.toml`) referenced from `dev-platform.toml`; (c) projection JSON only, hand-written or
  generated.
- **Evidence.** `config.py` rejects unknown keys (`config.py:288-290`); schema changes are versioned change kinds
  (`planning/release-policy.json`). MCP-RE deliberately separates claims from units to avoid duplicated authority
  (`_theorems.py:75-104`).
- **Consequences.** (a) couples assurance policy to check policy in one strict file; (b) keeps the separation MCP-RE
  found necessary; (c) is awkward for humans but lets the evaluator be validated first.
- **Recommendation.** Sequence: (c) for the first increment (projection evaluator validated on MCP-RE), then (b),
  compiled to the same projection. Do not design the TOML format before equivalence is shown.
- **Owner decision.** Approve deferring the native format; choose (a) or (b) at that time.

### R-3 Projection contract and producer ownership
- **Question.** How does Dev Platform read MCP-RE's assurance information without moving its authority?
- **Alternatives.** (a) parse MCP-RE TOML registries and records directly; (b) consume only the existing versioned
  closure record v1 / release-assurance v2; (c) a new versioned projection produced by an MCP-RE-owned exporter.
- **Evidence.** Only closure v1 and release-assurance v2 are versioned (reconciliation §8); they carry fingerprints and
  verdicts but no per-claim axis states, graph, causes or premises. `review --json` is unversioned. Registry keys are
  consumer-specific.
- **Consequences.** (a) couples Dev Platform to MCP-RE internals and makes Dev Platform a second interpreter of MCP-RE
  policy; (b) allows identity comparison only — no recomputation, no negative controls; (c) requires a change in
  MCP-RE (separately authorized there) and a schema Dev Platform owns.
- **Compatibility.** (c) is additive to both; MCP-RE keeps all gates.
- **Recommendation.** (c), schema owned by Dev Platform, exporter owned by MCP-RE, `extensions` for consumer data. Use
  (b) immediately as an identity cross-check in the evaluation (no MCP-RE change needed).
- **Owner decision.** Approve (c) and decide whether to request the MCP-RE exporter (an MCP-RE-side authorization).

### R-4 Core vocabulary and closure verdicts
- **Question.** Which states are core and how is closure computed?
- **Alternatives.** (a) four axes and four closure values as in proposal §3.3; (b) reuse MCP-RE's PASS/FAIL closure;
  (c) a single green/red status.
- **Evidence.** RFC §7.1, §7.5; MCP-RE folds incomplete support into `FAIL` at closure level (reconciliation §6.3) but
  distinguishes `INCOMPLETE` at aggregate and root levels; Dev Platform's evidence states answer a narrower question.
- **Argument semantics (rev. 2).** Conjunction is MCP-RE's model, not the universal semantics of assurance
  arguments. Draft ADR A §4a supports an explicit subset — conjunctive support, prerequisite claims, premises that
  must be accepted, review bound to the argument digest, and an explicit `incomplete`/`unknown` argument marker — and
  reports anything else, including `any-of`, as `unsupported-form`. Non-vacuity holds for every implemented form;
  evidence kinds stay distinct. **Rev. 3:** the rev. 2 rule "counterevidence in any alternative makes the claim
  `FAILED`" is withdrawn; alternative semantics are reserved for a later decision (ADR A §4a).
- **Recommendation.** (a); closure scope (`roots` or `all-active`) is consumer policy per gate; `UNDECLARED` for empty
  roots/active set; `FAILED` only for current counterevidence; the argument subset approved as explicitly partial.
- **Owner decision.** Approve the vocabulary in draft ADR A item 4 and the subset in §4a; answer the open questions in
  the [package](owner-decision-package.md) §3.

### R-5 Bind evidence carry to input identity ⚠ ratified (ADR 0006 §4, clarification)
- **Question.** May `verified` be carried from a record whose identity is not checked?
- **Alternatives.** (a) keep current behaviour; (b) bind carry to the identity components in proposal §4.1 and refuse
  otherwise; (c) remove `--previous`.
- **Evidence.** `engine.py:113` reads only `{id, state}`; nothing compares revision, configuration, check definition,
  environment or platform; no workflow uses it (reconciliation §3.3). ADR 0006 §4 says carry is allowed only across a
  change that "provably does not reach the check" — which an unbound record cannot prove.
- **Consequences.** (b) makes development-loop preservation sound and measurable; (a) leaves preservation unusable for
  a planner; (c) loses the only preservation mechanism.
- **Compatibility.** Behaviour change for callers passing a mismatched `--previous`: carry becomes `stale(…)`/`unknown`.
  `result/v1` gains optional fields (additive) — or v2 if the owner prefers strictness. 0.x minor bump.
- **Dependency completeness (rev. 2).** Matching digests are sufficient only over a complete or conservatively
  bounded read set. Globs and declared paths are not (MCP-RE F-1/F-2 show the failure). Draft ADR B §2–§4 therefore
  records a boundary class (`complete / declared / unknown`) with every identity: `complete` only from a measuring or
  over-approximating mechanism (none exists today); `declared` carry is labelled and never certifies; `unknown` is
  reported as uncertainty and carries nothing. Selection of owed checks is unchanged by carry (ADR B §4, rev. 3).
- **Recommendation.** (b), presented as a *clarification* of what "provably" means in ADR 0006 §4. (ii): keep
  `declared` carry at admission — no weaker than today's glob selection — until E4 measures glob under-approximation.
- **Owner decision.** (i) approve (b) and confirm it is a clarification; (ii) keep or refuse `declared` carry at
  admission (refusing would be a stricter amendment of §4).
- **Status (rev. 3, 2026-10-20).** (i): implementation **proposed** in PR #148 (open, not merged): identity over
  definition, platform, environment, global and declared inputs; boundary `declared`/`unknown` (`complete` produced by
  nothing); `current`/`stale`/`unknown` applicability; no carry at `full`; admission unchanged; inputs snapshotted
  before and after execution; a previous identity whose digest or boundary is inconsistent is `unknown`. Limitations it states: records are unauthenticated; declared boundaries can
  under-approximate; no provider identity; an edit undone within a run is not detected. Carried state from it is
  labelled history-backed reuse, not authoritative evidence for a future evaluator. (ii): **open**. ADR 0006 §4
  wording: **open** (proposed text in PR #148).

### R-6 Certification carry gap ⚠ ratified (ADR 0006 §6, clarification)
- **Question.** Can certification rely on state carried from a previous record?
- **Evidence.** A `change` check need not include `full` (`config.py:314-322`); at `full` it is `NOT_RUN` unimpacted
  (`engine.py:129-130`) and keeps carried state; certification needs every check `verified` (`engine.py:206`). By
  reading; not executed. No test covers it. NGA and Dev Platform's own checks all include `full`, so no known consumer
  is affected.
- **Alternatives.** (a) certification blocker for any check not `passed` in the certifying run; (b) config invariant:
  `always`/`change` checks must include `full`; (c) `full` runs every check regardless of `stages`.
- **Consequences.** (a) closes the gap with no configuration change; a configuration with pre-merge-only checks can no
  longer certify (today it can only via `--previous`). (b) rejects such configurations at load (breaking). (c) changes
  stage semantics.
- **Recommendation.** (a), plus a `doctor` warning for checks lacking `full`. Treated as a current-implementation
  defect with precedence over the evaluator and planner; full analysis, reproduction plan and authorization request in
  the [defect report](certification-carry-defect.md). Not experimentally confirmed.
- **Owner decision.** Approve (a) as a clarification of ADR 0006 §6 ("every check verified" = passed in this run).
- **Status (rev. 3, 2026-10-20).** **Decided and implemented**: reproduced, then fixed in PR #147, merged as `e73fd55`
  (outcome-based certification blocker, `doctor` warning, independent re-check in release assembly, ADR 0006 §6
  clarification with a dated note, R-19 wording). The evidence above is kept as examined at `6c0e7b4`.

### R-7 ADR 0006 versus bounded merge selection ⚠ ratified (ADR 0006 §2, amendment if B1)
- **Question.** Should Dev Platform admit consumer policies where a mandatory obligation is satisfied later than merge?
- **Evidence (reconciliation §6.1).** MCP-RE is not a Dev Platform consumer. As wired, MCP-RE's cap switches to a
  *full* pre-merge run (more work); the real differences are the mutation-lane deferral to the weekly run, the empty
  scope for unmapped paths (R-8), and that its verification jobs are not required checks.
- **Alternatives.**
  - **A — no change.** Keep ADR 0006 §2. A consumer wanting slower cadence must use `periodic`, which is uncoupled to
    inputs (so a change-triggered deferral is not expressible).
  - **B1 — explicit release-due obligations.** A consumer may declare, per check, `due = "release"`: the check stays
    change-triggered, is reported as *owed, not due* at pre-merge, is recorded as an outstanding obligation bound to the
    revision, and blocks certification and release until discharged by a run at or after that revision. Declared in
    policy ahead of time; never decided by selection, planner or budget.
  - **B2 — conditional deferral.** Allow deferral when a runtime predicate holds (scope size, cost). This is the
    documented `select-units` semantics.
  - **C — adopt MCP-RE semantics** generally.
- **Consequences.** A: no change, no expressiveness for slow lanes; B1: expresses MCP-RE's mutation-lane policy
  honestly and makes the debt visible and blocking at release; B2: makes admission depend on cost, contradicting ADR
  0006 §1, and a large change would owe *less* at merge than a small one; C: weakens existing guarantees.
- **Compatibility.** B1 is additive (new optional key; default `due = "merge"` = today). It amends §2's rule from "must
  be admissible at pre-merge" to "must be admissible at pre-merge unless declared release-due; release-due obligations
  must include `full` and block certification".
- **Recommendation.** A now; B1 drafted as ADR C for a considered decision; reject B2 and C. A cap that triggers a
  *larger* run (MCP-RE's wiring) needs no exception — it is already compatible.
- **Owner decision.** Choose A or B1. If B1, confirm that deferred obligations must be persisted and must block
  certification.

### R-8 Default for paths outside every provider read set ⚠ ratified (ADR 0006 §3, scope statement)
- **Question.** When impact is computed by a provider (fingerprints), what is a path no fingerprint reads?
- **Evidence.** MCP-RE: such a path moves no fingerprint → empty scope → nothing measured, negative controls skipped
  (`verification.yml:946-950`). Dev Platform: unmapped path → every owed check (`impact.py:81-84`). MCP-RE partially
  compensates with the trigger-coverage gate (workflow filters ⊇ read set), which proves the opposite direction only.
- **Alternatives.** (a) unmapped = unknown = owed (Dev Platform rule) for provider impact too; (b) provider read set
  is authoritative (MCP-RE rule); (c) (b) only when the consumer declares an explicit ignore list and the provider
  proves its read set covers every tracked path not ignored.
- **Recommendation.** (c), where "proves" means a `complete` boundary class (draft ADR B §2), which no provider has
  today; (c) therefore reduces to (a). Record MCP-RE's present behaviour as an
  evaluation negative control (F-3).
- **Owner decision.** Approve (c) as the generic rule; whether MCP-RE changes its own behaviour is the MCP-RE owner's
  decision (F-3).

### R-9 Claim review records and reviewer identity
- **Question.** What makes a claim review admissible?
- **Evidence.** MCP-RE binds reviews to claim/semantic digests but accepts any non-empty reviewer string and relies on
  repository write access (`_review.py:192-193`, `_approvals.py`). Dev Platform `authorization/v1` has identity
  assertions, roles, explicit supersession and rejects git authorship as identity (ADR 0013, `records.py:84-121`), but
  its subjects are releases and changes only (`records.py:92`).
- **Alternatives.** (a) native reviews as `authorization/v1` with a new subject kind `claim-review` bound to the claim
  fingerprint (and semantic digest); (b) a new review schema; (c) MCP-RE-style free-string records.
- **Recommendation.** (a) for native consumers (ADR 0013 record shape is the Proposed part; ADR 0016 trust boundary
  unchanged); projected consumers keep their own records and project only state. No tool writes a review on a
  reviewer's behalf; agents cannot create one (RFC §9).
- **Owner decision.** Approve (a) and the rule that review identity strength is reported, not assumed.

### R-10 Formal-methods boundary
- **Recommendation.** Provers are checks (usually `exec`) or projection providers; prover identity enters through the
  toolchain profile or an opaque `provider` component; "failed prerequisite blocks consumers" replaces MCP-RE's
  prover-named `BLOCKED` (`_graph.py:232`). Model-to-implementation correspondence is a claim with its own support (RFC
  §7.4), never inferred.
- **Owner decision.** Confirm no prover dependency in the core.

### R-11 Counterexample-control semantics
- **Evidence.** MCP-RE attributes kills by test identity, not assertion; baseline green comes from the test record at the
  same fingerprint; #1036 fixed false kills (reconciliation §4.4).
- **Recommendation.** A control's evidence records `detects: {unit, defect_id}`, the attribution level
  (`test-identity | assertion`) and requires a current unweakened pass of the same control. Registered controls are
  ordinary evidence; unregistered ones are exploratory (ADR D) and never evidence.
- **Owner decision.** Approve the attribution field and the registered/exploratory split.

### R-12 Terminology collisions
- **Recommendation.** In new text: "tool closure" for ADR 0015's runtime closure, "assurance closure" for L3; "release
  verification" (artifact provenance) vs "release assurance" (claims at release). No renaming of existing records or
  schemas.
- **Owner decision.** Approve the naming rule.

### R-13 Budget authority and enforcement split
- **Evidence.** No check timeout exists (`engine.py:31`); MCP-RE limits only by CI `timeout-minutes`; ADR 0007 makes
  agent instructions non-enforcing; RFC §9 notes unrestricted shell defeats a CLI budget.
- **Recommendation.** Draft ADR D: CLI enforces per-check timeouts, runs only declared checks, refuses exploratory
  actions without an authorization record, and appends a session ledger (counts, wall-clock); hard caps on tokens,
  shell and cumulative compute are runtime/execution-environment controls, documented as such, never claimed by the CLI.
- **Owner decision.** Approve the split and whether exploratory authorization reuses `authorization/v1` (new subject
  kind `exploration`) or stays out of scope until a runtime integration exists.

### R-14 Planner authority and LLM gate
- **Recommendation.** Deterministic `c/p` ordering + gap actions + abstention (proposal §7.2); advisory output only;
  an LLM ranker only after the evaluation shows a net (T, K) gain over the deterministic planner with no R loss, on
  held-out changes.
- **Owner decision.** Approve deterministic-first and the evaluation gate.

### R-15 Historical data preservation and consent
- **Evidence.** MCP-RE job logs are the only record of selection decisions, outcomes, probe kills and timings; 90-day
  retention; earliest expire ~2026-11-09, `select-units`-era from ~2026-12-24; artifacts 14 days. Agent cost data exist
  only in local agent transcripts (41 sessions, 2026-09-19..10-20), which are private.
- **Alternatives.** (a) authorize a read-only archival download of `verification.yml` and `mutation-probe.yml` job
  logs to private storage now; (b) wait for the evaluation authorization and accept the loss; (c) archive only the
  `select-units` era.
- **Recommendation.** (a), as a separately authorized data-collection action (no execution of any verification), and a
  separate explicit decision on whether agent transcripts may be mined, by whom, and what aggregates may be published.
- **Owner decision.** Authorize or decline (a) as specified in the [package](owner-decision-package.md) §2 (scope,
  integrity, caps, storage, non-publication, success criteria); transcripts are not covered and need separate consent.

### R-16 Migration criterion
- **Recommendation.** No MCP-RE gate is replaced in this program. Any future replacement requires: verdict equivalence
  on all committed closure targets and perturbation controls (evaluation §5); a shadow period with zero disagreements
  on real changes; license/NOTICE provenance for any copied code; explicit MCP-RE owner approval.
- **Owner decision.** Approve the criterion.

### R-17 Meaning of a full release run
- **Recommendation.** Consumer-declared release policy names: the checks owed at `full` (all, fresh, in one run); the
  assurance-closure scope at release (`roots` or `all-active`); required review currency; then release verification and
  owner acceptance as today. Intermediate evidence never substitutes (R-6). Dev Platform certification and consumer
  release assurance are separate records linked by digest (ADR 0013 pattern).
- **Owner decision.** Approve the composition rule.

### R-18 Duration and cost observations
- **Evidence.** `result/v1` is deterministic and excludes timestamps/host data (`docs/architecture.md:31`,
  `tests/test_engine.py:147`); no consumer records machine-readable durations (dataset inventory).
- **Recommendation.** A separate `execution-observation` record (wall-clock, exit, environment digest, runner) written
  alongside the result, never read by admission or certification.
- **Owner decision.** Approve a separate record. Part of draft ADR D (execution observations and budgets); not a
  condition of draft ADR B.

### R-19 Documentation correction
- **Evidence.** `docs/verification-model.md:51-52` and ADR 0006 §6 imply `self` mode certifies; `resolve.py:39-42` and
  `tests/test_engine.py:106` say it does not.
- **Recommendation.** Correct the wording to match the code (no semantic change). Not done in this branch because it
  edits ratified text.
- **Owner decision.** Authorize the wording fix.

---

## Findings for the MCP-RE owner (consumer-owned; not Dev Platform decisions)

These are reported, not acted on. Each is an evaluation input (negative control or replay case).

| ID | Finding | Evidence | Status |
|---|---|---|---|
| F-1 | Python/TypeScript test bodies are not fingerprinted; a test can be hollowed without moving any fingerprint | `_fingerprint.py:429-442`; `sdk/python/tests/**` in no unit `paths` | Interpretation, by reading |
| F-2 | V0 Rust units' dependency closure is declared (18 edges/308 units), not measured | `test_measured_inputs.py:115-120` | IMPLEMENTED as designed |
| F-3 | An empty scope (path outside every read set) measures nothing and skips negative controls | `verification.yml:946-950` | WIRED |
| F-4 | `select-units` says deferred work goes to weekly/release; `verification.yml` runs it all before merge; `mutation-probe.yml` really defers; no deferred obligation is recorded | `select-units:142-169`; `verification.yml:954-961`; `mutation-probe.yml:131-141` | WIRED |
| F-5 | Verification and mutation-probe jobs are not required status checks; in-repo docs disagree | live ruleset 2026-10-20; `CHANGELOG.md:550-553` vs `docs/dev/ci-runner-migration-analysis.md:35` | live setting |
| F-6 | `release-assurance` requires root completeness, not full assurance closure | `release-assurance:128-154` | IMPLEMENTED |
| F-7 | Reviewer and approver identity are unauthenticated strings; ledger "signatures" are content hashes | `_review.py:192-193`; `_approvals.py:66-87` | IMPLEMENTED |
| F-8 | Open N1 obligations are reported as blocking roots but do not enter the verdict | `review:204-208`; `_review.py:417` | Interpretation |
| F-9 | Mutation kill attribution is by test identity, not assertion | `verify-mutations:157-172` | IMPLEMENTED |
| F-10 | Stale documentation: `verification/README.md:44-66`, parts of `tools/verification/README.md`, `theorems.toml:132`, `_manifest.py:356-360`, `pre-merge.yml` header | reconciliation §4 | DOCUMENTED |
