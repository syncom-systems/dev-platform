# Deliverable 2 — Refined architecture proposal: a minimal generic assurance model

> Status: **proposal for owner review; not ratified.** It refines RFC §4–§11 using the facts in the
> [reconciliation](reconciliation.md). Where it requires a decision, it names the register entry (R-n) in the
> [decision register](decision-register.md). It changes no existing semantics by itself.

## 1. Design position

1. **Add an assurance layer above checks; do not replace checks.** A Dev Platform `check` stays the one verification
   action, obligation carrier and execution unit (ADR 0004, 0006). The new layer says which *claims* the outcomes of
   those checks support, under which *premises*, with which *review*, and whether a declared *scope* is complete.
2. **One data contract, two producers.** The assurance layer evaluates one versioned document,
   `dev-platform.assurance-projection/v1`. A consumer can produce it from native Dev Platform declarations (ordinary
   projects) or from its own authoritative tooling (MCP-RE). Dev Platform never parses consumer-specific registries.
3. **Fix evidence identity before adding anything that depends on it.** Both evidence preservation and any planner
   are unsound while Dev Platform's carry is unbound (reconciliation §3.3).
4. **Evaluator before planner.** The planner is advisory, separately evaluated, and the last component built.
5. **No new runtime, service, database or plugin framework.** Pure functions over files, the existing CLI, existing
   schemas extended additively, the existing write-once evidence store.

## 2. Layers and authority

| Layer | Responsibility | Owner / authority | Status |
|---|---|---|---|
| L0 Consumer policy | requirements, claims, units, premises, roots, review rules, which checks are owed at which gate, closure scope per gate | consumer repository | consumer-owned; Dev Platform invents nothing (ADR 0004) |
| L1 Execution and identity | checks, adapters, stages, selection, outcomes, environment/platform identity, `result/v1` | Dev Platform (existing) | IMPLEMENTED |
| L2 Evidence applicability | bind each outcome to the identity of the inputs it depended on; decide `current / stale(cause) / unknown` | Dev Platform (new, small) | proposed — draft ADR B |
| L3 Assurance evaluation | pure function: projection + applicability + reviews → per-claim states, outstanding obligations, closure verdict | Dev Platform (new) for native consumers; **the consumer's own evaluator stays authoritative for projected consumers** | proposed — draft ADR A |
| L4 Planner | rank permitted actions; recommend next or abstain | advisory only, no authority | proposed — draft ADR D; gated by evaluation |
| L5 Governance | admission (pre-merge), certification (full), release verification, owner acceptance, budgets | Dev Platform (existing) + consumer policy + execution environment | IMPLEMENTED except budgets; due-gates proposed — draft ADR C |

Authority rules (normative in the drafts):
- L3 may report `PASS` only from admissible inputs; any unknown input yields `INCOMPLETE`, never `PASS`.
- L4 reads L3 and L1; it writes nothing that L3 or L5 reads as evidence.
- L5 obligations are never inputs to optimization; budget exhaustion never satisfies one.
- For a projected consumer, a disagreement between Dev Platform's recomputation and the producer's own verdict is
  reported as `projection-inconsistent` and is never `PASS`.

## 3. Data model

### 3.1 Objects (the whole core)

