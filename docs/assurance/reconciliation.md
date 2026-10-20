# Deliverable 1 — Architecture reconciliation: Dev Platform and MCP-RE

> Status: investigation output, not ratified. Revisions, method and labels: [README](README.md).
> Dev Platform paths are relative to this repository at `6c0e7b4`; MCP-RE paths are relative to MCP-RE at `8262c5fa`.

## 1. Findings in brief

1. **The two systems answer different questions and barely overlap in mechanism.** Dev Platform decides *which
   declared checks a change owes and whether they passed* (`impact.py`, `model.py`, `engine.py`, ~520 lines). MCP-RE
   decides *which propositions currently hold, on what evidence, premises and reviews* (`tools/verification/`,
   ~20 kLOC). The RFC's assurance layer is almost entirely MCP-RE-shaped; Dev Platform supplies the execution,
   identity, stage, release and acceptance layers around it.
2. **Dev Platform has no claim, argument, premise, review, fingerprint, coverage or budget concept** (ABSENT; search
   terms in §3.9). Its `check` is simultaneously the verification action, the obligation carrier and the evidence
   subject.
3. **Dev Platform evidence reuse is unbound.** The only cross-run reuse is `--previous <result.json>`, read as
   `{id, state}` pairs only (`engine.py:113`, `cli.py:672`); revision, configuration, check definition, platform and
   toolchain identity of the previous record are never compared. No workflow passes it.
4. **Candidate certification defect (Interpretation, by reading; not executed).** A `change`/`always` check need not
   declare `full` (`config.py:314-322`). At `--stage full` such a check is not a candidate, gets `NOT_RUN` unimpacted
   (`engine.py:129-130`) and keeps its carried state; certification requires every configured check `verified`
   (`engine.py:206`). An arbitrary `--previous` file can therefore satisfy certification for a check that did not run. Standalone analysis: [defect report](certification-carry-defect.md).
   No test covers the case (`tests/test_engine.py:10-14` declares `full` on every change check).
5. **MCP-RE's assurance ladder is implemented and non-vacuous, and is the right model to generalize:** lane verdict →
   unit freshness at a fingerprint → review currency → evidence establishment → `currently_verified` with dependency
   fixpoint → root completeness → assurance closure (`_manifest.py:347-390`, `_graph.py:220-362`,
   `_review.py:417-588`, `tools/verification/assurance-closure:151-222`).
6. **The RFC's description of MCP-RE merge deferral is inaccurate in a way that narrows the ADR 0006 conflict.**
   `select-units` labels over-cap, platform and uncomputable scopes "deferred … verified by the weekly / release run"
   (`select-units:142-169`), but the gating workflow measures *every unit before merge* in that case
   (`.github/workflows/verification.yml:954-961`). Only `mutation-probe.yml:131-141` really defers. See §6.1.
7. **MCP-RE's assurance lanes are not required for merge.** The live ruleset on `main` (read 2026-10-20) requires only
   three `pre-merge.yml` Bazel contexts; neither `verification.yml` nor `mutation-probe.yml` is required. In-repo
   documents disagree about this (§6.1).
8. **MCP-RE impact defaults differ from Dev Platform's.** In MCP-RE a path outside every fingerprint read set moves no
   fingerprint and yields an *empty* scope, which skips measurement and the negative-control job
   (`verification.yml:946-950`). Dev Platform treats an unmapped path as unknown and selects every owed check
   (`impact.py:81-84`). This is the substantive semantic conflict, more than the 20-unit cap.
9. **Two MCP-RE fingerprint gaps (Interpretation, by reading):** Python/TypeScript test bodies contribute nothing to
   `test_sources` (`_fingerprint.py:429-442` resolves only `//` Bazel labels), and V0 Rust units' dependency closure is
   declared (18 edges for 308 units), not measured (`tests: test_measured_inputs.py:115-120`). Both are false-freshness
   risks to carry into any evaluation as negative controls.
10. **Only two MCP-RE assurance outputs are versioned and committed**: the closure record (`schema_version 1`,
    `kind mcp-re.assurance-closure-record`) and the release-assurance record (`schema_version 2`). The richest state,
    `review --json`, is unversioned. A read-only projection needs one versioned export from MCP-RE (§8).

## 2. Concept map

