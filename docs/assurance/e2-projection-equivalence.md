# E2: MCP-RE projection equivalence (evaluation report)

> **Status:** evaluation output for owner review, informational. Evaluation plan step E2 only
> ([evaluation plan](evaluation-plan.md) §8). No ADR is ratified or changed, no gate, policy, review, attestation or
> MCP-RE file is touched, and nothing of MCP-RE was executed. E1, E3, E4 and any exporter are not started.

## Answer first

**The current generic evaluator cannot reproduce MCP-RE's three committed closure conclusions from committed data.**
On a faithful projection of each target it reports `INCOMPLETE` and `projection-inconsistent` (the record says `PASS`).
The obstacle is **missing data** first and **mapping loss** second, not the generic closure semantics:

- MCP-RE's evidence axis rests on the run's attestation store, which MCP-RE deliberately does not commit
  (`_closure_record.py`: "the attestation store it was derived from is not persisted"). No per-unit evidence outcome
  exists in any committed file, so no evidence item can be projected without inventing it.
- MCP-RE's reviews bind MCP-RE identities (theorem fingerprint, semantic review digest, owner-approval ledger), which
  v1 cannot express; the converter carries them under a foreign encoding that v1 reports `incompatible`.

What *could* be recomputed independently from committed files agrees with MCP-RE on every item at all three targets:
133/133 theorem fingerprints, the review-ledger identity, the record's own digests, unit/theorem/root sets, and the
review axis of all 133 theorems on every part that does not need source-tree fingerprinting. That is agreement on
**identities and review bookkeeping**, not on the closure verdict. No PASS was reproduced, and none was manufactured.

## 1. Revisions

