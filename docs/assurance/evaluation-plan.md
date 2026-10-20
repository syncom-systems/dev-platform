# Deliverable 5 — Reference evaluation plan

> Status: **plan only; nothing in it has been executed or is authorized.** Each experiment (§8) needs a separate,
> explicit authorization naming permitted actions, resource limits and how outputs may be used (RFC §17). Results of an
> authorized experiment are exploratory and never satisfy an assurance obligation.

## 1. Questions and hypotheses

| ID | Hypothesis | Primary metric | Must not worsen |
|---|---|---|---|
| H1 | Identity-bound evidence preservation (draft ADR B) never reports false freshness | false-fresh count (§4.4) = 0 | — |
| H2 | Preservation in the development loop reduces repeated verification | machine time and repeated runs per change | missed checks, false-fresh |
| H3 | Deterministic sequencing (`c/p` + gap actions) reduces time to first failure and diagnosis | time-to-first-failure, localization | missed checks, mandatory outcomes |
| H4 | The assurance-aware planner beats a simple deterministic baseline on the whole loop | (T, K) including planner overhead | R metrics |
| H5 | Dev Platform's recomputation of MCP-RE assurance equals MCP-RE's own verdicts | disagreement count = 0 | — |

## 2. Strategies compared (same obligations in every arm)

| Arm | Definition | Notes |
|---|---|---|
| **A — current** | MCP-RE as wired: `select-units` scope; empty scope → nothing; deferred → full pre-merge; mutation deferred → weekly (`verification.yml:925-961`, `mutation-probe.yml:120-141`). Dev Platform/NGA: glob selection (`impact.py`) | reconstructed from logs, not re-run |
| A′ — documented | `select-units` as documented: deferred → weekly/release | reported for contrast only; not a candidate |
| **B — simple deterministic** | Dev Platform glob impact over each MCP-RE unit's declared `paths` as `inputs`, unmapped → all, no consumer closure, fixed order | the "obvious" generic baseline |
| **C — assurance-aware** | fingerprint-based applicability with fail-closed unmapped paths (ADR B §5) + prerequisite consumer closure + `c/p` ordering + gap actions + budget stop for optional actions | the proposal |
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
- Reference = the complete run on the same commit where available, else the next complete run, else the known-defect
  label. A unit-lane that fails in the reference but is not selected (or is preserved) by the arm is a **miss**.
- Report misses separately for mandatory and optional obligations. **Any mandatory miss rejects the arm** unless an
  explicit consumer policy (e.g. a declared release-due obligation, draft ADR C B1) covers it, in which case the
  deferral is recorded with the gate that catches it.

### 4.6 Residual uncertainty (R proxies)
At merge, per change: claims affected and not established; outstanding obligations by due gate; `unknown`
applicability items; open gap actions. At release: assurance-closure verdict and blockers. Never a probability.

### 4.7 Planner overhead
CPU time and, for D only, tokens of the planner itself; counted in T and K.

## 5. Nonvacuity and negative controls

Each control has an expected verdict; an arm or evaluator that does not produce it fails. Controls marked *data* are
perturbations of records/projections (no execution); *exec* need an authorized run.