Classification: **R** reuse as is · **G** generalize (mechanism reusable, names/policy consumer-specific) ·
**C** consumer-specific, stays in the consumer · **N** new (no implementation in either).

| RFC concept (§4) | Dev Platform (implemented) | MCP-RE (implemented) | Class | Notes |
|---|---|---|---|---|
| Requirement | none; `dev-platform.toml` declares checks, not behaviour | none as an object; theorem `statement` + `security_consequence` act as one; `docs/spec/security-boundary.md` via `claim_surface_gate.py` | N / C | Keep consumer-owned prose; no object needed in the minimal core |
| Claim | ABSENT | `[[theorem]]`, 11 closed keys (`_theorems.py:51-70`), 133 claims, 12 roots | G | Rename `security_consequence`→consumer field; `THM-` ID form is consumer-specific |
| Logical claim dependency | ABSENT | `depends_on`, acyclic, may not invert a `PROOF_DEPENDENCY` (`_theorems.py:172-311`) | G | Directly generic |
| Argument | ABSENT | implicit: `supported_by` + `review_requirement` + review record | G | No separate argument object is warranted (proposal §3.3) |
| Assurance unit | `check` is the nearest, but it is an action | `[[unit]]` (`_manifest.py:111-139`), 308 units, classes V0–V3 | G | V-classes are prover tiers: consumer-specific |
| Contract | ABSENT | `exported_contracts` + `CONTRACT_CONSUMES` edges with seals (`_manifest.py:435-491`, `_graph.py:272-362`) | G | **0 contract edges and 0 seals in the snapshot**: implemented, unexercised by data |
| Premise / assumption | fixed `scope.limitations` disclaimers only (ADR 0015) | `assumptions.toml`, classes `assumed`/`external-boundary`/`review-obligation` (+`model-registration`) (`_premise.py:65-282`), 73 live | G | Discharge predicates are partly Rust/Verus-specific |
| Evidence | `dev-platform.result/v1` per check: outcome + state (`engine.py:20`, `schemas/result-v1.schema.json`) | `EvidenceRecord{unit_id, lane, result, fingerprint, detail, prover?}` (`_evidence.py:76-108`), unversioned, not committed | G | Different granularity: run×check vs unit×lane |
| Evidence identity | none per check; run-level `environment.identity_digest`, platform digest, revision (`engine.py:210-235`) | component fingerprint `ENCODING_VERSION=10` with measured read set (`_fingerprint.py:169, 763-924`) | G | Dev Platform's environment identity is stronger (closure-verified tools); MCP-RE's input identity is far stronger |
| Freshness / applicability | `pending/verified/failed/invalidated`, glob impact (`model.py:39-71`) | `FRESH`, six `DIRTY_*`, `UNKNOWN`, `BLOCKED` (`_graph.py:37-131`) | G | MCP-RE's cause-typed staleness is the generic target |
| Verification action | `check` → adapter command (`adapters.py:24-45`) | lane × unit (`_lanes.py:51-92`), `--unit` scoping (`_unit_selection.py`) | R (DP) | Reuse the Dev Platform check as the action; do not add an action type |
| Obligation | `obligation ∈ {always, change, periodic}` × `stages` (`model.py:19-22`, `config.py:314-322`) | lane requirement from unit tier/evidence URIs (`_lanes.py:124-134`, `_compose.py:83-99`); N1 falsifier obligations (`_assurance_graph.py:199-234`) | R + G | Dev Platform obligation semantics are ratified (ADR 0006) |
| Counterexample control | ABSENT | 538 mutation probes with `expect_red` (`_mutation.py:19-155`), 60 structural probes, measured-apparatus controls | G | Probe schema is text-level and ecosystem-neutral |
| Human semantic review | ABSENT (authorization/v1 covers releases/changes only, `records.py:92`) | review records bound to claim fingerprint and `review_digest` (`_review.py:63-339`, `_fingerprint.py:952-1209`) | G | Reviewer identity is an unauthenticated string in MCP-RE (`_review.py:192-193`) |
| Assurance closure | ABSENT (Dev Platform "closure" = tool runtime file closure, ADR 0015, `closure.py`) | `assurance-closure` PASS/FAIL, non-vacuous (`assurance-closure:151-222`), closure record v1 | G | Name collision to resolve (R-12) |
| Checkpoint | stage `edit/pre-commit/pre-merge/full` | event `pull_request/push/schedule/workflow_dispatch` | R (DP) | |
| Release verification | artifact correspondence: `tools/verify_release.py`, `dev-platform.verification/v1` (ADR 0015 claim 2) | `release-assurance` record v2: claims on the release commit | — | **Same words, different claims** (§5) |
| Owner acceptance | `authorization/v1` + lifecycle `accepted` only via pinned verifier (`lifecycle.py:38-60`, ADR 0016/0017) | owner-approval ledger (`_approvals.py`), rulings; no release acceptance object | R (DP) | |
| Selection / planner | glob impact, fail closed; cost never read (`impact.py:48-89`, `test_impact.py:68`) | `select-units`: fingerprint diff + prerequisite consumer closure + 20-unit cap | G | No cost-aware sequencing exists anywhere |
| Budget / stopping | ABSENT (no check timeout, `engine.py:31`) | CI `timeout-minutes` only (`verification.yml:908-1227`) | N | |