| Item | Revision |
|---|---|
| Dev Platform evaluator | `main` @ `4d5272a9619ff27ad8ce6f56b354f7abdcb4d722` (PR #149 merged); evaluator unchanged by E2 |
| MCP-RE baseline | `syncom-systems/mcp-re` @ `8262c5faad4c766513e473da90be135675a0c347` (fixed; not advanced) |
| Closure records | `verification/closures/<target>.json` at the baseline. Each is byte-identical to the copy in the later trees that hold it (git blob ids below) |
| Per-target data | each target's **own** revision: `verification/policy/{theorems,assumptions,verification}.toml`, `verification/reviews/{specification,assumption}/*.json`, `docs/security/owner-approvals-*.jsonl` |
| MCP-RE semantics read | `tools/verification/{assurance-closure,review,_review.py,_fingerprint.py,_closure_record.py,_approvals.py,_premise.py,_registries.py}`, identical blobs at all three targets (e.g. `_review.py` `ad542d33`, `_fingerprint.py` `37b520fa`) |

| Target | Closure record (git blob / sha256) | Inputs | Input-manifest digest¹ |
|---|---|---|---|
| `4e3ffbb630ab49109a30961275217734a705a212` (v0.18.1) | `556f7cca` / `c78d6a30…7b02082` | 229 | `4072664f…13cab4d5` |
| `9dab7082f7fa02dbaf6024fde9ba3556ed3ad2e2` | `ce510eeb` / `f7746d73…dd3ac7d4` | 228 | `4044d317…9f627d685f` |
| `ffeafb22c3b3c8299406a79f9866b079e1f40bf1` (v0.18.0) | `baa4eec4` / `8dad5cfe…1432f6d0e5` | 228 | `959ca560…07a7467eba` |

¹ `records.canonical_digest` of the `sources` list (path, revision, sha256, git blob id per file) embedded in each
projection. `theorems.toml` `aa750af6` and `assumptions.toml` `83bb920c` are the same blob at all three targets;
`verification.toml` is `8333635d` at 4e3ffbb6 and `9cf35709` at the other two. Every fetched blob was checked
against its git object id before use.

Run identity in the records (not verified: no CI log or artifact was read):

| Target | Run | Evidence commit | Note |
|---|---|---|---|
| 4e3ffbb6 | 39060691189 | `b234587c` | not in the baseline's history; same tree (`4de286b3`) as the target |
| 9dab7082 | 38672416934 | `ffeafb22` | same run as ffeafb22; the two records carry identical unit and theorem digests |
| ffeafb22 | 38672416934 | `ffeafb22` | |

So the three targets hold **two** distinct identity states, not three.

## 2. Source-data inventory

| Concept | MCP-RE source | Status in committed data |
|---|---|---|
| Closure verdict | record `verdict`, `roots.verdict`, `counts` | **observed** (assertion; only a PASS is ever recorded) |
| Closure scope | `assurance-closure.evaluate`: every active theorem on three axes AND every declared root complete | **derivable** (source) |
| Declared roots | `theorems.toml root_theorems`; record `roots.declared` | **observed**, equal (12) |
| Active claims | `theorems.toml` entries without `replaced_by` | **derivable** (133; none deprecated), equal to the record |
| Claim dependencies | `depends_on` | **observed** (165 edges; acyclic; all resolve) |
| Unit identities | `verification.toml [[unit]]`; record `units` (fingerprints) | ids **observed** (308, equal); fingerprints **observed only as the record's assertion**, not recomputable without fingerprinting the source tree (excluded) |
| Unit outcomes | run attestation store (`attest` over the run's evidence) | **not determinable**: never committed |
| Evidence freshness / applicability | `_graph.derive_unit_state` over attestations at full unit fingerprint | **not determinable** |
| Evidence kinds | unit `evidence` refs (`test://`, `mutation://`, `structural://`, …), `evidence_class` | **observed as declarations** (588 refs); no result attached |
| Review currency, claim part | spec review `reviewed_fingerprint` + `components` vs theorem fingerprint | **derivable** (fingerprint depends on `theorems.toml` only) |
| Review currency, semantic part | `review_digest` vs `_fingerprint.review_digest` | claim/dependency/requirement/premise parts **derivable**; `supporting_semantics` **not determinable** without unit fingerprints, so compared with the record's value |
| Ledger backing | `_approvals.ledger_state` over `owner-approvals-*.jsonl` | **derivable**; ledger identity **derivable** |
| Premises | review record `review_components.premises`; assumption entries; assumption reviews | digests and reviews **derivable**; closure membership only **partly** (unit-scoped premises; boundary-attached ones need source analysis) |
| Premise discharge | `discharging_event` (9 entries) | observed; not used by MCP-RE's closure condition |
| Boundaries / provenance | unit `paths`, `governing_boundaries` (fingerprint component) | not determinable without fingerprinting |
| Run completeness | record `run.event` (`workflow_dispatch`), bundle `scope`/`aggregate` | event **observed**; bundle **not committed** |

Nothing above was inferred from the aggregate `PASS` or from `counts`.

## 3. Conversion mapping

Tool: [`tools/mcp_re_projection.py`](../../tools/mcp_re_projection.py) (`read` → `convert` → projection; `derive`
separately). Deterministic (re-conversion is byte-identical); reads only the listed paths; writes only `--out`.

| MCP-RE | v1 projection | Faithful? |
|---|---|---|
| active theorem `THM-NNNN` | claim, same id; `statement_digest` = re-derived theorem fingerprint | yes (fingerprint equals the record's, 133/133) |
| `supported_by` | `support = {form: "all", units}` (MCP-RE requires every supporting unit FRESH) | yes |
| `depends_on` | `depends_on` | yes |
| premise closure | claim `premises`, from the review record, only where the record's review digest (which covers premises) equals the reviewed one; else `argument: unknown`, `premises: []` | conditional (all 133 qualified) |
| specification review | `review` with encoding `mcp-re.specification-review/1` → evaluator `incompatible` | **no** (mapping loss; nothing minted) |
| `[[unit]]` | unit, same id, `evidence: []`; class, evidence class, declared refs, recorded fingerprint in `extensions` | ids yes; evidence **no** (missing data) |
| assumption `ASM-NNNN` | premise, same id; `statement_digest` = re-derived entry digest; `class` = `premise_class` (same vocabulary) | yes (67 premises; no unmapped class) |
| assumption review | premise `review`, only if the ledger backs the current entry text | yes, conservative (unbacked → unreviewed) |
| closure condition | `scope = {closure: "all-active", roots: root_theorems}` | yes for these targets; see D1 for empty roots |
| record `verdict` | `producer_verdicts.closure` (`PASS`) | yes; compared, never trusted |
| run, ledger, policy revision, sources | `extensions` | carried, not interpreted |

Each projection: 133 claims, 308 units, 67 premises, 203 claim→premise links, 286 claim→unit links, 165 dependencies.

## 4. Mapping-loss register

| # | Concept | Why v1 cannot carry it | Effect |
|---|---|---|---|
| L1 | Per-unit evidence outcomes and applicability | not committed (attestations are not persisted) | every unit `no-evidence`; no claim can be established |
| L2 | Specification review binding (theorem fingerprint + semantic review digest) | v1 reviews bind v1's `argument_digest` only | every review `incompatible` |
| L3 | Semantic review components (`supporting_semantics`, stale causes) | v1 binds unit ids, not unit contents (documented v1 limit) | cannot express `STALE_SEMANTICS`; N6/N18 not discriminable in v1 |
| L4 | Owner-approval ledger backing | no v1 field | applied in conversion: unbacked premise reviews withheld (none at these targets) |
| L5 | Unit fingerprints (semantic + toolchain/lane/policy components) and run identity/completeness | v1 takes applicability as reported; no component model | in `extensions` only; N7/N18 not representable |
| L6 | Unit edges (`verification.toml edge`, 18 rows) | no unit-to-unit relation in v1 | not used by MCP-RE's closure condition; no verdict effect |
| L7 | Premise closure membership | derived by MCP-RE from unit fingerprints | taken from the review record under the digest-equality condition |
| L8 | MCP-RE's binary closure (`PASS`/`FAIL`) vs v1's four verdicts | MCP-RE `FAIL` covers v1 `INCOMPLETE`, `FAILED` and `UNDECLARED` | comparison is `PASS` vs not-`PASS` only |

Per-target dynamic losses (missing review, missing semantic digest, unmappable premise, undeclared unit, unbacked
premise, malformed review, unverifiable ledger): **none** at any target.

## 5. Target comparisons

| | 4e3ffbb6 | 9dab7082 | ffeafb22 |
|---|---|---|---|
| MCP-RE native verdict (record) | PASS (roots COMPLETE 12/12; 133/133 on each axis) | PASS | PASS |
| Dev Platform verdict (faithful projection) | **INCOMPLETE**, `projection-inconsistent` | **INCOMPLETE**, `projection-inconsistent` | **INCOMPLETE**, `projection-inconsistent` |
| Evaluation projection digest | `3996be4c…4d2c0972` | `b5323b12…c48deea7` | `8e1ae724…6a36948ef` |
| Claims established (DP) | 0/133 | 0/133 | 0/133 |
| Claim reasons (DP) | `unit-no-evidence` 286, `review-incompatible` 133, `dependency-not-established` 165 | same | same |
| Premises current (DP) | 67/67 | 67/67 | 67/67 |
| Roots / scope | 12 roots, all active; root closure covers 106 of 133 (27 active theorems outside it) | same | same |
| Theorem fingerprints re-derived = record | 133/133 | 133/133 | 133/133 |
| Review axis, independent parts² | 133/133 | 133/133 | 133/133 |
| Semantic digest = record's derived value | 133/133 | 133/133 | 133/133 |
| Ledger identity / record digests / sets / policy revision | all agree | all agree | all agree |
| Evidence established | **unscorable** | **unscorable** | **unscorable** |
| Currently verified / roots established | **unscorable** (needs evidence) | unscorable | unscorable |
| Comparison | **partial**: review and structure scored, evidence and verdict unscorable | partial | partial |

² Review record present and valid; claim fingerprint and components equal the re-derived ones; ledger backs the
theorem; `review_digest` is the digest of its own components; their claim, dependency and requirement parts equal the
re-derived ones; every listed premise is at its re-derived entry digest, reviewed at that digest and ledger-backed;
no unit-scoped premise of a supporting unit is missing from the list.

Claim-level agreement: on the review axis, Dev Platform's own recomputation (`derive`, MCP-RE's rule, not the
evaluator) agrees with MCP-RE's `review_current` for all 133 claims at each target. On establishment, the evaluator and
MCP-RE disagree on all 133 claims, entirely explained by L1 and L2. The 27 active theorems outside every root's
closure confirm that MCP-RE's condition maps to `all-active`, not `roots`.

Across targets (record comparison): ffeafb22 → 9dab7082 moved nothing. 9dab7082 → 4e3ffbb6 (v0.18.0 → v0.18.1) moved
**all 308 unit fingerprints, no theorem fingerprint, and five semantic review digests** (THM-0077, 0086, 0092, 0106,
0111); exactly those five review records were re-recorded, and the ledger identity changed (one new approvals file).

## 6. Control matrix

Tool: [`tools/mcp_re_e2_controls.py`](../../tools/mcp_re_e2_controls.py). "Real data" means a perturbation of the
faithful projection, or of the committed inputs read by `derive`, at each of the three targets; results were identical
at all three. Perturbation content (e.g. an injected failure) is synthetic; the structure it lands in is MCP-RE's.

| # | Class | How evaluated | Expected | Observed | Result |
|---|---|---|---|---|---|
| N1 | EQ | real data (claims removed) + synthetic | `UNDECLARED` | `UNDECLARED` | agree |
| N2 | EQ | real data, scope `roots` | `UNDECLARED` | `UNDECLARED` | agree |
| N2 | EQ | real data, scope `all-active` + synthetic | `UNDECLARED` | `INCOMPLETE` (real); **`PASS`** (synthetic, all else passing) | **D1** |
| N3 | EQ | real data (THM-0001 units `[]`) + synthetic | `no-support`, not PASS | `no-support` | agree |
| N4 | EQ | synthetic only | `INCOMPLETE` | `INCOMPLETE` | agree (vacuous on real data: no evidence to replace) |
| N5 | EQ | real data (missing unit) + synthetic | `unresolved-unit`, not PASS | `unresolved-unit` | agree |
| N6 | EQ | real inputs via `derive` (THM-0001 statement edited) | fingerprint and review move for it and its dependants only | 22 moved = 22 stale = THM-0001 + 21 dependants | agree |
| N6 | EQ | real data, v1 projection | review `stale(claim)` | `incompatible` | **D2** (mapping loss L2) |
| N7 | EQ | synthetic only | `stale`, `INCOMPLETE` | as expected | not representable on real data (L5) |
| N8 | EQ | synthetic only | `INCOMPLETE` | as expected | vacuous on real data (L1) |
| N9 | EQ | real data (current observed failure injected in `http_profile.freshness_window`) + synthetic | `FAILED`; consumers blocked | `FAILED`; 6 claims sharing the unit failed; all 21 dependants of THM-0001 not established | agree³ |
| N10 | EQ / CORR | Dev Platform engine, synthetic only (`tests/test_impact.py`, unmapped path and unknown change set fail closed) | every owed check selected | as expected | not representable by the projection; MCP-RE side (F-3) needs selector execution: unscorable here |
| N13 | EQ / CORR | none | — | — | not representable (mutation attribution); needs probe results: unscorable |
| N14 | EQ | none | — | — | not representable (selection); MCP-RE behaviour needs selector execution: still unclassified |
| N17 | SPEC | real data (base and N9) + synthetic | `projection-inconsistent`, never PASS | as expected (the base projection already is: record PASS vs recomputed INCOMPLETE) | agree |
| N18 | EQ | real inputs via `derive`: 4e3ffbb6 data with 9dab7082's review records; plus record comparison | reviews current, evidence stale | 5 semantic reviews stale, exactly the five re-recorded; 0 claim fingerprints moved; 308/308 units moved | agree with MCP-RE's rule; **D3** (plan premise); not representable in v1 (L3, L5); synthetic v1 test passes |
| N19 | SPEC | synthetic only | `unsupported-form` → `INCOMPLETE` | as expected | MCP-RE has no `any-of`: not representable |
| N20 | SPEC | synthetic only | `INCOMPLETE` (`unsupported-form`) | as expected | as N19 |
| N21 | SPEC | real data (THM-0001 `argument: incomplete`) + synthetic | `argument-incomplete` | `argument-incomplete` | agree |
| N22 | SPEC (parity check) | real data (review of ASM-0027 removed) + real inputs (ASM-0027 entry edited) + synthetic | `premise-unaccepted` on exactly its claims | 18 = 18 claims in v1; 18 in `derive` (MCP-RE `PREMISE_UNREVIEWED`); premise `stale` | agree; **reclassify EQ** (MCP-RE parity holds) |
| N23 | SPEC | synthetic only | `unsupported-form`, never reinterpreted | as expected | as N19 |
| N24 | SPEC | Dev Platform engine, synthetic only (`tests/test_engine.py` `CertificationRequiresPassInRunTest`; `tests/test_evidence_identity.py`) | no carry at certification | as expected | not part of the projection contract |
| — | data | real inputs: one ledger line altered | ledger refused; identity differs; no premise review carried | as expected | agree |

³ The first run of N9 reported a disagreement caused by the control's own predicate: it accepted only the reason
code `dependency-not-established`, while the evaluator reports `dependency-failed` for a failed prerequisite and
`failed` for claims sharing the failing unit. The predicate was corrected; the expectation was not changed.

## 7. Discrepancies

| # | Case | Dev Platform | MCP-RE / expected | Class | Classification |
|---|---|---|---|---|---|
| D0 | Closure at all three targets | `INCOMPLETE`, `projection-inconsistent` | `PASS` | EQ | **missing data** (L1) and **mapping loss** (L2); not an evaluator or MCP-RE defect |
| D1 | `all-active` scope with no declared roots | not `UNDECLARED`; `PASS` when every claim is established | MCP-RE never closes without a declared root (`closure_satisfied`: `UNDECLARED` fails) | EQ | **specification ambiguity** in draft ADR A (does `all-active` require declared roots?). If MCP-RE parity is intended it is an **evaluator defect** (a PASS where MCP-RE fails). Not triggered at these targets (12 roots). Pinned by a test; evaluator unchanged |
| D2 | N6 in v1 | review `incompatible` | `stale(claim)` | EQ | **mapping loss** (L2); the same perturbation agrees through `derive` |
| D3 | N18 premise | — | the plan cites v0.18.0 → v0.18.1 as a toolchain-only bump | EQ | **specification ambiguity (plan)**: the records show five semantic review moves as well; the plan's construction should cite a pure toolchain change, or N18 should be stated per theorem |
| D4 | N22 class | agrees with MCP-RE | plan: SPEC "parity to be checked" | — | parity demonstrated: reclassify EQ |

No discrepancy was resolved by changing an expected result or the evaluator.

## 8. Processing and resource use (observed)

- Complete final pass (3 conversions, 3 evaluations, 3 control sets): **7.2 CPU-seconds** (7.05 user, 0.15 sys),
  7.4 s wall, 49 MB peak RSS. All runs in the session, including reruns and tests, stayed under one CPU-minute
  (estimated from per-run timings). Budget: one CPU-hour.
- Network: about 270 GitHub API GET requests for committed files of `syncom-systems/mcp-re` (trees, blobs, two
  compare/commit metadata reads). No CI log, artifact, run or transcript was read; nothing was written to GitHub.
- Executed: Dev Platform's evaluator (library and CLI), the two E2 tools, and the new unit tests. Not executed: any
  MCP-RE command, test, proof, fingerprint, selection, review or closure.

## 9. Limits

- `derive` re-implements MCP-RE's encodings from reading its source (`_fingerprint.canonical_digest`,
  `fingerprint_theorem`, `assumption_digest`, `_approvals.ledger_identity/entry_text/ledger_state`,
  `_closure_record.canonical_digest`, `_review._valid`). A known-answer test reproduces MCP-RE's committed ASM-0002
  digests; 133/133 fingerprint matches are a second check. A re-implementation can still share a misreading with
  nothing to expose it beyond these matches.
- The semantic review digest's `supporting_semantics` part and boundary-attached premise membership need unit
  fingerprints over the source tree; they are compared with the record's value, not recomputed (that would be E1-type
  fingerprinting, outside E2).
