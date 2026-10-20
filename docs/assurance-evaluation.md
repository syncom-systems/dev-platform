# Assurance evaluation (prototype)

`dev-platform assurance evaluate --projection FILE [--json]` evaluates engineering claims and their evidence from a
read-only [`dev-platform.assurance-projection/v1`](../schemas/assurance-projection-v1.schema.json) document and prints
a [`dev-platform.assurance-evaluation/v1`](../schemas/assurance-evaluation-v1.schema.json) record. The same function
is `dev_platform.assurance.evaluate(doc)` after `validate(doc)` returns no problems.

**Status.** A bounded prototype of [draft ADR A](assurance/drafts/draft-adr-a-assurance-model-and-projection.md),
which is **not ratified**. The owner authorized three of its choices for this prototype only: placement in this
package (R-1), one versioned read-only projection owned by Dev Platform (R-3), and conjunctive support only (R-4).
Nothing else in draft ADR A is implemented or decided by this command.

**Authority.** The record says `authority: informational`. A `PASS` satisfies no admission, certification, release
or owner-acceptance obligation; nothing in Dev Platform reads it. The command runs no check, test or proof, writes
nothing, and decides nothing about which verification may be skipped. The exit code is 0 for `PASS`, 1 for any other
verdict, 2 for a document it cannot read.

## What it reads

| Object | Fields | Notes |
|---|---|---|
| claim | `id`, `statement_digest`, `argument` (`declared / incomplete / unknown`), `support`, `depends_on`, `premises`, `review` | `support = {form: "all", units: [...]}` is the only implemented form |
| unit | `id`, `evidence`, `premises` | every evidence item of a unit must support it |
| evidence item | `id`, `kind` (`proof / test / measurement / analysis / control`), `outcome` (`passed / failed / unavailable / not_run`), `provenance` (`observed / measured / declared / inferred`), `applicability` (`current / stale / unknown`), `cause`, `boundary` (`complete / declared / unknown`), `identity` | outcome and applicability are the producer's report; the evaluator does not recompute or authenticate them |
| premise | `id`, `statement_digest`, `class` (`assumed / external-boundary / review-obligation`), `review` | accepted (review `current`) iff its review is bound to its current statement digest |
| scope | `closure` (`roots / all-active`), `roots` | `roots` covers the roots and everything they `depends_on` |
| `producer_verdicts` | per-claim state, closure verdict | compared with the recomputation, never trusted |

Fields outside the schema are refused, including status booleans such as `established`. `extensions` objects are
carried and never interpreted. A document of another schema version is refused, not read as v1.

## How it decides

Four things are kept apart: an item's **outcome** (did the action pass), its **applicability** (does the result still
apply), a claim's **establishment**, and the scope's **closure**.

- An item **supports** iff `passed`, `current` and `observed`/`measured`. A `current` item with an `unknown`
  boundary or no `identity` is treated as `unknown`. A `failed` item that is current and observed is
  **counterevidence**. Everything else (`not_run`, `unavailable`, stale, unknown, declared or inferred) supports
  nothing and refutes nothing.
- A claim is **established** iff its argument is `declared`, its support form is `all` with a non-empty list of
  resolvable units that are all established, every premise it rests on (its own and its units') is accepted, its
  review is current, and every `depends_on` claim is established (least fixpoint; a cycle is never established).
- The review is **current** iff its `encoding` is `dev-platform.assurance-argument/1`, its `statement_digest` equals the
  claim's, and its `argument_digest` equals `assurance.argument_digest(claim)`: a digest of the argument marker,
  support, premises and `depends_on`. Changing any of them stales the review.
- A claim with a counterevidence unit is **failed**; a missing tool (`unavailable`) never fails a claim.
- `any-of` and every other form are `unsupported-form`: never established, never failed, never treated as `all`.
- Closure: `UNDECLARED` without a scope, without claims, or with empty roots; `FAILED` if a claim in scope is failed;
  `INCOMPLETE` if any is not established or a root does not resolve; otherwise `PASS`. A `PASS` lists its `basis`:
  claims, premises, evidence kinds, boundary classes and identities.
- If `producer_verdicts` disagree with the recomputation, `consistency` is `projection-inconsistent` with each
  disagreement, and a recomputed `PASS` becomes `INCOMPLETE` (`recomputed_verdict` keeps the computed value).

Every blocker names its claim and, where relevant, the unit or premise and a reason code.

## Limits

The producer's outcomes, applicability and boundaries are taken as reported: the evaluator does not authenticate the
producer or show that a `declared` boundary contains everything a check reads; a `PASS` resting on `declared`
boundaries says so in its basis. Native claim declarations, other support forms, release-due obligations and any
MCP-RE exporter are not part of this prototype. Its synthetic tests are no evidence of agreement with MCP-RE's own
evaluator (evaluation plan E1–E4 have not run).
