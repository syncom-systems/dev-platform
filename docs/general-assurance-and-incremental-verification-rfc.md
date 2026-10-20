# RFC: General Assurance and Incremental Verification Architecture

> **Status:** Proposed architecture foundation / research charter. **Not an ADR, not ratified, and not implementation authorization.**
>
> **Date:** 2026-10-20
>
> **Home:** syncom-systems/dev-platform
>
> **Reference snapshots:** dev-platform [e548c6a8](https://github.com/syncom-systems/dev-platform/tree/e548c6a8eda0171726442e5874511806cba2b93f); mcp-re [8262c5fa](https://github.com/syncom-systems/mcp-re/tree/8262c5faad4c766513e473da90be135675a0c347).
>
> **Purpose:** Preserve the design rationale and define a constrained, reviewable basis for further investigation. Nothing in this RFC supersedes ratified ADRs, consumer policy, established CI gates, release verification, or owner approval.

## 1. Executive position

Dev Platform should investigate a reusable, domain-neutral **assurance capability** and a separate **incremental verification planner**. They should be grounded in the working evidence, review, and proof-dependency mechanisms of MCP-RE, but should not import MCP-RE's security-specific terminology or policies as mandatory concepts for all consumers.

An assurance system answers **what must hold**, **why it is believed to hold**, **on which assumptions and source/environment identities**, and **what remains unresolved**. A planner answers **what permissible verification action would be most useful next**, given that assurance state and the cost of development.

These are separate authorities. A planner, whether deterministic or LLM-assisted, cannot weaken requirements, fabricate evidence, self-approve claims, or decide that release verification is unnecessary.

The immediate goal is **documentation, existing-system reconciliation, and a read-only reference evaluation**. It is not to move MCP-RE code, implement a new optimizer, create a service, replace CI, or start automated mutation campaigns.

## 2. Why this work exists

### 2.1 The initiating failure

During an eight-issue epic, an engineering agent reportedly required **800–1,300 tool calls per issue**. Much of its activity consisted of self-directed mutation experiments outside the configured verification framework. This triggered the investigation.

These figures are an observed report, **not** an audited token-cost measurement. Tool calls, tokens, elapsed time, and useful information are different quantities. The architectural failure was that an agent could expand optional verification work without an explicit purpose, budget, authority, or stopping condition.

The objective is not to ban mutations or formal verification. It is to make meaningful verification **reusable, bounded, and accountable**. Registered negative controls may be essential evidence. Repeated improvised experiments with no defined new claim are not inherently valuable.

### 2.2 The existing investment

MCP-RE has already built a serious assurance system: claims with permanent identities, logical dependencies, verification units, versioned proof and test evidence, provenance and fingerprints, controlled assumptions, separate human semantic reviews, declared system roots, and assurance closure. Its formal lanes use Verus for supported Rust implementation proof and an extraction path from Rust through Charon/Aeneas to Lean. It also has test batteries, structural controls, measured evidence, and registered mutation probes.

Dev Platform is already a deterministic, language-independent development control plane. It has stages, change impact, declared checks and obligations, evidence state transitions, runner/toolchain identity, pinned releases, and a policy that agent instructions cannot replace executable enforcement.

**Conclusion:** reuse the concepts and demonstrated mechanisms; do not start with a greenfield proof database or a new agent that reads the entire repository on each checkpoint.

### 2.3 The generalization requirement

This initiative is no longer specific to a security product. It must apply to ordinary functional behavior, numerical correctness, data integrity, protocol compatibility, performance, reliability, availability, resource bounds, and security, using whichever verification methods actually fit each claim.

A project that uses only unit and integration tests should be a first-class consumer. Neither Lean nor Verus is a prerequisite for adopting the general model.

## 3. Optimization objective and boundaries

### 3.1 Three primary objectives

For a completed development increment, minimize the multi-objective vector:

**(total elapsed development time, total model-token expenditure, expected residual defect/conformance risk).**

We can write this informally as **minimize (T, K, R)**. This defines a Pareto problem, not a single magic score.

- **T** includes design, implementation, verification, diagnosis, retries, and rework; report wall-clock and compute time distinctly where necessary.
- **K** includes agent/model use for implementation, selecting verification, inspecting failures, diagnosing, and rework. Tool calls are a useful secondary indicator, not equivalent to tokens.
- **R** is residual risk that the delivered implementation violates a required contract. It is not directly measurable as a simple correctness percentage. We approximate it with historical defect outcomes, deliberately seeded defects, evidence gaps, missed defect-revealing checks, and explicit uncertainty.

**Delivered functionality and mandatory engineering obligations are constraints, not tradable bucket contents.** Doing no work uses almost no time/tokens but does not deliver the increment. Nor may a cheap result compensate for a missing mandatory proof or test.

Do not assume zero testing implies zero correctness, or that a green suite implies complete correctness. Tests provide observations about specified behavior; proofs establish propositions within stated models and assumptions; neither automatically finds omitted requirements.

### 3.2 What else to measure

Collect human interventions/attention, diagnostic delay, flakiness, test setup cost, resource utilization, maintenance overhead of the assurance system, and its own planning overhead. These may explain the main objectives without becoming mandatory additional optimization dimensions.

The objective concerns **the whole development loop**, not merely the milliseconds taken by a test. An early three-second focused test may prevent an hour of agent debugging and thousands of tokens; a redundant forty-minute suite may add little information at the same checkpoint.

### 3.3 Non-negotiable completion rule

**A release requires the consumer's complete, authoritative verification and assurance-closure obligations. This is never a choice offered to the development optimizer.**

A full run on a defined artifact/revision and the consumer's required semantic reviews are distinct from an intermediate, incomplete or scoped development run. A current full test run does not automatically discharge all review or assurance requirements. Dev Platform's release verification, certification, and owner acceptance must remain separate claims.

No optimization may turn unavailability, unknown impact, stale evidence, a skipped lane, or budget exhaustion into PASS.

## 4. Generic conceptual vocabulary

The following terms are proposed; precise names and schemas remain reviewable.

| Term | Meaning | Key distinction |
| --- | --- | --- |
| **Requirement** | Desired external behavior, constraint, or property for an increment/system | Consumer-owned; not inferred as authority from code |
| **Claim** | A reviewable proposition about behavior, conformance, quality, or another property | Not synonymous with a machine-checked theorem |
| **Argument** | Why the stated supporting evidence and premises justify a claim | A reference link is not itself a justified argument |
| **Assurance unit** | Bounded semantic/engineering responsibility with declared relevant inputs and evidence | Not automatically a file, crate, service, or test group |
| **Contract** | Defined interface behavior or invariant linking obligations between units | An intended contract is not proof of implementation |
| **Premise / assumption** | Condition on which an argument or proof rests, possibly outside its verification boundary | Explicit, attributable, and subject to review |
| **Evidence** | Particular proof check, test observation, measurement, review or other supported result | Must retain provenance, scope and validity |
| **Verification action** | Executable or authoring activity that can produce additional evidence | Costed; execution does not guarantee a pass |
| **Obligation** | Requirement for evidence/assurance at a defined stage | Independent of runtime cost |
| **Assurance closure** | Deterministic judgment that all obligations for the declared scope/gate are fulfilled | Not a metaphysical proof of zero bugs |
| **Checkpoint** | A development moment at which feedback may be useful | Worker stage/intent is a claim, not an established fact |

**Domain-neutral examples:**

- A parser rejects malformed input in a specified class (functional claim; tests, proof, fuzzing).
- A revoked delegation is denied (security claim; contract tests, proof, integration).
- A scheduler preserves a fairness bound under stated assumptions (correctness/reliability; model checking, tests).
- p99 latency remains under a threshold for a declared workload and environment (performance; measurement).
- Two language implementations conform to a protocol contract (interoperability; conformance tests and cross-implementation evidence).
- A state machine cannot enter an invalid state (formal claim; type/structural proof or formal verification).

An empirical performance claim should not masquerade as a timeless Lean theorem; a theorem about an abstract model should not masquerade as a proof of an unverified Python implementation.

## 5. Architectural foundation: deep modules and behavioral contracts

Deep modules have narrow, stable public interfaces and may contain substantial internal implementation. Assurance is most reusable when associated with **behavioral contracts at those interfaces**, not with individual changed lines.

Three complementary levels often apply:

1. **Internal invariant evidence:** focused checks/proofs of meaningful internal obligations; precise and often fast, but not every implementation detail deserves a test.
2. **Public interface contract evidence:** tests/proofs of externally promised behavior that can survive internal refactoring.
3. **Cross-unit composition evidence:** tests/proofs that independently correct units interact consistently; serialization, external systems, configuration, and actual runtime wiring can introduce defects invisible to local proofs.

The relationship is a **graph, not necessarily a tree**. One test may support several claims; one claim may require multiple independently scoped kinds of evidence. An interface contract can constrain invalidation propagation only after its applicability/refinement assumptions have been established. An unchanged claim statement **alone** never makes changed implementation proof valid.

Do not distort production architecture merely to create pretty proof units or smaller test-selection sets. Assurance boundaries should correspond to genuine semantic ownership.

## 6. Distinct graphs and typed edges

Maintain the following conceptual relationships separately; do not collapse them into a single generic dependency arrow.

1. **Logical claim graph:** claim A relies on claim B. This is logical reliance, *not* a call/import/build edge.
2. **Assurance/evidence graph:** an assurance unit or item of evidence supports a particular claim through an explicit argument with a stated scope.
3. **Impact and validity graph:** source, configuration, toolchain, specification, model, test-definition or policy input changes can invalidate specific evidence.
4. **Verification-action graph:** an executable action, with prerequisites/environment, is expected or known to produce specific evidence and has measured cost.

Bazel may supply declared build dependency information and runnable targets. It **cannot by itself** establish that a test asserts a requested behavior or that a logical theorem follows from another.

The following distinctions are strict:

- **Depends on code:** declared structural/build relationship.
- **Executes a location:** measured coverage in a particular execution/configuration.
- **Guards source structure:** a textual/structural condition is checked.
- **Detects a specific mutation:** a named control demonstrably fails for a named injected defect.
- **Asserts a behavior:** a test contains relevant observable assertions under defined preconditions.
- **Establishes a formal proposition:** a checked proof about the exact declared model/specification under its assumptions.
- **Establishes the intended system contract:** requires an argument connecting the required behavior, evidence, implementation and external assumptions.

None follows automatically from the preceding item. In particular, a test that guards changed source lines has not demonstrated detection of arbitrary behavior-changing mutations, nor established that an arbitrary behavior-preserving refactor is safe. A mutation rejected at one edit site is not evidence that every other mutation at that site would be rejected.

**Counterfactual controls must be discriminating.** The injected defect must reach and violate the intended property, and the test must fail on its own meaningful assertion, not merely crash in surrounding scaffolding. Coverage of an irrelevant branch is not defect detection.

## 7. Evidence semantics, identity, and historical reuse

### 7.1 Separate four questions

A general evidence model should report distinctly:

- **Execution outcome:** passed / failed / not run / unavailable (and meaningful non-applicability where declared).
- **Applicability/freshness:** valid for current inputs, historical, invalidated, or unknown.
- **Claim assurance:** review current? supporting evidence established? prerequisites established? outstanding premises?
- **Scope completion:** are all declarations and required root/system-level claims complete at the requested gate?

These states cannot safely be compressed into a single green light. MCP-RE's review currency, evidence establishment and root completeness are distinct. Dev Platform's existing check-state machine is not wrong; it answers a narrower question.

### 7.2 Provenance

Preserve the difference between:

- **Declared/claimed:** worker says “behavior-preserving refactor” or “new feature”; this is intent, not validation.
- **Observed:** specified command/inspection produced a recorded outcome.
- **Measured:** quantified observation with conditions and instrumentation.
- **Inferred:** reasoning from existing evidence, including semantic test matching.

Each claim of evidence must identify its authority and confidence limitations. An LLM's semantic inference cannot silently become a measured behavioral fact.

### 7.3 Evidence fingerprint

A reusable evidence identity must capture the inputs determining its validity, as appropriate to its kind, including:

- Exact relevant source snapshot and generated artifacts.
- Contract/specification/model revision and assurance-unit definition.
- Test/proof/measurement target, selection, actual assertions/probe definitions.
- Tool, solver, compiler, instrumentation, model extraction and runner identity.
- Build flags/features, configuration, fixtures, runtime dependencies and environment.
- Relevant premises, policies, trusted components, and measuring-lane implementation.

A content hash of *only the test file* does **not** validate prior coverage, mutation results or execution on changed production code. Test code can remain identical while execution paths and defect-detection behavior change.

Prefer deterministic, versioned fingerprints over a mutable “clean=true” marker. Conservative over-invalidation costs time but avoids false freshness. As the granularity is refined, prove the coverage of the actual measured dependency cone; do not shrink fingerprints by guesswork.

Historical evidence may still help plan the next action. **Historical usefulness is not current certification.** Record a prior result as historical rather than promoting it to current measurement. An unchanged contract is not by itself an unchanged implementation proof.

### 7.4 Assumptions and proof limits

Formal proof results must be tied to the *specific theorem*, model, assumptions, toolchain and implementation correspondence actually verified. A handwritten Lean theorem about a normative model is not proof of its Rust or Python implementation unless the refinement link is established. Verus covers supported executable Rust/specifications within a stated trusted computing base. The Charon/Aeneas/Lean extracted model has its own unsupported operations and axioms.

Explicitly account for unproved premises, axioms, external libraries, environment behavior and missing requirements. A model checker may prove the wrong property precisely; review the claim itself.

### 7.5 Admissibility and closure

No result with an unresolved identity, absent execution, unknown relevant change, missing proof target, or unreviewed changed claim may be used to satisfy an obligation as if it were current.

A declared system root cannot silently disappear because its proof is difficult. A missing declaration and a declared but unresolved gap are different states. Human approval should bind to the *specific reviewed claim and premises*, not be a mutable Boolean within the claim.

A valid full release closure requires every claim in the consumer's declared closure scope, including each required system-level/root claim, to have a non-empty, typed, resolvable support or obligation path. Such a path is necessary but never sufficient by itself: it must reach admissible, applicable evidence or an explicitly permitted and reviewed premise (for example an accepted assumption or established structural fact), and every applicable obligation must actually be satisfied. Empty, absent, unknown, exclusively non-applicable, or unresolved support leaves closure **INCOMPLETE**, never PASS. Closure also requires current claim/assumption reviews and the complete set of required assurance obligations, according to consumer policy.

## 8. Verification actions and incremental development

### 8.1 The action set must be extensible, but bounded

Examples include:

- Run a particular focused or interface test.
- Run a declared subsystem/integration battery.
- Check an existing Lean theorem or Verus implementation proof.
- Run a registered structural or mutation counterexample.
- Collect a required performance/reliability measurement.
- Determine whether an adequate test/proof exists for a new claim.
- Author the missing test/contract/proof (development work, not evidence until executed).
- Continue editing with an explicit list of outstanding obligations.

These are **not interchangeable** ways of proving “correctness”. Each has a declared output type, cost, prerequisites, and limits.

A fixed hierarchy of “focused/extended/all” might be an experimental baseline, but must not define the permanent architecture: the most informative pair of checks might come from two non-nested groups.

### 8.2 Sequential decisions

Verification selection is adaptive. After every useful outcome, update what is known and what remains owed. A focused failure can save diagnosis/rework; a pass can make another action more valuable; a missing behavioral assertion may mean the next step is writing a test rather than running all existing tests.

Suggested conceptual loop:

**Change/intent → affected claims/units → current valid evidence → outstanding mandatory obligations → permitted optional candidates → select next useful action → execute → record/update → repeat or stop.**

The optimizer does not control the mandatory obligations. Candidate generation and checking of chosen actions should be deterministic. An optional adviser (including Jev) may rank candidates within those boundaries and must support abstention/unknown and fallback.

Scores from language-model multiple-choice responses must not be treated as calibrated correctness probabilities without measurement. A fixed 0.6 threshold and simple top-option selection are not sufficient decision semantics.

### 8.3 Cost is end-to-end

Estimate a candidate's incremental wall-clock and resource cost **for its actual environment**, including parallelism, setup, cache state, database availability, retries, and diagnostic cost. Record uncertainty. A standalone test's historical “seconds” field is not necessarily the wall-clock price of a proposed suite.

The planner itself costs time and tokens and may be irrational for trivial actions. It must beat a simpler baseline on the whole development process, not merely produce interesting recommendations.

## 9. Verification governance and resource authority

The initiating failure requires governance **independently of any selection algorithm**.

Define three kinds of activity:

| Category | Governing principle |
| --- | --- |
| **Mandatory verification** | Required by declared policy at an explicit gate. Budget exhaustion does not waive it. |
| **Planned incremental verification** | Permitted/checkpoint-appropriate, within delegated execution authority and budget. |
| **Exploratory verification** | Explicitly scoped hypothesis, expected information, resources, stopping condition and separate authorization if exceeding allowance. |

Unregistered mutation campaigns do not become justified because the agent says they increase confidence. Registered probes and negative controls remain legitimate when they establish a specified fact.

Budgets should account for cumulative actions, not just the cost of each run. Report elapsed time, model tokens where observable, command/tool count, and experiment purpose. A hard token cap requires model/runtime accounting; a repository CLI cannot observe or enforce every agent token. Likewise, **unrestricted shell access defeats a CLI-only command budget**. Real enforcement needs an execution boundary or reduced delegated privileges. Prompts and agent skills are not hard controls.

On budget exhaustion: stop optional execution, preserve outstanding obligations, explain the blocker and request explicit renewed authority if necessary. Do not claim verification success.

Agents may propose evidence and make code/proof changes **only when an implementation task separately authorizes them**. They may not create approvals, alter assumptions, weaken gates, edit attestations, or silently broaden scope to obtain green status.

## 10. Verification stages and an unresolved policy conflict

Dev Platform currently defines edit, pre-commit, pre-merge and full, with ratified ADR 0006 declaring cost independent of obligation. Mandatory always/change checks must be available at pre-merge; unknown impact selects owed checks.

MCP-RE's select-units instead bounds scoped merge verification (currently default 20 affected units) and explicitly defers oversized, untrustworthy, or verification-platform changes to weekly/release complete runs. Both mechanisms make their obligations visible, but they are **not identical admission policies**.

This is an **owner-level architecture decision to reconcile**:

- Distinguish “mandatory now”, “mandatory before merge”, “mandatory before release”, and advisory/periodic requirements without weakening existing policy.
- A deferred check remains owed. A merge that has not fulfilled a mandatory pre-merge obligation must block, **unless the consumer's previously authorized policy explicitly defines a different admission contract**.
- A change touching the selection algorithm cannot be trusted to narrow its own scope.
- Unknown impact must not become an empty test selection. If an allowed stage cannot execute full affected coverage, report the unresolved obligation and its next mandatory gate.
- Full/release must execute **all required checks under the consumer's full policy**, including assurance closure where applicable. Intermediate cached evidence does not substitute for the required full execution when that policy requires a fresh complete run.

**Do not resolve this conflict incidentally inside an issue or by copying MCP-RE's select-units behavior into Dev Platform.** It requires a considered amendment or clarification to the existing ratified platform semantics and consumer compatibility analysis.

## 11. Proposed architectural responsibilities (not file layout)

### 11.1 Consumer owns meaning

Each repository declares its requirements, claims, assurance units, relevant environments, mandatory evidence, root/system claims, approval rules and gate thresholds. Security or safety criticality is consumer-owned. Dev Platform does **not** invent obligations from source files or agent assertions.

### 11.2 Generic assurance evaluator owns semantics

A reusable capability validates typed graph edges and declarations; computes current evidence applicability and transitive invalidation; reports claim/argument/assumption state and outstanding obligations; and evaluates required closure at the selected stage.

It must be usable without an LLM or formal prover installed. Proof engines are evidence producers, not intrinsic dependencies of the core.

### 11.3 Planner owns advice, not requirements

An incremental planner receives a read-only assurance view and deterministic permitted action candidates. It compares risk-relevant information value and cost, maintains uncertainty, and recommends the next action or abstains.

Start with a deterministic baseline. Add Jev or another model only if blinded real-world evaluation shows demonstrable incremental benefit over that baseline. No agent can waive a policy obligation.

### 11.4 Existing Dev Platform owns execution identity

Reuse pinned platform/toolchain releases, routing, execution adapters, result schemas and release trust. Introduce new interfaces only where the reconciliation shows a missing capability. Avoid duplicating policy engines or creating a generic plugin runtime without a concrete second implementation need.

### 11.5 MCP-RE remains authoritative during extraction

The initial integration should be a **read-only, versioned projection** of existing MCP-RE assurance claims, graph edges, proof/test evidence and closure state. Do not move or rewrite the existing security theorems, assumptions, CI gates or reviews.

First demonstrate identical conclusions on known snapshots, including deliberately invalidated evidence and incomplete roots. Replacement can be considered only after compatibility is measured and the consumer owner explicitly authorizes it.

## 12. Reference scenarios the general architecture must handle

1. **Behavior-preserving internal refactor:** worker claims refactor; affected implementation evidence is invalidated; stable exported contract *may* preserve unrelated evidence only where a valid correspondence/invalidation argument supports it. Run focused obligations first; full release remains required.
2. **New functional requirement:** existing tests might all pass while no test asserts the new behavior. Detect the evidence gap and propose authoring a test/contract/proof before treating the requirement as established.
3. **Security invariant:** a Lean theorem about an abstract authorization model and a passing Rust/Verus obligation have distinct scopes; runtime wiring and external boundary evidence remain necessary where assumed.
4. **Performance change:** source and test inputs may be unchanged while hardware, workload or runtime profile differs. Historical p99 measurements are not proof of the present profile.
5. **Database-dependent behavior:** coverage and outcomes exist only for the environment/revision actually executed. A test unavailable at a checkpoint is not marked passed; alternative runner routes must be authorized, not invented.
6. **Negative mutation control:** a specific weakened invariant is detected by a declared test. The result supports detection of that defect, not arbitrary edits to the same lines.
7. **Large impact or changed verifier:** incremental scope is uncertain or too broad. The planner does not return “nothing to do”; the unresolved obligation is surfaced and the governing admission policy decides whether work blocks or is explicitly deferred.
8. **Non-formal Python project:** unit/integration tests and contract declarations suffice for its chosen assurance policy. No Lean/Verus dependence is introduced.
9. **Proof/model change:** the theorem may still elaborate after its statement was weakened. Human semantic review and exact proof/model source identity must invalidate prior claim approval.
10. **Agent exploration loop:** proposed exploratory actions exhaust their budget. The agent stops optional experiments, reports unresolved knowledge and cannot relabel missing evidence as acceptable.

These scenarios should become the initial nonvacuity and compatibility fixtures for a later evaluation, not an excuse to construct a new large test harness during this research phase.

## 13. Existing implementation inventory and conflicts

### 13.1 Dev Platform (reference snapshot above)

- **Implemented/declared:** stages and obligations; fail-closed path impact; check state machine; check cost metadata (fast/slow, informational only); adapters for Bazel/Python/Cargo/exec; runner and toolchain identity; result records; full-stage certification; independent release-trust and owner-acceptance chain.
- **Ratified:** [ADR 0004, discovery versus declared requirements](https://github.com/syncom-systems/dev-platform/blob/e548c6a8eda0171726442e5874511806cba2b93f/docs/adr/0004-adapters-and-declared-requirements.md), [ADR 0006, verification semantics](https://github.com/syncom-systems/dev-platform/blob/e548c6a8eda0171726442e5874511806cba2b93f/docs/adr/0006-verification-semantics.md), [ADR 0007, agent independence](https://github.com/syncom-systems/dev-platform/blob/e548c6a8eda0171726442e5874511806cba2b93f/docs/adr/0007-agent-independence.md), [ADR 0015, closure identity](https://github.com/syncom-systems/dev-platform/blob/e548c6a8eda0171726442e5874511806cba2b93f/docs/adr/0015-closure-identity-and-trust-base.md).
- **Planning rules:** [ADR 0017](https://github.com/syncom-systems/dev-platform/blob/e548c6a8eda0171726442e5874511806cba2b93f/docs/adr/0017-release-lifecycle-and-planning.md) and [release management](https://github.com/syncom-systems/dev-platform/blob/e548c6a8eda0171726442e5874511806cba2b93f/docs/release-management.md): GitHub milestones/issues for execution, not release authority; verification distinct from owner acceptance.
- **Not identified as implemented:** a generalized claim/argument assurance graph or a calibrated optimizer of token/time/defect-risk trade-offs. Do not infer their absence from one README alone; the next study must trace the actual code and schemas.

### 13.2 MCP-RE (reference snapshot above)

- **Claim registry:** [theorems.toml](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/verification/policy/theorems.toml) has stable THM IDs, root claims, support units and logical theorem dependencies. It deliberately forbids duplicated path/test/policy fields.
- **Evidence model:** [verification README](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/verification/README.md) and [tools README](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/tools/verification/README.md).
- **Measured dependency closure:** [fingerprint engine](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/tools/verification/_fingerprint.py); includes proof and test sources, selection, lane identity, mutation probes and formal-model inputs.
- **Selection:** [select-units](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/tools/verification/select-units); compares fingerprints and prerequisite consumer closure, then bounds scoped verification.
- **Lean:** [extraction and proof model](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/verification/lean/README.md), [CivilFromDays theorem](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/verification/lean/theorems/CivilFromDays.lean), and [verify-lean](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/tools/verification/verify-lean). Verify actual activation/attestation for a snapshot, not just source presence.
- **Verus:** [verify-verus](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/tools/verification/verify-verus) uses pinned prover and whole-crate verification.
- **Review/closure:** [review](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/tools/verification/review) and [epic closure](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/docs/dev/epic-close.md) distinguish passing lanes, current reviews, established claims and root completeness.
- **CI:** [verification workflow](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/.github/workflows/verification.yml). Repository comments cite complete verification runs in the tens of minutes (including approximately 66–95 minutes in different measured contexts); these are historical, not guaranteed budgets.
- **Scope:** the security consequences, actual claims, theorem IDs, assumptions, selected toolchains and CI admission policy are consumer-specific. They must not become the general platform's normative defaults.

**Reuse and licensing:** MCP-RE source is Apache-2.0; Dev Platform is MIT. This does not prevent compatible reuse, but any actual code move requires retained copyright, license/NOTICE obligations, provenance and owner-reviewed compatibility. Reusing an idea is not the same action as copying a file.

## 14. Evaluation before optimization authority

**Hypothesis:** preserving a reliable contract/evidence graph will reduce repetitive agent rediscovery and permit cheaper incremental checks with no unacceptable degradation in defect detection or required assurance.

We need evidence. Compare, on fixed unseen changes and under the **same allowed obligations**:

- **Baseline A:** current Dev Platform / consumer's declared selection and gate behavior.
- **Baseline B:** a simple deterministic selection policy over the same generated assurance graph.
- **Candidate C:** an assurance-aware sequential deterministic planner.
- **Candidate D (only if warranted):** optional Jev/LLM ranking over validated deterministic candidates.

A hand-curated reference can diagnose information gaps but is not an achievable automated baseline.

Measure actual end-to-end time, model tokens where available, planning overhead, repeated tool calls, outstanding evidence gaps, missed defect-revealing checks, delay-to-detection, diagnostic/rework cost, and false or stale “established” conclusions. Preserve all mandatory gate outcomes in each comparison. Include behavior-preserving refactors, new behavior, proof edits, integration boundaries, and adversarial negative controls.

Historical replay is useful but cannot reconstruct every counterfactual agent behavior. Follow with **shadow-mode** recommendations on real changes, without affecting actual verification. Use holdout examples; do not optimize a model on the same 16 cases repeatedly and claim generality.

**Reject a proposed optimization** if it makes existing mandatory gate outcomes less strict, produces false current evidence, misses a known important defect without justified policy, or costs more than it saves over the complete development loop. Improved test counts or raw coverage alone are not a success criterion.

## 15. Architecture and governance decisions still open

The following are *questions for owner review*, not invitations for the agent to pick convenient answers:

1. **Contract surface:** minimal versioned, read-only projection of claims, support, premises, evidence identity and outstanding obligations; how to avoid duplicating MCP-RE authority.
2. **General evidence vocabulary:** which types and admissibility policies are core versus consumer-defined; what precise verification statuses are needed.
3. **Stage/deferral policy:** how to reconcile ADR 0006 with MCP-RE's bounded merge-selection behavior without changing either silently.
4. **Freshness and granularity:** valid dependency closures per evidence kind, thresholds for conservative invalidation, and project-specific evidence providers.
5. **Formal methods boundary:** how proofs and extracted models enter generic evidence without requiring Lean or Verus in every consumer.
6. **Review and acceptance:** how human claim review, release assurance and owner acceptance remain independent.
7. **Budget authority:** what is enforceable with current agent/runtime tools versus merely reportable, and which exploratory actions require approval.
8. **Cost model:** empirical wall-clock distributions, setup costs, token accounting availability, and how to handle correlated detection and uncalibrated uncertainty.
9. **Deployment shape:** module inside existing Dev Platform package versus separate package/repository only if a real independently versioned boundary is demonstrated.
10. **Migration criterion:** equivalence, negative controls, source provenance, compatibility and license obligations before any MCP-RE gate is replaced.
11. **Meaning of a full release run:** precise consumer-owned coverage, independence and assurance-closure requirements; never implicitly weakened by reused intermediate evidence.
12. **Agent interoperability:** CLI/JSON contract independent of Claude Code or any other particular agent, including non-agent execution.

For each decision, the follow-up study should give concrete alternatives, actual source evidence, risks, and a recommended owner decision. Unsupported guesses should be labeled as such.

## 16. Work sequence and requested documents

**Phase 0 — This RFC.** Preserve intent and boundaries. Its review does not authorize code changes.

**Phase 1 — Existing-system reconciliation.** Read the relevant code, schemas, tests and ratified ADRs at pinned revisions; produce a traceable mapping of Dev Platform and MCP-RE concepts, overlap, contradictions and gaps. Explicitly distinguish documentation assertions from executed behavior.

**Phase 2 — Decision-ready ADRs.** Draft, do not self-ratify, a small set of ADRs covering (a) general assurance graph, (b) evidence identity/validity, (c) stage and obligation semantics, (d) optimizer/agent authority and budgets. Consider a separate packaging ADR only if material.

**Phase 3 — Reference evaluation design.** Define read-only compatibility fixtures and exact acceptance criteria for comparing existing MCP-RE behavior with the proposed general representation. Design a deterministic planner baseline using historical evidence.

**Phase 4 — Owner decisions.** Ratify or reject ADRs; decide whether a bounded implementation epic is warranted and which consumer can pilot safely.

**Phase 5 — Implementation, only under subsequent authorization.** Begin with additive, read-only integration; preserve existing gates; run parallel comparisons and negative controls; migrate a gate only after demonstrated equivalence and explicit consumer approval.

This follows Dev Platform's existing GitHub-native milestones/issues/PRs **once architecture is settled**. Planning records, green workflows and merged PRs never substitute for the independent release verification and authorized owner acceptance already required by the platform.

## 17. Charter for the next research agent

### Authorized

- Read public Dev Platform and MCP-RE source, policies, test definitions, schemas, design records and relevant CI results; record exact revision and file links.
- Critique this RFC for contradictions with executed source and ratified policies; report corrections with supporting evidence.
- Write the **reconciliation study**, a **decision register**, and **draft** ADRs for owner review.
- Define a **read-only** reference evaluation: its candidate data, negative controls, measurement plan and stop conditions. Propose experiments but **do not execute any new experiment**, however cheap or bounded, without separate explicit authorization naming permitted actions, resource limits, and how outputs may be used. Inspection of existing source, recorded results and historical evidence is permitted.
- Escalate unresolved policy, correctness, ownership or licensing decisions instead of inventing authority.

### Not authorized by this RFC

- Do not change Dev Platform or MCP-RE executable code, CI, release policies, requirements, reviews, attestations, assumption registries, proofs or tests.
- Do not move code, invent an agent framework, create a database/service, or make the planner authoritative.
- Do not create implementation issues or a release milestone from this RFC alone.
- Do not execute new experimental test, fuzzing, mutation, model-checking, proof-generation, or benchmarking runs, **including bounded low-cost runs**, without separate explicit authorization. An authorized experimental result remains exploratory and cannot automatically satisfy a current assurance obligation; its admissibility must be established through the applicable evidence policy.
- Do not mark missing evidence current, downgrade mandatory checks, skip complete release verification, or grant agents new execution permissions.
- Do not assume a design is ratified because this document records it.

### Expected outputs and stopping condition

Produce an inspectable architectural reconciliation with:

1. A claim-by-claim **observed/proposed/unresolved** classification and source citations.
2. A minimal generic data model and typed-edge model, with explicit examples from one non-security and one security assurance claim.
3. A mapping from MCP-RE's current artifacts to a read-only Dev Platform representation, naming information that cannot be represented.
4. Compatibility and nonvacuity cases, including changed tests, changed proof model, stale review, omitted result, false mutation attribution and unknown impact.
5. A decision register for the owner and ADR outlines; clear statement of what existing guarantees must not change.
6. An evaluation plan with numerical cost/detection metrics, baseline strategies and a strict exploratory budget proposed for separate approval.

**Stop at that boundary.** Do not start building the architecture, generating implementation tickets, or running a large experiment merely because another step is imaginable.

## 18. Criteria for reviewing this RFC

The foundation is ready for owner consideration when it:

- Uses domain-neutral vocabulary applicable to functional, formal, empirical, performance and reliability assurance.
- Explicitly separates consumer-owned requirements, assurance evaluation, planning advice, execution and governance.
- Preserves the three-bucket objective with delivered-functionality and mandatory-gate constraints.
- Makes evidence freshness and proof/model correspondence precise; does not equate execution, assertion, mutation detection and proof.
- Retains full release verification and independent owner acceptance.
- Acknowledges and does **not silently resolve** the ADR 0006 versus MCP-RE merge-deferral conflict.
- Identifies reusable source machinery rather than mandating a new implementation.
- Constrains agent autonomy and explicitly recognizes what cannot be enforced with unrestricted shell/model access.
- Supplies executable counterexamples and evaluation criteria for a later, bounded experiment.
- Is useful to a future agent **without requiring access to the original conversation**.

---

## Reference pointers

- Dev Platform [architecture](https://github.com/syncom-systems/dev-platform/blob/e548c6a8eda0171726442e5874511806cba2b93f/docs/architecture.md), [verification model](https://github.com/syncom-systems/dev-platform/blob/e548c6a8eda0171726442e5874511806cba2b93f/docs/verification-model.md), [release management](https://github.com/syncom-systems/dev-platform/blob/e548c6a8eda0171726442e5874511806cba2b93f/docs/release-management.md) and [consumer integration](https://github.com/syncom-systems/dev-platform/blob/e548c6a8eda0171726442e5874511806cba2b93f/docs/consumer-integration.md).
- MCP-RE [formal verification overview](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/verification/README.md), [theorem/proof layers](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/docs/verification/03-theorem-and-proof-layers.md), [theorem registry](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/verification/policy/theorems.toml), [theorem ratification](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/verification/reviews/packets/theorem-architecture-ratification-2026-08-31.md), [tools](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/tools/verification/README.md) and [epic close](https://github.com/syncom-systems/mcp-re/blob/8262c5faad4c766513e473da90be135675a0c347/docs/dev/epic-close.md).
- Assurance-case terminology: ISO/IEC/IEEE 15026-2 (assurance case) and claims–arguments–evidence approaches are *conceptual references*, not automatically required compliance or tooling.

**Document authority reminder:** This is a design input and constrained research charter, not an assurance attestation, an executable policy, a ratified architecture decision, or approval to modify any consumer gate.