| Object | Fields (minimal) | Generalizes | Deliberately not included |
|---|---|---|---|
| **Claim** | `id`, `statement`, `scope`, `kind` (free consumer tag: functional, security, performance, …), `depends_on: [claim]`, `support` (`{form: all, units}`; `{form: any-of, groups}` reserved, reported `unsupported-form`, ADR A §4a), `premises?`, `argument?` (`incomplete`/`unknown` marker), `review_requirement`, `replaced_by?` | MCP-RE theorem (`_theorems.py:51-70`) | severity, consequence text, owner-as-unit, layers — consumer extension fields |
| **Root set** | `roots: [claim]`, declared, never inferred | `root_theorems` | — |
| **Assurance unit** | `id`, `inputs` (identity specification §4.1), `evidence: [check:<id>]`, `consumes: [{unit, contract, sealed}]` | MCP-RE unit (`_manifest.py:111-139`) | V-class, prover symbols, Lean theorem names — consumer extension fields |
| **Premise** | `id`, `statement`, `class ∈ {assumed, external-boundary, review-obligation}`, `scope: [unit]`, `discharge?` | `assumptions.toml` (`_premise.py:65-282`) | prover-mechanism tokens, Rust seam sites |
| **Review** | `subject` (claim or premise id), `reviewed_fingerprint`, `semantic_digest?`, reviewer identity assertion | MCP-RE review record (`_review.py:76-86`) + Dev Platform `authorization/v1` identity (ADR 0013) | stored status booleans (forbidden, as in MCP-RE) |
| **Evidence item** | `check`, `unit`, `outcome`, `input_identity`, `environment.identity_digest`, platform digest, revision, check-definition digest | Dev Platform result entry + MCP-RE `EvidenceRecord` | timestamps inside `result/v1` (determinism, `docs/architecture.md:31`) |

Rejected as separate objects (minimality): **Argument** (an argument is the typed `support`/`depends_on`/premise
structure plus a review bound to its digest; RFC §4's "a reference link is not itself a justified argument" is
enforced by requiring a current review. The supported structures are a deliberately small subset — conjunction,
one level of alternatives, explicit `incomplete` — listed in ADR A §4a; anything else is reported, not coerced), **Requirement** (stays consumer prose; a claim's
`statement` is the reviewable proposition), **Verification action** (it is a check), **Contract** as a node (it is a
named property on a `consumes` edge, as in MCP-RE).

### 3.2 Typed relations (kept separate, RFC §6)

| Relation | From → To | Graph | Meaning | Propagates |
|---|---|---|---|---|
| `depends_on` | claim → claim | logical | A relies on B being established | non-establishment upward (fixpoint) |
| `supported_by` | claim → unit | assurance | the unit's evidence is offered for the claim | `EVIDENCE_ESTABLISHED` needs every supporting unit current and passing |
| `evidenced_by` | unit → check | action | running the check produces evidence for the unit | — |
| `premised_on` | unit → premise (premise `scope`) | assurance | the unit's evidence holds only under the premise | premise change stales evidence and the review of supported claims |
| `consumes` | unit → unit (+contract) | impact | B's inputs/behaviour are inputs of A | staleness from B to A, except a sealed edge stops self/evidence staleness when the contract is unchanged |
| `identity` | evidence → input components | validity | the components whose change invalidates the evidence | — |

A build/import edge (Bazel, Cargo) may *populate* `consumes` or `identity`; it never populates `supported_by` or
`depends_on` (RFC §6).

### 3.3 The four state axes (RFC §7.1), each with a closed vocabulary

| Axis | Values | Source |
|---|---|---|
| Execution outcome (per run × check) | `passed / failed / unavailable / not_run` | existing `model.Outcome` |
| Applicability (per evidence item) | `current / stale(cause) / unknown`; causes `inputs, definition, environment, platform, dependency, premise, policy` | new (ADR B); maps MCP-RE `FRESH / DIRTY_* / UNKNOWN` |
| Claim assurance (per claim) | review `current / stale(cause) / absent / unknown`; support `established / not-established(units) / no-support / unknown / unsupported-form`; argument `declared / incomplete`; premises `accepted / premise-unaccepted(ids)`; `established` = argument declared ∧ review current ∧ support established under its form ∧ premises accepted ∧ every `depends_on` established | MCP-RE `theorem_assurance` (`_review.py:417-492`) |
| Scope completion (per gate × scope) | `PASS / INCOMPLETE(blockers) / FAILED(counterevidence) / UNDECLARED` | MCP-RE root completeness + closure, with RFC §7.5 `INCOMPLETE` |

Closure rules (normative in ADR A):
- `UNDECLARED` if the scope's root set is empty or no active claim exists (MCP-RE `bool(active)` and `UNDECLARED`).
- `FAILED` if any required evidence in the scope is `failed` and current, or a required unit is blocked by a failed
  prerequisite; listed with any `INCOMPLETE` blockers.
