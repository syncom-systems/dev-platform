# Draft ADR A: General assurance model and read-only projection

Status: **Draft for owner review — not an ADR, unnumbered, not in the ADR index, not ratified.** Rev. 2 (owner review
C: argument semantics, item 4a). A number is assigned
only if the owner ratifies or accepts it as Proposed. Register entries: R-1, R-2, R-3, R-4, R-9, R-10, R-12, R-16.
Evidence: [reconciliation](../reconciliation.md); design: [proposal](../architecture-proposal.md) §2–§6, §9.

## Context
Dev Platform decides which declared checks a change owes and whether they passed; it has no notion of claims,
premises, reviews or assurance closure. MCP-RE implements those concepts, non-vacuously, for a security product, but
couples them to its registries, provers, GitHub workflows and vocabulary. Consumers that use only ordinary tests must
be first-class; MCP-RE must remain authoritative for its own assurance.

## Decision (proposed)
1. **Placement.** The assurance capability is a module of the Dev Platform package, exposed through the CLI and
   versioned JSON (ADR 0007). No service, database, plugin runtime or agent dependency.
2. **Core objects** are exactly: claim, root set, assurance unit, premise, review, evidence item (proposal §3.1).
   Consumer-specific attributes (severity, prover tiers, consequence text) live in `extensions` and are never
   interpreted by the core.
3. **Typed relations** `depends_on`, `supported_by`, `evidenced_by`, `premised_on`, `consumes`, `identity` are kept
   distinct (proposal §3.2). A build-graph edge may populate `consumes`/`identity`, never `supported_by`/`depends_on`.
4. **State axes and verdicts.** Outcome, applicability, claim assurance and scope completion are reported separately
   with closed vocabularies. A claim is *established* iff its argument is declared supported (§4a), its review is
   current, its support is established under its support form, every premise it rests on is accepted, and every
   `depends_on` claim is established (fixpoint). Closure for a declared scope at a gate is
   `UNDECLARED` (no roots or no active claim), `FAILED` (current counterevidence or failed prerequisite), `INCOMPLETE`
   (anything else not established, including empty, unknown, non-applicable-only or unresolved support) or `PASS`.
   A `PASS` record names the identities it was computed from.
4a. **Argument semantics — a deliberately small, explicit subset.** The core does not claim that conjunction is the
   semantics of every assurance argument. It supports exactly these structures and rejects or reports everything else:

   | Element | Representation | Rule |
   |---|---|---|
   | Conjunctive support (default) | `support = {form: "all", units: [...]}` | established iff the list is non-empty and every unit is current and passing |
   | Alternative strategies | `support = {form: "any-of", groups: [[...], [...]]}` — **name reserved, semantics not decided (rev. 3)** | always reported `INCOMPLETE(unsupported-form)`; never established, never `FAILED`, never coerced to `all` |
   | Prerequisite claims | `depends_on` | each must be established (fixpoint), independent of support form |
   | Premises / assumptions | `premised_on` (unit) or `premises` (claim); class `assumed / external-boundary / review-obligation` | an unaccepted premise (no current review of the premise) → `premise-unaccepted`; an established claim's record lists every premise it rests on — "established under P" is never reported as unconditional |
   | Human semantic review | review bound to the claim's statement digest **and** its argument digest (support form, units, premises, `depends_on`) | changing any part of the argument stales the review; the review is the judgement that the evidence, of whatever kind, actually bears on the statement |
   | Incomplete or unknown argument | `argument: "incomplete"` or `"unknown"`, or a support form the evaluator does not implement | never established; reported as `INCOMPLETE(argument-incomplete / unsupported-form)`, never coerced to `all` |

   Non-vacuity holds for every implemented form: an empty list, a list of only `not_run`/non-applicable/`unknown`
   items, or an unresolved reference never establishes support. Under `all`, a current `failed` unit makes the claim
   `FAILED` (current counterevidence).

   **Alternatives are reserved, not specified (rev. 3).** Rev. 2 proposed that a current `failed` item in *any* group
   makes the claim `FAILED`. That rule is withdrawn: it conflates evidence against the statement with a failed
   strategy (a measurement strategy that misses a threshold does not refute a proof of the same statement unless both
   bear on the same proposition), and it makes adding an alternative able to turn an established claim into `FAILED`.
   Which failures count as counterevidence across groups, how `unavailable` and `failed` differ in a fallback, and
   whether the result is monotone in added groups are open questions for a later decision, taken only when a consumer
   needs alternatives. Until then `any-of` is accepted syntactically and reported `unsupported-form`.

   **Evidence kinds stay distinct.** Each unit declares `kind ∈ {proof, test, measurement, analysis, control}`. The core
   does not rank kinds or treat one as implying another; the `PASS` record lists the kinds that established each
   claim. A formal theorem, an empirical measurement and a behavioural test thus remain different evidence; whether a
   kind is adequate for a statement is the reviewed argument's question, not the evaluator's. Model–implementation
   correspondence is itself a claim (item 9).

   The first evaluator implements `all` only and reports `any-of` as `unsupported-form`; it does not reject the
   document or reinterpret it. MCP-RE's model is the `all` subset with review bound to the claim fingerprint.