## 3. Dev Platform as implemented

### 3.1 Stages, obligations, selection — IMPLEMENTED
- Stages `edit → pre-commit → pre-merge → full` (`model.py:12-16`); admission stages are `pre-merge`, `full`
  (`model.py:46`). `edit` has no special behaviour; there is no editor/agent integration (ADR 0007 `integrations/`
  "none exist yet" — confirmed absent).
- Obligation is an enum field on a check (`config.py:73`), not an object. Load-time invariants: `always`/`change` must
  include `pre-merge`; `periodic` must include `full`; `change` must declare `inputs` (`config.py:314-322`;
  `tests/test_config.py:51-62`). `periodic` has no scheduler; it runs only at `--stage full`.
- Selection (`impact.py:48-89`): at `full` every candidate; otherwise `always` checks, checks whose `inputs` match a
  changed path, everything owed on a `global` match, an unmapped path or an unknown change set
  (`tests/test_impact.py:36-70`). `git_changed` returns `None` (unknown) on any git failure (`engine.py:60-80`).
- `cost` is read only to copy and print it (`engine.py:127`, `cli.py:731`); `tests/test_impact.py:68` asserts selection
  never reads it. RFC §13.1 is accurate.
- `project.assurance` (`standard | security-critical`, `config.py:180-182`) is validated and echoed, and changes no
  behaviour (Interpretation from a full-text search).

### 3.2 Outcomes, evidence state, admission, certification — IMPLEMENTED
- Outcomes `passed | failed | unavailable | not_run`; states `pending | verified | failed | invalidated`
  (`model.py:30-43`); `advance()` invariants tested (`tests/test_model.py:12-33`). Exit 127 is `unavailable`
  (`engine.py:155-163`); an unroutable runner is `unavailable` without executing (`engine.py:151-153`).
- Admission: every check *selected in this run* passed *in this run*, environment conformant, infra pin honoured
  (`engine.py:174-184`). Carried state never satisfies admission.
- Certification blockers (`engine.py:186-207`): stage `full`, platform `pinned` (not `self`: `resolve.py:39-42`,
  `tests/test_engine.py:106`), known revision, clean tree, conformant and certifiable tool identity, infra not blocking,
  executed, every check `verified`.
- **Doc discrepancy:** `docs/verification-model.md:51-52` says `pinned` or `self` certifies, and ADR 0006 §6 says
  "non-override platform"; code and `docs/architecture.md:75` say `self` never certifies.

### 3.3 Evidence reuse — IMPLEMENTED but unbound
- `--previous` (`cli.py:67, 672`) → `prev_state = {id: state}` (`engine.py:113`). Nothing else from the record is read.
  `tests/test_engine.py:93-97` covers carry; nothing covers refusal of a mismatched predecessor.
- Consequence for the RFC's *evidence preservation* objective: Dev Platform today preserves evidence only implicitly —
  a check not reached by the change is simply *not owed* at `pre-merge`. The soundness of that rests on an unchecked
  inductive premise: that the base revision was itself verified.
- Finding 4 (§1) follows from this.

### 3.4 Adapters — IMPLEMENTED, coarse
- Fixed dict `bazel | python | cargo | exec` (`adapters.py:24-45`; ADR 0004 "no plugin runtime"). Each yields only an
  exit code: no per-target results, durations, logs, coverage or timeouts.
- `bazel_rust.py` is a separate toolchain proof (`dev-platform.bazel-rust-proof/v1`), not an adapter.