- `INCOMPLETE` if any claim in scope is not established for any other reason — including `no-support`, `unknown`,
  exclusively `not_run`/non-applicable support, stale review, or unresolvable references.
- `PASS` only otherwise. A `PASS` record carries the identities it was computed from, like MCP-RE's closure record.

Closure **scope** is consumer policy per gate: `roots` (MCP-RE `release-assurance`) or `all-active` (MCP-RE
`assurance-closure`/epic close). Both are expressible; neither is a platform default.

## 4. Evidence semantics

### 4.1 Input identity (ADR B)
A Dev Platform evidence item's identity is a canonical digest (`records.canonical_digest`) of components:

| Component | Content | Exists today? |
|---|---|---|
| `inputs` | digests of git-tracked files matching the check's declared `inputs` globs, plus `impact.global` files | globs exist (`config.py`); digest is new |
| `definition` | canonical digest of the check entry (adapter, argv/targets, stages, obligation, runner) | new |
| `environment` | `environment.identity_digest` | IMPLEMENTED (`toolchain.py:371-379`) |
| `platform` | release `tree_digest` / `source_digest` | IMPLEMENTED (`engine.py:83-91`) |
| `provider` (optional) | an opaque digest supplied by a consumer evidence provider (e.g. an MCP-RE unit fingerprint) | new, opaque |
| `encoding` | identity encoding version | new |

Rules:
- An `always` check has no carryable identity: it is owed at every admission (unchanged ADR 0006).
- Each identity records a **boundary class** for its `inputs`/`provider` component — `complete` (asserted only by a
  measuring or conservatively over-approximating mechanism), `declared` (globs, declared paths) or `unknown` (ADR B
  §2). No check in either repository has a `complete` boundary today; nothing here establishes read-set completeness.
- Carry is permitted only if every component of the previous item's identity equals the current one **and** the
  boundary class permits it at that gate (ADR B §4: `declared` carries at development and, as today, at admission,
  always reported as `declared`; nothing carries into certification); otherwise `stale(<first differing component>)`;
  any unreadable component, `unknown` class or unbound previous record → `unknown`, reported as uncertainty and
  treated as reached.
- Granularity is the check, because adapters report one exit code (`adapters.py`). Finer evidence needs finer
  declared checks or a provider; the core does not parse test output.
- A consumer whose glob `inputs` under-approximate what the check reads gets false freshness. That is already true of
  ADR 0006 impact today. Equal digests over such a set are **not** evidence of validity; the proposal therefore never
  upgrades a `declared` boundary to `complete`, labels every carry with its class, and makes the gap *measurable*
  (evaluation E4) instead of replacing unbound carry with a fingerprint that hides it.

### 4.2 Provenance classes (RFC §7.2)
Every item carries `provenance ∈ {declared, observed, measured, inferred}`. Only `observed`/`measured` items with
`current` applicability can establish support. `inferred` (including any LLM output) never satisfies an obligation.

### 4.3 Historical versus current
A `stale` or `unknown` item remains visible as history (for planning) and is never counted as support.

### 4.4 Formal proofs, mutation and measurements without special cases
- A Lean, Verus or model-checking run is a check (typically `exec`) whose evidence supports a unit. Its prover identity
  enters through `environment` (if the tool is in the toolchain profile) or `provider`. The core names no prover.
  MCP-RE's `BLOCKED` on a failed proof (`_graph.py:232`) generalizes to "a failed prerequisite unit blocks consumers",
  independent of prover.
- A registered counterexample control (mutation/structural probe) is a check whose `passed` means "the declared
  control discriminated the declared defect". It is recorded with `detects: {unit, defect_id}` and an
  `attribution ∈ {test-identity, assertion}` statement; a control's pass is evidence of detecting *that* defect only
  (RFC §6). MCP-RE's lane is `test-identity` attributed (reconciliation §4.4).
- A measurement is a check with an environment-scoped identity; a historical p99 is `stale(environment)` on a
  different profile.

## 5. Gates, verification kinds and acceptance

Names fixed to remove the collision in reconciliation §5–§6.2:

