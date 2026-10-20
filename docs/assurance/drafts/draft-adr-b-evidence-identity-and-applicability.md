# Draft ADR B: Evidence identity and applicability

Status: **Draft for owner review — not an ADR, unnumbered, not ratified.** It proposes *clarifications* of ratified
ADR 0006 §3, §4 and §6 and therefore needs explicit owner sign-off. Register entries: R-5, R-6, R-8, R-11.
Evidence: [reconciliation](../reconciliation.md) §3.2–3.3, §4.3–4.4, §6.1; design: [proposal](../architecture-proposal.md) §4, §7.1.

## Context
ADR 0006 §4 permits carrying `verified` "across a change that provably does not reach the check". The implementation
reads only `{id, state}` from a caller-supplied previous record (`engine.py:113`) and compares nothing else, so it
cannot prove non-reach. Certification requires every check `verified` (`engine.py:206`), and a check not defined at
`full` keeps its carried state there (`engine.py:129-130`), so certification can rest on an arbitrary file (by reading;
not executed). MCP-RE shows a sound alternative: evidence bound to a component-typed input fingerprint with
cause-typed staleness.

## Decision (proposed)
1. **Identity.** Every evidence item carries an identity digest over components `inputs`, `definition`,
   `environment`, `platform`, optional opaque `provider`, and `encoding` (proposal §4.1). `always` checks carry no
   reusable identity.
2. **Applicability.** `current` iff every component equals the previous item's; otherwise `stale(<cause>)`; any
   unreadable or missing component → `unknown`. `stale`/`unknown` items are history, never support.
3. **Carry (clarifies ADR 0006 §4).** "Provably does not reach" means *identity equal*. A previous record whose identity
   cannot be matched contributes nothing.
4. **Certification (clarifies ADR 0006 §6).** "All checks verified" means every check *passed in the certifying run*.
   Carried state never certifies. A check not defined at `full` is a certification blocker; `doctor` warns about it.
5. **Provider impact (scopes ADR 0006 §3).** When impact comes from a provider (fingerprints), a tracked path outside
   every read set is *unmapped* and selects every owed check, unless the consumer declares an explicit ignore list and
   the provider proves its read set covers every tracked path not ignored.
6. **Provenance.** Items record `declared / observed / measured / inferred`; only current `observed`/`measured` items
   establish support.
7. **Counterexample controls.** A control's evidence records `detects: {unit, defect_id}`, its attribution level
   (`test-identity | assertion`) and requires a current unweakened pass of the same control. A control's pass supports
   detection of its declared defect only.
8. **Read-set conformance** (glob `inputs` vs what a check actually reads) is measured in evaluation, not assumed.

## Consequences
- Development-loop evidence preservation becomes sound and usable by a planner.
- Certification can no longer depend on a supplied file; a configuration with pre-merge-only checks cannot certify
  (it could previously only through `--previous`).
- Over-invalidation is preferred to false freshness; granularity improves only by declaring finer checks or a provider.

## Compatibility
`result/v1` gains optional identity/applicability fields (additive) or moves to v2 at the owner's choice; 0.x minor
bump. Behaviour change only for callers relying on unbound carry. No known consumer (NGA, Dev Platform itself) has a
change check without `full`.

## Alternatives rejected
Keeping unbound carry (cannot support preservation or a planner); removing `--previous` (loses the only preservation);
a config invariant forcing `full` on every check (breaking, and not needed once certification ignores carry);
treating MCP-RE's implicit ignore as the generic default (fails open on unmapped paths).

## Owner decisions required
R-5 (clarification of §4), R-6 (clarification of §6), R-8 (scope of §3), R-11.