### 3.5 Identity, runners, release trust, acceptance — IMPLEMENTED
- Tool identity strengths up to `closure-verified` / `bazel-locked`; only those certify (`toolchain.py:120-133,
  366-381`). Runner routing is a recorded requirement check; commands run locally either way (`engine.py:136-155`).
- Four claims kept apart (ADR 0015): development verification, release verification (artifact correspondence),
  certification, owner acceptance. `accepted` has no incoming edge and is derivable only from a `VerifierResult`
  produced by the pinned verifier (`lifecycle.py:38-60, 141-155`; `tests/test_lifecycle.py`).
- Result records are self-reported: `tools/verify_consumer_evidence.py:8-10` states it cannot rule out a fabricated
  record.

### 3.6 Admission policy and planning (Proposed ADRs) — IMPLEMENTED
- ADR 0018 and `prcheck.py` concern workflow trigger/runner safety, not verification obligations. Actual merge blocking
  is GitHub required status checks (ADR 0005, 0007).
- ADR 0017 and `planning.py` are release/milestone planning; nothing recommends a next verification action.

### 3.7 Versioned contracts available to an external evaluator
12 `$id`'d schemas under `schemas/`; `dev-platform.result/v1` from `check|explain --json` is the consumable surface
(selection reasons, outcome, state, environment identity, certification blockers). `tests/test_schemas.py:18-74` keeps
schemas and builders aligned.

### 3.8 Extension points — largely ABSENT
No consumer-defined adapter or evidence provider (`config.py:20`, `adapters.py:45`). `exec` is the escape hatch.
The only external-process plug-in is the infrastructure resolver (`infra.py:233-242`). `evidence put` stores arbitrary
JSON in a write-once content-addressed store (`evidence.py:24-38`) that nothing reads for check reuse.

### 3.9 Searched and absent
Case-insensitive over `src/` and `tests/`: claim, premise, assumption, theorem, coverage, mutation, fingerprint,
budget, historical, duration, elapsed, "test selection", waiver, defer, review. Hits are prose only.

## 4. MCP-RE as implemented

### 4.1 Claims and logical graph — IMPLEMENTED
- Closed theorem schema; ~30 forbidden keys rejected with the owning authority named (`_DUPLICATED_AUTHORITY`,
  `_theorems.py:75-104`; `test_theorems.py:210-229`): no stored status, approval, root flag, reverse edge or derived
  severity. A repository-wide `FORBIDDEN` status-key gate exists (`scripts/registry_approval_gate.py:47-60`).
- Roots declared, never inferred; an empty root set is `UNDECLARED` (`_theorems.py:225-239`; `_review.py:495-510`).
- `structurally_supported_theorems` is explicitly *not* establishment (`_theorems.py:362-398`).

### 4.2 Units, edges, freshness — IMPLEMENTED
- 7 closed edge kinds (`_manifest.py:78-86`); only `COMPILE_DEPENDENCY` (15) and `PROOF_DEPENDENCY` (3) appear in
  data. Seal semantics tested (`test_invalidation.py:312-363`) but no sealed edge is declared (`_graph.py:150-151`).
- `derive_unit_state` fails closed: no attestation, missing component, unclassified change, or equal components with a
  different digest → `UNKNOWN` (`_graph.py:220-269`). A failed Verus or Lean record → `BLOCKED` — hard-wired prover
  names at `_graph.py:232`.

### 4.3 Fingerprints — IMPLEMENTED
- Component-wise digest over git-tracked files (`_fingerprint.py:209-296, 763-897`): declared sources, whole-crate and
  dependency-crate sources for formal units, build configuration, selected tests and integration-test bytes, every
  lane's own code, probe/measurement registry entries, trusted assumptions, crossed trust boundaries, toolchain pins,
  model/threat/policy revisions. `_fingerprint.py` itself is represented by `ENCODING_VERSION`.
- The read set is recorded and `scripts/verification_trigger_gate.py` proves workflow path filters cover it.
- Dependency closure from a committed `bazel query` table (`verification/generated/rust-targets.json`,
  `_rust_targets.py:260-278`), package-granular. Not rustc dep-info, not per file.
- Deliberate over-invalidation: v0.18.0 → v0.18.1 (a rustls bump) moved all 308 unit fingerprints and no theorem
  fingerprint (closure-record comparison).