| Name | Meaning | Today |
|---|---|---|
| **development verification** | owed checks at `edit/pre-commit`; advisory, planner-ordered | Dev Platform (no owed obligations below pre-merge) |
| **admission** | owed checks at `pre-merge` pass in this run (ADR 0006) | Dev Platform |
| **certification** | `full` stage, everything verified *in this run* (ADR B closes the carry gap) | Dev Platform |
| **assurance closure** | L3 verdict for a declared scope at a gate | MCP-RE; Dev Platform proposed |
| **release verification** | the archive is what the trusted workflow built (ADR 0015) | Dev Platform |
| **release assurance** | assurance closure required by consumer policy at the release gate | MCP-RE `release-assurance` |
| **owner acceptance** | `authorization/v1` bound to the archive digest | Dev Platform |

`tool closure` is the proposed name for ADR 0015's runtime closure in new text (R-12); existing records are not renamed.

Due-gates (ADR C) let a consumer declare that a mandatory obligation is due *at release* rather than *at merge*,
without the planner or selection ever deciding that.

## 6. Read-only integration with MCP-RE

### 6.1 Shape
MCP-RE (its owner, in MCP-RE) adds one exporter producing `dev-platform.assurance-projection/v1` from its own
authoritative state (`review --json`, `evidence-graph`, closure record). Dev Platform adds
`dev-platform assurance evaluate --projection FILE [--json]`, which reads the file, validates it, recomputes the axis
states and closure from the graph and the per-unit/per-review states supplied, and compares with the producer's
verdicts. No execution, no access to MCP-RE source, no write-back.

### 6.2 Projection document (sketch; normative text in ADR A)

```json
{
  "schema": "dev-platform.assurance-projection/v1",
  "producer": {"name": "mcp-re", "tool": "tools/verification/…", "tool_revision": "<sha>", "encoding": "…"},
  "subject": {"repository": "syncom-systems/mcp-re", "commit": "<sha>", "tree": "<sha>"},
  "policy": {"revision": "adr-mcpre-059-r1", "closure_scope": "all-active", "review_ledger": "<digest>"},
  "claims": [{"id": "THM-0074", "statement_digest": "sha256:…", "kind": "security",
              "depends_on": ["THM-0015"], "supported_by": ["proxy.dispatch_commitment"],
              "review": {"state": "current", "reviewed_fingerprint": "sha256:…"}}],
  "roots": ["THM-0074"],
  "units": [{"id": "proxy.dispatch_commitment", "fingerprint": "sha256:…",
             "applicability": {"state": "current"}, "consumes": [],
             "evidence": [{"kind": "test", "ref": "test://…", "outcome": "passed", "fingerprint": "sha256:…"}]}],
  "premises": [{"id": "ASM-0007", "class": "external-boundary", "scope": ["…"], "review": {"state": "current"}}],
  "producer_verdicts": {"claims": {"THM-0074": {"review_current": true, "evidence_established": true,
                        "established": true}}, "roots": "COMPLETE", "closure": "PASS"},
  "extensions": {"mcp-re": {"severity": {}, "classes": {}}}
}
```

`extensions` is carried and never interpreted. `statement_digest` instead of text keeps authority over claim wording in
the consumer (text may be included as a convenience, never as the reviewed subject).

### 6.3 Mapping and loss

| MCP-RE | Projection | Loss / note |
|---|---|---|
| `FRESH` | `current` | — |
| `DIRTY_SELF / CONTRACT / EVIDENCE / DEPENDENCY / ASSUMPTION / POLICY / TOOLCHAIN` | `stale(inputs / inputs / definition / dependency / premise / policy / environment)` | cause names normalised; original kept in `extensions` |
| `UNKNOWN` | `unknown` | — |
| `BLOCKED` | `stale(dependency)` + failed prerequisite → closure `FAILED` | prover identity of the failing proof only in `extensions` |
| review `REVIEWED` / `STALE_*` / `UNREVIEWED` / `UNBACKED` / `UNKNOWN` | `current` / `stale(cause)` / `absent` / `stale(backing)` / `unknown` | ledger mechanics not represented |
| `NO_SUPPORT` | `no-support` | — |
| closure `FAIL` | `INCOMPLETE` or `FAILED` from blockers | MCP-RE folds both; Dev Platform separates them using blocker causes |
| claim corrections | not represented | merge-path only; never review currency |
| N1 obligations, severities | `extensions` | consumer policy |
| deferred obligations | not available | MCP-RE records none (reconciliation §4.8) |