| # | Control | Construction | Expected |
|---|---|---|---|
| N1 | Empty claim set | projection with no active claims | closure `UNDECLARED`, never `PASS` |
| N2 | Empty roots | roots `[]` | `UNDECLARED` |
| N3 | Claim with empty support | `supported_by = []` | `no-support` → `INCOMPLETE` |
| N4 | Support only non-applicable/not-run | all lanes `NOT_REQUIRED` / `not_run` | `INCOMPLETE` |
| N5 | Unresolvable reference | `supported_by` names a missing unit | load error or `INCOMPLETE`, never `PASS` |
| N6 | Stale review | change a claim statement digest | review `stale(claim)`; dependants not established |
| N7 | Changed proof model | move the provider/model component | `stale`; closure `INCOMPLETE` |
| N8 | Omitted result | drop one evidence item | `unknown`/`INCOMPLETE`; MCP-RE `REFUSE` parity |
| N9 | Failed prerequisite | one supporting unit failed | closure `FAILED`, consumers blocked |
| N10 | Unknown impact | change set unknown / unmapped path | every owed check selected; never empty |
| N11 | Python test hollowing (F-1) | empty a pytest body named by a unit | must be `stale` under C; arm A reports `current` → documents the gap |
| N12 | Undeclared V0 helper change (F-2) | change a helper outside a V0 unit's `paths` that its tests call | C must not report `current` unless read set covers it; expected to expose the gap |
| N13 | False mutation attribution | replay 9e0ba722's pre-fix probes; a control that fails by scaffolding panic | not counted as detection under `assertion` attribution; flagged under `test-identity` |
| N14 | Selector self-narrowing | change the selection/fingerprint code | everything owed; never narrower |
| N15 | Unbound carry (Dev Platform) | `--previous` from another revision/config | carry refused (ADR B); today accepted — documents the gap |
| N16 | Certification carry (Dev Platform) | change check without `full`, verified `--previous` | not certified (ADR B); today certified by reading — confirms or refutes finding 4 |
| N17 | Projection inconsistency | producer verdict `PASS` with a failing unit | `projection-inconsistent`, never `PASS` |
| N18 | Toolchain bump | move environment component only | all evidence `stale(environment)`, reviews current (MCP-RE v0.18.0→v0.18.1 parity) |

N11, N12, N15, N16 *exec*; the rest *data*. N1–N9, N17, N18 run against the three committed MCP-RE closure targets.

## 6. Failure criteria (reject the proposed optimization if any holds)
1. Any false-fresh item (§4.4).
2. Any mandatory miss not covered by a declared consumer policy (§4.5).
3. Any mandatory gate outcome less strict than arm A on any change.
4. Any control in §5 not producing its expected verdict.
5. Net `T_machine + planner overhead` not lower than arm A on the held-out set, or (in shadow) K not lower, with
   uncertainty intervals excluding zero gain.
6. Any H5 disagreement unexplained by a documented, owner-accepted mapping loss.
Improved test counts or raw coverage are not success criteria (RFC §14).

## 7. Holdout and validity
- Split MCP-RE changes chronologically: tune nothing on the last third; report on it only. Do not iterate on the
  same handful of cases.
- Threats: cancelled runs (308 of 1,000 sampled cancelled by concurrency), PRs that triggered no verification run
  (path filters), flakiness (e.g. ecd1196c), correlated detection between lanes, fingerprint coarseness (a dependency
  bump moves all 308 units), small known-defect set, one security consumer.

## 8. Bounded experimental plan (each step separately authorized)

| Step | Action | Executes | Budget (proposed) | Stop condition | Output use |
|---|---|---|---|---|---|
| E0 | Archive MCP-RE `verification.yml` and `mutation-probe.yml` job logs (R-15) | downloads only (GET) | ≤ 3,000 logs; private storage | done | evaluation input only |
| E1 | Offline replay of arms A/B/C over archived logs and git history | MCP-RE `fingerprint`/`select-units` at historical heads in a scratch checkout; **no tests, proofs or probes** | ≤ 300 PR heads; ≤ 20 CPU-hours; no network beyond git | budget reached or first false-fresh in C | report; informational |
| E2 | Projection equivalence (H5) on 3 committed closure targets + data controls N1–N9, N17, N18 | evaluator over data files only | ≤ 1 CPU-hour | any unexplained disagreement | report; gates R-16 |
| E3 | Shadow mode on real changes | planner recommendations logged beside normal CI; **no change to any gate**; agent K measured only with consent | 30 PRs or 4 weeks, whichever first; 0 additional CI minutes beyond observation | budget, or any recommendation that would have skipped a mandatory check | report; informational |
| E4 | Exec controls N11, N12, N15, N16 and read-set instrumentation | targeted runs in scratch copies | ≤ 10 runs; ≤ 4 CPU-hours | all four answered | findings to owners |

No step may modify a gate, policy registry, proof, review or attestation, or produce evidence that a gate reads.

## 9. Deliverable of the evaluation
A report with, per arm: §4 metrics with uncertainty, misses and false-fresh listings with commit SHAs, control
verdicts, and a recommendation on R-7, R-14 and R-16. It is input to owner decisions, not a decision.
