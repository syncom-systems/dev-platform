# Draft ADR B: Evidence identity, applicability and certification

Status: **Draft for owner review — not an ADR, unnumbered, not ratified.** Rev. 2 (owner review A, B, F, G). It
proposes *clarifications* of ratified ADR 0006 §3, §4 and §6 (§6 below lists which). Register entries: R-5, R-6, R-8,
R-11. It does not introduce release-due obligations (draft ADR C) or execution observations (draft ADR D, R-18).
Evidence: [reconciliation](../reconciliation.md) §3.2–3.3, §4.3–4.4, §6.1; [defect report](../certification-carry-defect.md);
design: [proposal](../architecture-proposal.md) §4, §7.1.

## Context
ADR 0006 §4 permits carrying `verified` "across a change that provably does not reach the check". The implementation
reads only `{id, state}` from a caller-supplied previous record (`engine.py:113`) and compares nothing else, so it
cannot prove non-reach. Separately, certification accepts carried state from that record for a check not run at
`full` (defect report; by reading, not executed).

Binding evidence to a digest of its inputs is necessary but not sufficient. **Equal digests over an incomplete input
set do not establish that evidence still applies.** A declared glob can omit a file the check reads; a Bazel-label
read set can omit a non-Bazel test body (MCP-RE F-1); a declared V0 `paths` list can omit a helper (F-2). Replacing
unbound carry with a fingerprint that silently trusts such boundaries would make false freshness harder to see, not
rarer. This draft therefore makes the *trust in the boundary* an explicit, reported part of identity.

## Decision (proposed)

### 1. Identity
Every evidence item carries an identity digest over components `inputs`, `definition`, `environment`, `platform`,
optional opaque `provider`, and `encoding` (proposal §4.1), plus the run's `revision`. `always` checks carry no
reusable identity: they are owed at every admission (unchanged ADR 0006).

### 2. Boundary class
Each identity records how its `inputs`/`provider` component was bounded. Closed vocabulary:

| Class | Meaning | Who may assert it | Examples |
|---|---|---|---|
| `complete` | the read set is known to contain everything the check's outcome can depend on (measured by a hermetic or sandboxed execution, or a conservative over-approximation such as "every tracked file") | a mechanism, never a declaration; the record names the mechanism | a digest of every tracked file; a provider whose read set was *measured* under sandboxing. No check in either repository uses one today |
| `declared` | the read set is what someone declared; nothing verifies it covers what the check reads | consumer configuration | Dev Platform `inputs` globs; MCP-RE V0 `paths`; MCP-RE Bazel-label closure for lanes with non-Bazel inputs |
| `unknown` | no read set, or one that could not be computed | — | missing provider output, unreadable component |

No component is classed `complete` in either repository today. Nothing in this investigation establishes read-set
completeness for any check; that requires the measurement in evaluation step E4.

### 3. Applicability (current vs historical)
For each evidence item, relative to the current run:
- **`current`** iff every component digest equals the previous item's **and** the boundary class permits reuse at the
  gate in question (§4). Only `current` items can be carried or support a claim.
- **`stale(<cause>)`** iff any component differs; cause = first differing component. Never support.
- **`unknown`** iff any component is unreadable, the class is `unknown`, or the previous record is not a valid,
  identity-bearing `result/v1` record for this project. Never support. Reported as uncertainty, not as stale.
- **historical**: every `stale`/`unknown` item and every item from another revision remains visible for planning and
  diagnosis, labelled historical; it never discharges an obligation.

### 4. Preservation, invalidation and uncertainty by gate

| Gate | `complete` boundary, digests equal | `declared` boundary, digests equal | any digest differs | `unknown` |
|---|---|---|---|---|
| development (`edit`, `pre-commit`) | carry as `current` | carry as `current (declared)`; report the class | `stale(cause)`, re-run if owed | `unknown`, re-run if owed |
| admission (`pre-merge`) | carry (this is "provably does not reach", ADR 0006 §4) | **today's behaviour retained**: carry as `current (declared)`, with the class in the result | `stale(cause)` → owed | treat as reached → owed (fail closed, ADR 0006 §3) |
| certification (`full`) | **no carry** | **no carry** | — | — |