- The evidence axis has zero coverage. Agreement on identities says nothing about whether any unit's evidence passed.
- Three targets, two distinct identity states, one consumer; the real-data controls perturb one leaf claim (THM-0001,
  the leaf with the most dependants) and one premise (ASM-0027, the most used).
- Synthetic tests show agreement with the draft ADR text, not with MCP-RE.

## 10. Recommendations

**R-16 (migration criterion).** Keep it; E2 shows it is **not met** and cannot be met from committed records. Add
explicitly: equivalence must be shown on independently recomputed evidence, not on agreement with a record's
identities or verdict, and a target whose evidence is not available is unscorable, not equivalent.

**Projection contract (candidates for owner decision; none implemented).**
1. Decide D1: whether `all-active` requires a non-empty declared root set (MCP-RE parity) or a closure without roots
   is meaningful.
2. Decide how a producer's review that v1 cannot bind is represented. `incompatible` is correct and conservative;
   anything stronger would be a producer-verified review class that, like `declared` provenance, never establishes on
   its own.
3. Per-unit evidence state is the one input no Dev Platform-side converter can supply. If equivalence is still wanted,
   it needs data that exists only at MCP-RE's closure time.

## Final assessment

| Question | Answer | Basis |
|---|---|---|
| Can the current generic evaluator reproduce MCP-RE's committed closure conclusions? | **No**, at none of the three targets | demonstrated (§5) |
| If not, why? | **Missing data** (per-unit evidence is never committed) and **mapping loss** (review binding). Not incorrect generic semantics on any demonstrated case; one semantic ambiguity (D1) exists but does not affect these targets | demonstrated (§2, §4, §7) |
| Which concepts cannot be carried through v1? | L1–L8: evidence outcomes and applicability; MCP-RE review binding; semantic review components and stale causes; ledger backing; unit fingerprints and run completeness; unit edges; premise-closure derivation; binary closure verdicts | demonstrated (§4) |
| Is a consumer-owned exporter necessary? | For the evidence axis, **some MCP-RE-side source of per-unit evidence state is necessary**: no Dev Platform-side converter can recover it from committed records. Whether that is an exporter, persisting the attestation store, or reading the run's evidence artifact is **not established**; for reviews an exporter would only repeat MCP-RE's own verdicts unless v1 can bind them | demonstrated for "necessary"; the form is a hypothesis |
| Smallest justified next step | Owner decisions only: (1) D1 semantics; (2) whether E2 should be rerun with the evidence artifacts of runs 39060691189 and 38672416934 (`verification-evidence-<run>-1`), which are what MCP-RE's closure read; that needs a separate authorization (CI artifact retrieval) and may be time-limited by artifact retention. No exporter, no evaluator change and no MCP-RE change is recommended before those decisions | recommendation |