### 6.4 Equivalence before any reliance
On the three committed closure targets and on deliberately perturbed copies of the projection (evaluation §5),
Dev Platform's recomputed verdicts must equal MCP-RE's for every claim, root set and closure. Until the owner accepts
that result, the Dev Platform evaluation of MCP-RE is informational.

## 7. Incremental verification

### 7.1 Evidence preservation (what remains valid)
- **Development (edit/pre-commit):** a check whose bound identity is unchanged since its last `passed` need not be
  re-run to inform the developer; report it as `current (carried, <boundary class>)`. This is where agents repeatedly
  re-run whole suites, so it is where time and tokens are saved.
- **Admission:** unchanged ADR 0006 — unreached checks are not owed; reached checks run in this run; carry now
  requires matching identity and states its boundary class (ADR B §4; whether `declared` carry is refused is R-5(ii)).
- **Certification and release:** no carry. Every check passes in the certifying run (closes reconciliation finding 4;
  [defect report](certification-carry-defect.md)).
- Optimization order (owner review E): (1) preserve valid evidence without false freshness; (2) reduce unnecessary
  invalidation and full-run escalation (finer checks, `complete` providers once measured); (3) sequence permitted
  incremental checks (§7.2); (4) anything more elaborate only after measurement.

### 7.2 Verification sequencing (what to run next)
Deterministic baseline, no model:
1. Candidates = owed checks (selection) ∪ checks the consumer declared `permitted` at this stage.
2. Order owed checks by ascending `c / p` — expected cost per detected failure — where `c` is the observed median
   duration in this environment and `p` the smoothed historical failure frequency of the check on changes reaching its
   inputs. For independent checks this minimizes expected time to the first failure (a standard sequencing result);
   correlation is handled in evaluation, not assumed away. `p` is a **ranking statistic, not a probability of
   correctness**: it says how often this check has been the one to fail, not how likely the change is to be right.
   - *Absent data* (no observations for the check in this environment): no `c/p`; the check keeps its configuration
     order, placed after ranked checks only if the consumer opts in, else the whole plan abstains (item 5).
   - *Sparse data*: `p = (failures + 1) / (runs + 2)` (Laplace) and `c` = median only with ≥ 5 observations, otherwise
     the configured `cost` class maps to a fixed default; both reported with their counts so the ordering's basis is
     visible.
   - *Correlated checks* (one failure implies another): the independence result does not hold; the planner does not
     model correlation, and E1 measures how much ordering gain survives it. A detected strong correlation is reported,
     never used to skip the dependent check.
   - Whatever the data, every owed check still runs; a bad estimate costs time to first failure, never assurance.
3. Before running anything, emit **gap actions**: an affected claim with `no-support`, or a new claim with no
   supporting unit, yields "author a test/contract/proof" — not "run more existing tests" (RFC §12 scenario 2).
4. Stop optional actions at the budget (ADR D); mandatory ones are never dropped, only reported as outstanding.
5. Abstain (return the plain ordered owed list) when cost or history is unavailable.

Ordering changes *when* a failure is seen, never *whether* an owed check runs. Durations needed for `c` are recorded
in a separate observation record, not in `result/v1`, to keep results deterministic.

### 7.3 Where an LLM could help, later
Only in ranking *permitted optional* candidates or proposing gap actions, with abstention, after the evaluation shows
benefit over §7.2 (RFC §11.3). Its output is `inferred` provenance.

## 8. Budgets and execution boundaries (summary of ADR D)

| Control | Enforceable by the CLI | Needs the agent runtime / execution environment |
|---|---|---|
| per-check timeout | yes (new `timeout` on a check) | — |
| only declared checks run through `dev-platform` | yes (already) | direct `cargo test`, `bazel test`, ad-hoc mutation tools are outside the CLI |
| cumulative action count / wall-clock per session | report only (a session ledger the CLI appends) | hard cap needs runtime hooks or a sandbox |
| model tokens | no | runtime accounting only |
| exploratory runs need authorization | yes for actions the CLI runs (refuse without a matching record) | otherwise runtime permission rules |
| credentials / runners | routing refuses (ADR 0005) | GitHub settings remain the enforcement |

