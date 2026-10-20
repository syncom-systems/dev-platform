# Deliverable 5 — Reference evaluation plan

> Status: **plan only; nothing in it has been executed or is authorized.** Each experiment (§8) needs a separate,
> explicit authorization naming permitted actions, resource limits and how outputs may be used (RFC §17). Results of an
> authorized experiment are exploratory and never satisfy an assurance obligation.

## 1. Questions and hypotheses

| ID | Hypothesis | Primary metric | Must not worsen |
|---|---|---|---|
| H1 | Identity-bound evidence preservation (draft ADR B) never reports false freshness and labels every carry with its boundary class | false-fresh count (§4.4) = 0 | — |
| H2 | Preservation in the development loop reduces repeated verification | machine time and repeated runs per change | missed checks, false-fresh |
| H3 | Deterministic sequencing (`c/p` + gap actions) reduces time to first failure and diagnosis | time-to-first-failure, localization | missed checks, mandatory outcomes |
| H4 | The assurance-aware planner beats a simple deterministic baseline on the whole loop | T including planner overhead (replay); K only from the consented E3 shadow comparison in which arms B and C are both logged for the same changes — without it H4 claims T only | R metrics |
| H5 | Dev Platform's recomputation of MCP-RE assurance equals MCP-RE's own verdicts on EQ cases and is stricter on CORR cases (§5) | unexplained discrepancies = 0 | — |

## 2. Strategies compared (same obligations in every arm)

| Arm | Definition | Notes |
|---|---|---|
| **A — current** | MCP-RE as wired: `select-units` scope; empty scope → nothing; deferred → full pre-merge; mutation deferred → weekly (`verification.yml:925-961`, `mutation-probe.yml:120-141`). Dev Platform/NGA: glob selection (`impact.py`) | reconstructed from logs, not re-run |
| A′ — documented | `select-units` as documented: deferred → weekly/release | reported for contrast only; not a candidate |
| **B — simple deterministic** | Dev Platform glob impact over each MCP-RE unit's declared `paths` as `inputs`, unmapped → all, no consumer closure, fixed order | the "obvious" generic baseline |
| **C — assurance-aware** | fingerprint-based applicability with fail-closed unmapped paths (ADR B §6) + prerequisite consumer closure + `c/p` ordering + gap actions + budget stop for optional actions | the proposal |
| D — LLM ranker | ranking of permitted optional candidates over C | **excluded** from the first experiment; considered only if C shows gains and R-14 is approved |

A hand-curated "oracle" scope may be computed for diagnosis of information gaps; it is not an arm.

## 3. Datasets

