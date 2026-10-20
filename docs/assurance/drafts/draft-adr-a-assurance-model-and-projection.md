# Draft ADR A: General assurance model and read-only projection

Status: **Draft for owner review — not an ADR, unnumbered, not in the ADR index, not ratified.** A number is assigned
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
   with closed vocabularies. A claim is *established* iff its review is current, every supporting unit is current and
   passing, and every `depends_on` claim is established (fixpoint). Closure for a declared scope at a gate is
   `UNDECLARED` (no roots or no active claim), `FAILED` (current counterevidence or failed prerequisite), `INCOMPLETE`
   (anything else not established, including empty, unknown, non-applicable-only or unresolved support) or `PASS`.
   A `PASS` record names the identities it was computed from.
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

## Alternatives rejected
Extracting MCP-RE tooling as the core (security vocabulary, provenance, authority move); parsing MCP-RE registries
directly (coupling, second interpreter); a separate package (no demonstrated boundary); a single green status (RFC §7.1).

## Owner decisions required
R-1 placement/authority; R-2 deferral of native format; R-3 projection ownership and the MCP-RE exporter request;
R-4 vocabulary; R-9 review records; R-10; R-12; R-16.