## 9. Worked examples

### 9.1 Ordinary functional claim (Python project, no formal methods)
```toml
# consumer-owned declarations (format: R-2)
[[claim]]
id = "PARSE-001"
statement = "parse_config rejects any document with an unknown top-level key"
scope = "dev_platform.config.load; TOML input"
kind = "functional"
supported_by = ["config.loader"]
review_requirement = "maintainer review"

[[unit]]
id = "config.loader"
inputs = ["src/dev_platform/config.py", "schemas/config-v1.schema.json"]
evidence = ["check:unit"]
```
- Change edits `config.py`: `check:unit` identity `inputs` moves → `stale(inputs)`; claim support `not-established`
  until `unit` passes in this run; review stays current (statement unchanged).
- Change edits the claim's `statement`: review `stale(claim)`; claim not established even with green tests.
- New claim with no unit: `no-support` → closure `INCOMPLETE`; planner emits "author a test".
- No Lean, Verus or LLM involved; closure scope `all-active` at release, consumer's choice.

### 9.2 Security-sensitive formal claim (MCP-RE, projected)
- `THM-0074` "No unearned dispatch" (root; `supported_by` two units; `depends_on` four theorems) — projected with
  review `current`, units `current`.
- Unit `core.time_civil_from_days` (V2) carries two evidence items: `lean://core/time/civil_from_days_total` and
  `test://core/time/civil_from_days_extremes`. In the projection both are evidence of one unit; the Lean result's
  Charon/Aeneas/Lean identity is a `provider` component, not a core concept; the test is compensating evidence on the
  shipped code (`verification.toml` comment at the unit) — the model keeps both, it does not let the proof replace the
  test.
- A Verus failure in a supporting unit → `FAILED` closure via failed prerequisite, without the core knowing what
  Verus is.
- A toolchain pin bump → every unit `stale(environment)`; reviews unaffected; closure `INCOMPLETE` until a complete
  run re-establishes — identical to MCP-RE's own result on v0.18.0→v0.18.1.

## 10. RFC §12 scenarios against the model

| # | Scenario | Handled by |
|---|---|---|
| 1 | behaviour-preserving refactor | identity moves → `stale(inputs)`; sealed `consumes` can stop propagation only with an unchanged contract and a current review; full release still runs everything |
| 2 | new requirement, all tests green | `no-support` gap → `INCOMPLETE`; gap action |
| 3 | Lean model theorem vs Verus implementation proof | separate units/evidence; claim needs both via `supported_by`; runtime wiring evidence separate |
| 4 | performance change on new hardware | `stale(environment)` |
| 5 | database-dependent test unavailable | outcome `unavailable` → not `passed`; runner routing refuses silently substituting |
| 6 | negative mutation control | control evidence `detects` only its defect; attribution limitation recorded |
| 7 | large impact or changed verifier | identity `unknown` / platform change → everything owed; due-gate (ADR C) decides block vs declared release-due |
| 8 | non-formal Python project | §9.1 |
| 9 | proof/model statement weakened | claim fingerprint moves → review `stale(claim)` |
| 10 | agent exploration loop | ADR D budget → stop optional, report outstanding |

## 11. What is new, and how much

| Component | New code (estimate, Interpretation) | Depends on |
|---|---|---|
| L2 identity + bound carry + certification fix | small (one module, schema additive) | nothing |
| execution observation record (durations) | small | nothing |
| projection schema + validator + evaluator (L3) | medium (pure functions, ~MCP-RE `_review.py` scale) | ADR A |
| native declaration reader | small–medium | R-2 |
| planner baseline (L4) | small | evaluation result |
| budgets (timeouts, session ledger, exploration refusal) | small | ADR D |
| MCP-RE exporter | in MCP-RE, owned there | MCP-RE owner authorization |