- Gaps: §1 item 9.

### 4.4 Lanes and counterexample controls — IMPLEMENTED
- Test lane runs exactly the declared selectors; declared-but-not-run, ignored or failed → FAIL; zero selected → FAIL.
- Mutation lane: a probe kills only if the weakened tree builds, every `expect_red` control is reported, and at least
  one named control is `FAILED` (`verify-mutations:157-172, 785-823`). **Attribution is by test identity, not by
  assertion**: a panic in scaffolding of a named test counts (Interpretation). The unweakened baseline comes from the
  test-lane record at the same fingerprint, required by `attest` (`attest:86-94`). History: 9e0ba722 (#1036) fixed two
  probes that reported kills they did not make.
- Structural lane requires the declared rustc error code and span; measured lane requires reproducibility or an
  `APPARATUS-MOVED: n≥1` sensitivity result (`_measured.py:154-191`).
- Verus: prover JSON, whole-crate run, symbol list; one bespoke non-vacuity probe (`_verus_nonvacuity.py`). Lean:
  `#print axioms` against a kernel baseline, `sorryAx` never registrable, model stamp, activation probe.

### 4.5 Evidence, issuance, verdicts — IMPLEMENTED
- Lane verdicts `NOT_REQUIRED | PASS | FAIL | UNAVAILABLE | SKIPPED`; aggregate `PASS | FAIL | INCOMPLETE`; all lanes
  `NOT_REQUIRED` → `INCOMPLETE` (`_manifest.py:347-390`; `test_verdict_algebra.py`).
- A scoped run's bundle is always `INCOMPLETE` (`verify:175-185`) and cannot be attested; issuance refuses on missing
  or stale records or a broken prerequisite (`_evidence.py:211-326`).
- Evidence records live in a gitignored store and move between CI jobs as 14-day artifacts; only closure records are
  committed.

### 4.6 Reviews, premises, corrections — IMPLEMENTED
- Review binds `reviewed_fingerprint` (statement + consequence + scope + transitive dependency claims + review
  requirement) and `review_digest` (adds premise entries and semantic components of supporting units)
  (`_fingerprint.py:952-1209`). Toolchain/policy/lane changes stale evidence, not reviews. `owner`, `title` and severity
  are not bound except through ledger entry approvals (9 of 133 theorems).
- Reviewer: any non-empty string. Anti-self-approval is structural (no tool writes a review record); the agent
  prohibition is DOCUMENTED-ONLY (`docs/verification/05-refinement-and-closure-model.md:252`). The ledger "signature"
  is `sha256(text)` in a committed file — authenticity rests on repository write access.
- Claim corrections chain owner-reviewed to current fingerprints and satisfy only the merge-path claim-surface gate,
  never review currency (`_claim_corrections.py:36-46, 324-369`).
- Premise class affects no verdict; a discharged observable `review-obligation` fails `check-assumptions`.

### 4.7 Closure and release assurance — IMPLEMENTED
- `currently_verified = review_current ∧ evidence_established`, then a fixpoint over `depends_on`
  (`_review.py:417-492`). Root completeness `COMPLETE | INCOMPLETE | UNDECLARED` with typed blocking causes
  (`_review.py:513-588`).
- `assurance-closure` PASS requires a non-empty active set (`bool(active)`, `assurance-closure:203`), every active
  theorem on all three axes, and complete roots; it refuses non-schedule/dispatch events, scoped bundles and non-PASS
  aggregates (`assurance-closure:115-142`).
- `release-assurance` (v2) runs verify, attest, check-assumptions, `review --require-root-complete` and the
  claim-surface gate (`release-assurance:128-154`). **It does not run `assurance-closure`**: a release requires roots
  (and their dependency closure) established, not every theorem; epic close requires the stronger closure.
- Open N1 falsifier obligations are printed by `review` as making roots incomplete (`review:204-208`) but are not an
  input to `theorem_assurance` (Interpretation; enforcement is the separate shrink-only ratchet).

### 4.8 Selection and CI — IMPLEMENTED + WIRED
- `select-units` (`select-units:142-169`): platform path touched → `deferred`; else fingerprint diff (base computed by
  the base's own tools) + consumer closure over prerequisite edges, ignoring seals; `> 20` → `deferred`; any error →
  `deferred`. Empty scope is a stated result (`test_scoped_verification.py:129-146`).
- `verification.yml` (WIRED): empty scope → nothing measured, negative controls skipped (`:946-950`); deferred → every
  unit measured before merge (`:954-961`, comment "Hosted minutes are free for this repository"); complete runs on
  schedule/dispatch only feed `assurance-closure` (`:1222-1248`).
- `mutation-probe.yml` (WIRED): deferred or empty → no probe at merge; "The complete run (weekly, or dispatched)
  applies every probe" (`:131-141`).
- No persistent record of a deferred obligation exists; the scope artifact is uploaded only for a non-empty scope.
- Cost data is never used by selection; timings are printed only (`verify:491-500`, `verify-mutations:631-640`).

## 5. The distinctions the RFC requires, checked against code

| Distinction | Dev Platform | MCP-RE |
|---|---|---|
| green test ≠ current evidence | partly: `passed` is per run; `verified` can be carried unbound (§3.3) | yes: record bound to a pre-run fingerprint; stale record → `UNAVAILABLE` |
| current evidence ≠ established claim | no claims | yes: `EVIDENCE_ESTABLISHED` needs every supporting unit `FRESH`; `currently_verified` adds review + dependencies |
| established claim ≠ complete closure | no claims | yes: roots + all-theorem closure, non-vacuous |
| human semantic review ≠ technical verification | no claim review | yes: separate axes and digests; corrections cannot substitute |
| development ≠ release verification ≠ owner acceptance | yes (ADR 0015 four claims) | development vs release assurance yes; no owner acceptance of releases |
| "release verification" | artifact is what the trusted workflow built (provenance) | the release commit's roots are established (assurance) |

Dev Platform's "release verification" and MCP-RE's "release assurance" are different, complementary claims about
the same release. Neither implies the other. The generic model must name them separately (proposal §5).

## 6. Conflicts

### 6.1 ADR 0006 versus MCP-RE merge selection (stated, not resolved)

Facts:
- **MCP-RE is not a Dev Platform consumer.** No file in the snapshot references Dev Platform (full-text search). ADR
  0006 governs Dev Platform configuration semantics; it does not currently bind MCP-RE's own CI. The conflict is
  latent: it materializes if MCP-RE adopts Dev Platform for these lanes, or if Dev Platform generalizes MCP-RE's
  selection.
- Component-by-component:

| ADR 0006 rule | MCP-RE behaviour | Conflict? |
|---|---|---|
| §1 selection never reads cost | the 20-unit cap is a cost proxy justified by minutes (`select-units:83-86`); in `verification.yml` it only switches *scoped → everything*, i.e. more work, never less | **Not for admission** as wired; **yes** if the tool's documented "defer to weekly" were adopted |
| §2 a mandatory check must be admissible at pre-merge | verification lanes: measured pre-merge (scoped or full). Mutation probes: deferred to the weekly complete run when over cap or platform-touching | **Yes, for the mutation lane** |
| §3 unknown/unmapped impact selects every owed check | a path outside every fingerprint read set yields an empty scope; nothing measured, negative controls skipped. An uncomputable scope → full run (fail closed) | **Yes, for unmapped paths** (implicit-ignore vs explicit-ignore) |
| §4 `verified` only from a pass or a provably unreached carry | fingerprint equality with a verified read set is a *stronger* proof of non-reach than path globs | Compatible in principle; subject to the §1 item 9 gaps |
| §6 certification requires a full run with everything verified | `assurance-closure` requires a complete dispatched/scheduled run; scoped bundles are always `INCOMPLETE` | Compatible |
| admission is enforced by required status checks (ADR 0005/0007) | verification and mutation-probe jobs are not required contexts on `main` (live ruleset 2026-10-20) | **Consumer policy question**: lanes are effectively advisory at merge |

- In-repo statements about required checks disagree: `CHANGELOG.md:550-553` ("neither verification job was ever
  required") versus `docs/dev/ci-runner-migration-analysis.md:35` ("Required status check"). The live ruleset agrees
  with the CHANGELOG.

Interpretation: the conflict has three real components — the unmapped-path default, the mutation-lane deferral and
the non-required status — and one apparent one (the cap) that, as wired, increases work. The decision is R-6/R-7.

### 6.2 Closure terminology
Dev Platform "closure" (ADR 0015) is a tool's runtime file closure; MCP-RE "closure" is assurance closure. Both are
established terms in ratified or committed material. Decision R-12.

### 6.3 Verdict vocabulary
MCP-RE assurance closure is `PASS | FAIL`; the RFC (§7.5) requires `INCOMPLETE` for absent/unknown support. MCP-RE
uses `INCOMPLETE` at aggregate and root levels but folds it into `FAIL` at closure level. A projection must keep the
cause so that "failed evidence" and "incomplete support" stay distinguishable (proposal §4.4).

## 7. Corrections to the RFC (for the record; the RFC is not edited)

| RFC text | Correction | Evidence |
|---|---|---|
| §10: select-units "explicitly defers oversized, untrustworthy, or verification-platform changes to weekly/release complete runs" | The tool says so; the gating workflow runs a full measurement before merge instead. Only the mutation-probe workflow defers. | `select-units:142-169`; `verification.yml:954-961`; `mutation-probe.yml:131-141` |
| §10: "Both mechanisms make their obligations visible" | MCP-RE records no deferred obligation; the scope artifact exists only for non-empty scopes, 14-day retention | `verification.yml:963-969` |
| §13.1: "result records; full-stage certification" | Add: evidence carry is unbound; result records are self-reported; adapters report exit codes only; `project.assurance` is inert; no check timeouts | §3.2–3.4 |
| §13.1: ADR 0017 listed with ratified ADRs | ADR 0017 (and 0018) are **Proposed** | `docs/adr/README.md` |
| §13.2: "includes proof and test sources" | Python/TypeScript test sources are not fingerprinted; V0 closure is declared | `_fingerprint.py:429-442`; `test_measured_inputs.py:115-120` |
| §13.2: review/closure "distinguish … root completeness" | Correct; add that `release-assurance` requires root completeness, not full assurance closure | `release-assurance:128-154` |
| §2.1: 800–1,300 tool calls per issue | No committed record exists; only local agent transcripts (private) could substantiate it | dataset inventory, [evaluation plan §3](evaluation-plan.md#3-datasets) |

## 8. What a read-only projection can and cannot represent today

From existing versioned MCP-RE outputs (closure record v1, release-assurance v2) a consumer can obtain: target
commit/tree, policy revision, ledger identity, per-unit and per-theorem fingerprints and review digests, root set and
verdict, counts. It **cannot** obtain, without a new versioned export owned by MCP-RE:
- per-theorem axis states and blocking causes (`review --json`, unversioned);
- unit freshness states and causes (`evidence-graph --json`, unversioned);
- the claim/unit/edge/premise graph itself except by parsing consumer TOML (`schema_version 2`, consumer-specific keys);
- lane evidence records (unversioned, artifact-only, 14 days);
- deferred or outstanding obligations (not recorded);
- costs (printed only).

Information that should **not** be represented generically: severity scales and N1 rules, V-class tiers, Verus/Lean
prover blocks (carried opaquely), trust-boundary rules, ledger mechanics, claim-correction authorities.

## 9. Reuse candidates

**Reuse directly (Dev Platform):** check/adapter as the verification action; stage and obligation semantics; fail-closed
impact; outcome vocabulary; environment and platform identity; certification; ADR 0015's four-claim separation;
`authorization/v1` with identity providers and explicit supersession; lifecycle; versioned schemas with
`test_schemas.py` alignment; the write-once evidence store.

**Generalize (ideas from MCP-RE; reimplementation, not file copies — MCP-RE is Apache-2.0, Dev Platform MIT, RFC §13.2):**
closed claim schema with duplicated-authority refusal; declared roots and `UNDECLARED`; `depends_on` with fixpoint
establishment; review bound to a claim fingerprint, separate semantic digest; premise classes; component-typed
fingerprints with a recorded read set and an encoding version; cause-typed freshness states; the five-verdict lane
algebra and `INCOMPLETE` aggregation; issuer separated from verifier; non-vacuous closure; probe schema
(`anchor`/`weakening`/`expect_red`); trigger-coverage gate idea; shrink-only ratchet registers.

**Consumer-specific (stays in MCP-RE):** theorem content, IDs, roots, severities and N1; V-classes; Verus/Lean/Charon/
Aeneas lanes and container identity; structural lane (rustc codes); Bazel target table and module-tree logic; trust
boundaries; ledger paths; GitHub workflow coupling of `assurance-closure`; required-check policy; the 20-unit cap.