Admission with `declared` boundaries is no weaker than today: ADR 0006 selection already trusts the same globs. The
change is that the result now *says* the carry rests on a declaration, so it can be audited and measured (E4).
Whether admission should refuse `declared` carry altogether is owner decision **R-5(ii)**; the recommendation is to
keep it until E4 measures how often globs under-approximate, because refusing it makes every check owed on every
admission that passes `--previous` (no consumer passes it today).

### 5. Certification (clarifies ADR 0006 §6)
"All checks verified" means **every configured check passed in the certifying run**. Carried state, of any boundary
class, never certifies. A configured check not defined at `full` is a certification blocker; `doctor` warns about it.
This is the corrective option (a)/(d) of the defect report and can ship independently of §§1–4.

### 6. Provider impact (scopes ADR 0006 §3)
When impact comes from a provider, a tracked path outside every read set is *unmapped* and selects every owed check,
unless the consumer declares an explicit ignore list **and** the provider's read set is `complete` for every tracked
path not ignored. Today that proof does not exist, so the rule reduces to "unmapped = owed".

### 7. Provenance
Items record `declared / observed / measured / inferred`; only current `observed`/`measured` items establish support.
(Provenance of the *outcome*; distinct from the boundary class of the *identity*.)

### 8. Counterexample controls
A control's evidence records `detects: {unit, defect_id}`, its attribution level (`test-identity | assertion`) and
requires a current unweakened pass of the same control. A control's pass supports detection of its declared defect only.

## Which parts clarify and which amend ADR 0006
| Element | Relation to ADR 0006 | Why |
|---|---|---|
| §5 certification = passed in this run | clarification of §6 (R-6) | §6's "all checks verified" admits both readings; this picks the one consistent with §4 |
| §1/§3 carry requires matching identity | clarification of §4 (R-5) | "provably does not reach" cannot be satisfied by an unbound record |
| §4 admission carry on `declared` boundary | none — retains present semantics, reported | — |
| §4 refusing `declared` carry at admission (if the owner chooses R-5(ii) = refuse) | amendment of §4 (stricter) | narrows what "provably" admits today |
| §6 unmapped provider paths owed | scope statement of §3 (R-8) | extends the existing fail-closed rule to provider impact |
| `doctor` warning, boundary class reporting | none | diagnostic only |

## Consequences
- False freshness from an incomplete boundary is no longer hidden: every carried item states its boundary class.
- Development-loop preservation becomes usable by a planner, which must treat `declared` carry as weaker evidence.
- Certification can no longer depend on a supplied file.
- Over-invalidation is preferred to false freshness; granularity improves only by finer checks or a `complete` provider.

## Compatibility
`result/v1` gains optional identity, boundary-class and applicability fields (additive) or moves to v2 at the owner's
choice; 0.x minor bump. Behaviour change: (i) certification as in §5; (ii) a `--previous` record without matching
identity contributes nothing. No known consumer relies on either.

## Alternatives rejected
Keeping unbound carry; removing `--previous` (loses the only preservation); a config invariant forcing `full` on every
check (breaking, and unnecessary once §5 holds); trusting any fingerprint match as `current` regardless of boundary
(reproduces F-1/F-2 at platform level); MCP-RE's implicit ignore as the generic default (fails open).

## Evidence required before ratification
- §5: the defect reproduction (defect report §9.1) — confirms or refutes the motivating finding.
- §2–§4: none for the rules themselves; E4 (read-set measurement) is needed before any boundary is classed `complete`
  or before R-5(ii) is decided on evidence.

## Owner decisions required
R-5 (i) identity-bound carry as a clarification; (ii) keep or refuse `declared` carry at admission. R-6 (certification;
may be decided alone, first). R-8 (provider scope of §3). R-11 (controls).