| Source | Content | Availability | Use |
|---|---|---|---|
| MCP-RE `verification.yml` job logs | selected unit IDs, mode, per-lane PASS/FAIL with wall time, per-unit targets, per-probe killer and time | ~1,327 runs since 2026-08-11; **90-day retention** (earliest expire ~2026-11-09) | arms A/B/C replay, costs, outcomes |
| MCP-RE `mutation-probe.yml` logs | scoped probe runs, kills | 888 runs | probe attribution, deferral cost |
| MCP-RE committed records | 3 closure records; 133+85 review records; 72 claim corrections; registries incl. 538 probes with `expect_red` | permanent | H5 equivalence, controls |
| MCP-RE git history | 2,337 commits, 769 merged PRs; 360 commits touching `verification/policy` | permanent | recompute fingerprints at historical heads (needs authorization: executes MCP-RE's fingerprint tool) |
| Known-defect commits | 50378f89 (lane missing from fingerprint), d90505b1/f91aba47/f79494e3/e552cd78 (edge defects), 9e0ba722 (false kills), 31e17965 (green lane that could not measure), 58cc8302, 76ec8862 (escaped) | permanent | missed-defect and invalidation cases |
| Dev Platform qualification results | 90 `result/v1` records (0.4.0–0.10.0), no durations | permanent | baseline semantics only |
| NGA runs | 461 runs; `check` median 5.3 min, full gate median 36 min | 90-day | ordinary-tests consumer contrast |
| Agent transcripts (local, private) | 41 sessions 2026-09-19..10-20, 56,608 tool calls, per-message token usage, branch/PR attribution | only with owner consent (R-15) | K measurement; the RFC's 800–1,300 tool-call figure |

Sample characterization (60 recent MCP-RE runs, 2026-10-13..17): 27 scoped (18 with zero units), 14 over cap
(22–281 units), 19 platform-touching; 33/60 therefore ran every unit before merge; median executed host-lane job
145 min. Interpretation: under arm A the cap and platform rule, not selection precision, dominate merge cost.

## 4. Measurements

### 4.1 Time (T)
- `T_machine(change)` = Σ wall time of lanes/checks executed for the change (from logs/observations).
- `T_ttff(change)` = elapsed from verification start to the first failing action, for changes whose reference run fails.
- `T_elapsed(PR)` = first push → merge; reported, not optimized (confounded by review and queueing).
- Per-arm replay cost uses observed durations per (unit, lane) at the nearest commit; uncertainty reported as the
  interquartile range of observed durations; setup cost per job counted once per job.

### 4.2 Tokens and tool calls (K)
- From consented transcripts only: tokens per PR/issue (deduplicated by message id), tool calls per PR, and the share of
  both spent after verification commands until the next code edit (diagnosis proxy).
- Historical replay cannot reconstruct counterfactual agent behaviour (RFC §14); K effects are measured only in
  shadow mode (§8 E3) as *recommendation followed vs not*, never inferred from replay.

### 4.3 Diagnostic efficiency
- rank of the first failing action in the arm's order; `T_ttff`; localization = number of units implicated by the first
  failing action (smaller is better); actions after the first failure until the failing unit is identified.

### 4.4 Invalidation accuracy (correctness of preservation)
- **False-fresh**: an evidence item the arm treats as `current` whose reference shows (a) a different outcome on re-run,
  or (b) a moved read-set component. **Target 0; any occurrence rejects the arm.**
- Over-invalidation rate: items marked stale whose reference shows identical outcome and identical read set — a cost.
- Read-set conformance: for Dev Platform glob `inputs`, compare with what the check actually read (requires an
  instrumented run, E4) — measures how far globs under-approximate.

### 4.5 Missed defect-revealing checks
- Reference = a complete run (any attempt) on the **same commit**, else a known-defect label for that commit; otherwise
  the case is **unscorable** — excluded and counted, never scored against another revision. A unit-lane that fails in the reference but is not selected (or is preserved) by the arm is a **miss**.
- Report misses separately for mandatory and optional obligations. **Any mandatory miss rejects the arm** unless an
  explicit consumer policy (e.g. a declared release-due obligation, draft ADR C B1) covers it, in which case the
  deferral is recorded with the gate that catches it.

### 4.6 Residual uncertainty (R proxies)
At merge, per change: claims affected and not established; outstanding obligations by due gate; `unknown`
applicability items; open gap actions. At release: assurance-closure verdict and blockers. Never a probability.

### 4.7 Planner overhead
CPU time and, for D only, tokens of the planner itself; counted in T and K.

## 5. Nonvacuity, equivalence and correction controls

Each control has an expected verdict and a **class**:
- **EQ — equivalence.** Existing, accepted behaviour (MCP-RE's evaluator or Dev Platform's current engine). The new
  evaluator must agree exactly.
- **CORR — intentional correction.** Existing behaviour known or suspected to be unsound (cited finding). The new
  evaluator must produce the stricter expected verdict; the existing system is *expected to differ*, and the difference
  is recorded against the finding. If the existing system turns out to agree with the expected verdict, the finding is
  refuted and the case is reclassified EQ.
- **SPEC — new semantics.** No existing counterpart (argument forms, boundary classes, projection consistency). The
  new evaluator must match the draft ADR text; a mismatch is an evaluator defect or a specification ambiguity.

Controls marked *data* are perturbations of records/projections (no execution); *exec* need an authorized run.

| # | Control | Construction | Expected | Class (vs) |
|---|---|---|---|---|
| N1 | Empty claim set | projection with no active claims | closure `UNDECLARED`, never `PASS` | EQ (MCP-RE `bool(active)`) |
| N2 | Empty roots | roots `[]` | `UNDECLARED` | EQ (MCP-RE) |
| N3 | Claim with empty support | `units = []` | `no-support` → `INCOMPLETE` | EQ (MCP-RE) |
| N4 | Support only non-applicable/not-run | all lanes `NOT_REQUIRED` / `not_run` | `INCOMPLETE` | EQ (MCP-RE) |
| N5 | Unresolvable reference | support names a missing unit | load error or `INCOMPLETE`, never `PASS` | EQ (MCP-RE) |
| N6 | Stale review | change a claim statement digest | review `stale(claim)`; dependants not established | EQ (MCP-RE) |
| N7 | Changed proof model | move the provider/model component | `stale`; closure `INCOMPLETE` | EQ (MCP-RE) |
| N8 | Omitted result | drop one evidence item | `unknown`/`INCOMPLETE` | EQ (MCP-RE `REFUSE`) |
| N9 | Failed prerequisite | one supporting unit failed | closure `FAILED`, consumers blocked | EQ (MCP-RE) |
| N10 | Unknown impact | change set unknown / unmapped path | every owed check selected; never empty | EQ (Dev Platform `impact.py:81-84`); CORR (MCP-RE empty scope, F-3) |
| N11 | Python test hollowing | empty a pytest body named by a unit | not `current` (`stale` or `unknown`) | CORR (MCP-RE, F-1) |
| N12 | Undeclared V0 helper change | change a helper outside a V0 unit's `paths` that its tests call | not `current` unless a `complete` boundary covers it; `declared` carry must be labelled | CORR (MCP-RE, F-2) |
| N13 | False mutation attribution | replay 9e0ba722's pre-fix probes | not counted as detection under `assertion`; flagged under `test-identity` | EQ (MCP-RE after 9e0ba722); CORR (before) |
| N14 | Selector self-narrowing | change the selection/fingerprint code | everything owed; never narrower | EQ (Dev Platform fail-closed rule); MCP-RE behaviour not established — classify at E2 |
| N15 | Unbound carry | `--previous` from another revision/config | contributes nothing (`unknown`) | CORR (Dev Platform, R-5) |
| N16 | Certification carry | mandatory check without `full`, verified `--previous` | not certified | CORR (Dev Platform, [defect report](certification-carry-defect.md)) |
| N17 | Projection inconsistency | producer verdict `PASS` with a failing unit | `projection-inconsistent`, never `PASS` | SPEC |
| N18 | Toolchain bump | move environment component only | all evidence `stale(environment)`, reviews current | EQ (MCP-RE v0.18.0→v0.18.1) |
| N19 | Alternative with counterevidence | `any-of`: group 1 passes, group 2 has a current `failed` item | `unsupported-form` → `INCOMPLETE` until alternative semantics are decided (rev. 3) | SPEC (ADR A §4a, reserved) |
| N20 | Empty alternative | `any-of` with an empty group and a not-run group | `INCOMPLETE` (`unsupported-form`) | SPEC (reserved) |
| N21 | Incomplete argument | `argument = "incomplete"`, all support passing, review current | `INCOMPLETE(argument-incomplete)` | SPEC |
| N22 | Unaccepted premise | supporting unit premised on a premise with no current review | `premise-unaccepted`, not established | SPEC (MCP-RE parity to be checked: EQ if it matches) |
| N23 | Unsupported form | `any-of` given to an `all`-only evaluator | `unsupported-form` → `INCOMPLETE`, never reinterpreted | SPEC |
| N24 | Declared boundary at certification | identity equal, boundary `declared`, stage `full` | no carry; check must pass in the run | SPEC (ADR B §4–§5) |

N11, N12, N15, N16 *exec* (N15/N16 can be engine unit tests, defect report §5); the rest *data*. N1–N9, N17, N18 run
against the three committed MCP-RE closure targets.

### 5.1 Discrepancy procedure
Every disagreement between the new evaluator and the expected verdict or the existing system is recorded with: the
case, both verdicts, the class, and one of **evaluator defect**, **mapping loss** (information the projection cannot
carry, R-3), **existing-system defect** (CORR; cites the finding), or **specification ambiguity**. Each is explained and
owner-reviewed; none is resolved by changing the expected verdict to match whichever system is newer.

## 6. Acceptance and failure criteria
Accept the evaluator as a candidate only if all hold; reject the proposed optimization if any fails.
1. **Zero false-fresh** (§4.4) in every class, for any model proposed as authoritative.
2. **EQ:** exact agreement on every EQ case, or an owner-accepted mapping loss.
3. **CORR:** the stricter verdict on every CORR case, with the existing system's divergence recorded against its
   finding; exact equality with the existing system is *not* required and would indicate the correction is missing.
4. **SPEC:** agreement with the draft ADR text on every SPEC case.
5. No mandatory miss not covered by a declared consumer policy (§4.5); no mandatory gate outcome less strict than arm A.
6. For optimization claims (H2–H4): net `T_machine + planner overhead` lower than arm A on the held-out set with the
   uncertainty interval excluding zero gain; K claims only from shadow mode (E3).
7. Every discrepancy classified and reviewed (§5.1).
Improved test counts or raw coverage are not success criteria (RFC §14).

### 6.1 Evidence labels in the report
Every number is labelled as one of: **observed** (measured in logs or runs: costs, outcomes, durations), **estimated**
(replay of an arm over observed data: savings an arm *would* have had, with its assumptions), or **experimental**
(end-to-end result of an authorized shadow or live experiment). Replay never establishes counterfactual agent
behaviour: an arm that would have run fewer checks says nothing about what an agent would then have done, how long
diagnosis would have taken, or how many tokens it would have spent.

## 7. Holdout and validity
- Split MCP-RE changes chronologically: tune nothing on the last third; report on it only. Do not iterate on the
  same handful of cases.
- Threats: cancelled runs (308 of 1,000 sampled cancelled by concurrency), PRs that triggered no verification run
  (path filters), flakiness (e.g. ecd1196c), correlated detection between lanes, fingerprint coarseness (a dependency
  bump moves all 308 units), small known-defect set, one security consumer.

## 8. Bounded experimental plan (each step separately authorized)

| Step | Action | Executes | Budget (proposed) | Stop condition | Output use |
|---|---|---|---|---|---|
| E0 | Archive MCP-RE `verification.yml` and `mutation-probe.yml` job logs (R-15) | downloads only (GET) | see [owner decision package](owner-decision-package.md) §2 | done or budget | evaluation input only |
| E1 | Offline replay of arms A/B/C over archived logs and git history | MCP-RE `fingerprint`/`select-units` at historical heads in a scratch checkout; **no tests, proofs or probes** | ≤ 300 PR heads; ≤ 20 CPU-hours; no network beyond git | budget reached or first false-fresh in C | report; informational |
| E2 | Projection equivalence (H5) on 3 committed closure targets + data controls N1–N10, N13, N14, N17–N24 | evaluator over data files only | ≤ 1 CPU-hour | any unexplained disagreement | report; gates R-16 |
| E3 | Shadow mode on real changes | arm B and arm C recommendations both logged beside normal CI for each change; **no change to any gate**; agent K measured only with consent | 30 PRs or 4 weeks, whichever first; 0 additional CI minutes beyond observation | budget, or any recommendation that would have skipped a mandatory check | report; informational |
| E4 | Exec controls N11, N12, N15, N16 and read-set instrumentation (the only route to a `complete` boundary class) | targeted runs in scratch copies | ≤ 10 runs; ≤ 4 CPU-hours | all four answered | findings to owners |

No step may modify a gate, policy registry, proof, review or attestation, or produce evidence that a gate reads.

## 9. Deliverable of the evaluation
A report with, per arm: §4 metrics with uncertainty, misses and false-fresh listings with commit SHAs, control
verdicts, and a recommendation on R-7, R-14 and R-16. It is input to owner decisions, not a decision.