5. **Closure scope** (`roots` or `all-active`) and which gates require closure are consumer policy. The platform sets
   no default obligation.
6. **One contract.** The evaluator reads `dev-platform.assurance-projection/v1` only. Native declarations, when
   introduced, compile to the same document. Dev Platform owns the schema; a producer owns its export.
7. **Projected consumers.** For a consumer that produces its own projection (MCP-RE), Dev Platform recomputes and
   compares; disagreement is `projection-inconsistent`, never `PASS`; the consumer's verdict stays authoritative until a
   migration criterion (R-16) is met and the consumer owner approves.
8. **Reviews.** A native claim review is an `authorization/v1` record with subject kind `claim-review` bound to the
   claim fingerprint (and semantic digest where declared). No command creates a review on a reviewer's behalf.
   Reviewer-identity strength is reported. Status booleans on claims are rejected at load.
9. **Formal methods.** Provers are checks or providers; the core contains no prover names. Model/implementation
   correspondence is itself a claim.
10. **Terminology.** New text uses "tool closure" (ADR 0015) and "assurance closure" (this ADR); "release verification"
    (artifact) and "release assurance" (claims) are different records linked by digest.

## Consequences
- Ordinary consumers can adopt claims with unit/integration tests only; nothing requires Lean, Verus or an LLM.
- MCP-RE needs one exporter (its own change, separately authorized) to be evaluated; none of its gates change.
- A second interpreter of MCP-RE policy is avoided: Dev Platform reads state, not MCP-RE registries.

## Compatibility
Additive: new command, new schema, new `authorization/v1` subject kind (ADR 0013's record shape is the Proposed part).
No change to ADR 0004, 0006, 0007, 0015 semantics. Native declaration format deferred (R-2).

## Open questions on the argument model (owner, R-4)
- `any-of` semantics (rev. 3: reserved; see §4a): counterevidence across groups, `unavailable` versus `failed` in a
  fallback, monotonicity. Decided only when a consumer needs alternatives; no current consumer does (MCP-RE claims are
  conjunctive).
- Should an accepted `assumed` premise be allowed at the release gate, or must release closure list it as a blocker
  unless the consumer's release policy names it? (Recommendation: allowed, but listed in the `PASS` record.)
- Does the argument digest belong in the claim fingerprint (as MCP-RE's claim fingerprint does for its own fields) or in a separate digest?

## Alternatives rejected
A general assurance-case language (GSN/SACM-style nodes, defeaters, confidence arithmetic): no consumer needs it, and
it would make the evaluator a second interpreter of argument policy. Treating conjunction as universal without an
`incomplete` escape: forces consumers to misstate arguments that do not fit. Extracting MCP-RE tooling as the core (security vocabulary, provenance, authority move); parsing MCP-RE registries
directly (coupling, second interpreter); a separate package (no demonstrated boundary); a single green status (RFC §7.1).

## Owner decisions required
R-1 placement/authority; R-2 deferral of native format; R-3 projection ownership and the MCP-RE exporter request;
R-4 vocabulary; R-9 review records; R-10; R-12; R-16.
