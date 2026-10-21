# E2 follow-up: MCP-RE evidence artifacts (evaluation report)

> **Status:** evaluation output for owner review, informational. A bounded follow-up to the
> [E2 report](e2-projection-equivalence.md) (PR #150), authorized for two artifacts only. Nothing of MCP-RE was
> executed or changed; no CI log, other artifact or agent transcript was read; no raw artifact is committed. No ADR,
> gate, policy, release or attestation is touched. E1, E3, E4 and any exporter are not started.

## Answer first

**Yes, the artifacts materially reduce E2's mapping loss: they remove L1 (per-unit evidence outcomes) entirely, under
one stated basis.** Each artifact is exactly the evidence directory MCP-RE's `assurance-closure` attested for its run.
At all three targets, every one of the 585 declared (unit, lane) pairs has a `pass` record whose fingerprint equals the
unit fingerprint the closure record asserts. No pair is missing or failing, and none is measured at another
fingerprint.

Projected into v1 with that binding, all 308 units are `established`, and `unit-no-evidence` falls from 286 to 0.
The generic verdict is still **`INCOMPLETE`** at every target, now blocked **only** by the review axis (L2:
`review-incompatible` on 133 claims, and the `dependency-not-established` cascade it causes). **No PASS was reproduced
or claimed.**

The basis is that a record is `current` because it matches the **closure record's asserted** unit fingerprint, which
is not recomputed here (recomputing it requires MCP-RE's fingerprinting, which is excluded). With that basis withheld
(`--applicability unknown`), nothing supports, as before.

## 1. Identities, integrity and run linkage

| Artifact | id | Run / attempt | Run head (= record `evidence_commit`) | Event | Size | Zip sha256 (API digest = local) | Expires |
|---|---|---|---|---|---|---|---|
| `verification-evidence-38672416934-1` | 11949291352 | 38672416934 / 1 | `ffeafb22` (`rc/v0.18.0`) | `workflow_dispatch`, success | 213 870 | `a7ea8f7a…afdc442d12` | 2026-10-29 |
| `verification-evidence-39060691189-1` | 12114113728 | 39060691189 / 1 | `b234587c` (`release/v0.18.1-prep`) | `workflow_dispatch`, success | 213 839 | `236bea43…ccdcfef8dfca7dce88641bfdfc4c31ea6b3b534e` | 2026-10-31 |

Each zip holds 589 files: `bundle.json`, 586 lane records, and 2 `measured-artifacts/*.txt`. The manifest digests
(`mcp_digest` of the path, sha256 and git-blob list) are `e8fe9670…453d044e` (run 38672416934) and `e89fb795…1289fd`
(run 39060691189).

The link to the closure runs comes from source and data, not from logs:

- `.github/workflows/verification.yml` is the same blob, `132bff73`, at the baseline `8262c5fa`, at `ffeafb22` and at
  `b234587c`. Its `aggregate` job uploads `.verification/composed` as `verification-evidence-<run>-<attempt>`. Its
  `assurance-closure` job downloads that exact artifact and passes it as `--evidence`.
- Each closure record's `run.id`, `run.attempt` and `run.event` equal the artifact's run. Its `evidence_commit` equals
  the run's head SHA.
- `bundle.json` `policy_revision` (`adr-mcpre-059-r1`) equals each record's `policy_revision`.
- Pairing: 4e3ffbb6 ↔ run 39060691189; 9dab7082 and ffeafb22 ↔ run 38672416934. That is two identity states, as E2
  found.

Integrity is GitHub's artifact digest only. The records are **producer-reported and unauthenticated**, which is v1's
standing limitation.

## 2. Inventory (both artifacts)

| Content | Shape | Count | Source-supported state |
|---|---|---|---|
| `bundle.json` | `aggregate`, `lanes{8}`, `policy_revision`; **no `scope`** | 1 | all `PASS`; byte-identical across the two runs. Producer verdict, **not used to establish anything** |
| `<lane>/<unit>.json` | `unit_id`, `lane`, `result`, `fingerprint`, `detail`, optional `prover` | 586 | per-unit outcome and the fingerprint measured at (`_evidence.EvidenceRecord`) |
| lanes | test 275, mutation 268, structural 34, verus 6, lean 1, generated-model 1, measured 1 | | every `result` is `pass` |
| `prover` pins | verus (commit, version, pin, host), lean/aeneas/charon revisions, extraction digests | 8 | identical across runs |
| `measured-artifacts/*.txt` | `MEASURED:` key=value lines (repo-relative paths, counts) | 2 | inventoried, not mapped |
| `assumptions` lane | bundle verdict only, no per-unit records | — | run-level; not mappable per unit |

Path, `lane` and `unit_id` agree for all 586 records, and none is malformed. The `generated-model` record is not
declared by any unit (`attest` does not consume it). Between the two runs all 586 fingerprints differ, and 3 detail
strings differ. This agrees with E2's "all 308 units moved".

A sensitivity check found no hostnames beyond `Linux/x86_64`, and no user paths, tokens, keys, emails or URLs. The
content is derived from the public MCP-RE sources. A representative record:
`{"unit_id": "proxy.connection_bounds", "lane": "test", "result": "pass", "fingerprint": "sha256:7ab2dd04…", "detail":
"//mcp-re-proxy:proxy_unit_test: 11 passed"}`.

**Absent from the artifacts:** the attestation store, `review --json` output and closure decision. Those are in
`assurance-closure-<run>-1`, which is not authorized and was not read. Also absent: any record of how each unit
fingerprint was computed, and any failed or refused result.

## 3. Mapping into projection v1

Tool: [`tools/mcp_re_evidence.py`](../../tools/mcp_re_evidence.py). It layers on `tools/mcp_re_projection.py
convert` without changing it, and its tests are in `tests/test_mcp_re_evidence.py`. It attaches a record only for a
(unit, lane) pair the target's `verification.toml` declares. That is MCP-RE's `required_lanes` set, so 588 declared
references collapse to 585 pairs.

| v1 field | From | Faithful? |
|---|---|---|
| `id` | `<lane>:<unit>` | yes (MCP-RE keys records by lane and unit) |
| `outcome` | `result`: `pass` → `passed`, `fail` → `failed`; another string → `unavailable` (unit refused); a non-string result makes the record malformed, so it is not attached | yes, except the divergences below |
| `provenance` | `observed` (`measured` for the measured lane) | yes; producer-reported |
| `identity` | the record's fingerprint (the input identity measured at) | yes |
| `applicability` | `current` iff the fingerprint equals the record's unit fingerprint **and** MCP-RE would issue the unit a pass from this run (below); a differing fingerprint is `stale`; otherwise a passing item is withheld as `unknown`, with the reasons in `extensions.withheld`. `unknown` mode withholds every item | **conditional**: `attest`'s own tests, applied against the record's asserted fingerprint |
| `boundary` | `declared` | yes (declared inputs, not shown complete) |
| `kind` | test → test; verus, lean → proof; measured → measurement; mutation, structural → `control` | **approximate** for mutation/structural; kind never changes a verdict |
| `extensions` | lane, detail, prover, record path and sha256, applicability basis | kept |

Two fail-closed rules decide whether a passing item may be `current` (revision 2, after owner review):

- **Issuance** (MCP-RE `_evidence.decide_issuance`). A unit is issued a pass only if **every** declared lane has a
  record at the unit fingerprint and all of them pass. A missing, malformed or stale required lane refuses the unit.
  So does a refused or failed producer over a `PROOF_DEPENDENCY`, `CONTRACT_CONSUMES` or `COMPILE_DEPENDENCY` edge
  (fixpoint).
- **Run linkage** (MCP-RE `assurance-closure.run_refusals`, plus this converter's linkage). The run must be
  `workflow_dispatch` or `schedule`, and the bundle present, unscoped and `PASS`. The record must name this run id
  and attempt, and the bundle must carry the record's policy revision. Absent linkage refuses.

A refusal never removes or upgrades an item. It withholds currency from passing items only, so the unit cannot be
established. A record is malformed, dropped and its unit refused when it is not a JSON object, or when `unit_id`,
`lane`, `result` or `fingerprint` is absent or not a non-empty string, when the fingerprint is not
`sha256:` plus 64 lowercase hex characters, or when the lane or unit id disagrees with the record's path.

Where v1 and MCP-RE decide differently, the difference is one of two kinds. None occurs in the real data.

- **Stronger refusal** (v1 refuses where MCP-RE issues a pass). A passing lane with no v1 kind refuses its unit, and
  its item is not attached. A passing record whose body `unit_id` or `lane` is mistyped or disagrees with its path is
  dropped; MCP-RE keys records by path and would issue it.
- **Weaker counterevidence** (v1 reports no failure where MCP-RE issues one, so the verdict is `INCOMPLETE`, not
  `FAILED`). A string result other than `pass`/`fail` is carried as `unavailable`; a non-string result is dropped;
  a failing record on a lane with no v1 kind is not attached. MCP-RE issues each as `ISSUE_FAIL`. The unit is still
  refused, so nothing is established, but v1 does not mint a failure the record does not state in its terms.
- **Stronger counterevidence** (the reverse of the above). A failed record at the unit fingerprint stays current
  counterevidence even when the unit is refused for another lane or by the run, so v1 reports `failed`. MCP-RE's
  refusal writes no attestation, so it reports no failure for that unit.

A non-string or ill-formed fingerprint is refused by both (MCP-RE as a fingerprint mismatch).

Each unit's decision is in `extensions.mcp-re.issuance`, and the run refusals are in
`extensions.mcp-re.evidence_artifact.run_refusals` and `binding.json`.

Reviews, premises, arguments, scope and producer verdict are `convert`'s and unchanged. A test pins that the
projection equals `convert`'s apart from the evidence.

## 4. Remaining mapping losses and missing review bindings

| E2 loss | After the artifacts |
|---|---|
| L1 per-unit outcomes and applicability | **removed** under the record-bound basis; replaced by the narrower loss below |
| L2 specification review binding | **unchanged**: 133/133 reviews `incompatible`. This is now the sole cause of non-establishment |
| L3 semantic review components | unchanged |
| L4 ledger backing | unchanged (applied in conversion) |
| L5 unit fingerprints, run identity and completeness | **narrowed**: run completeness and linkage are now observed and **applied** as a withholding rule. They still have no v1 field, and they never upgrade an item. Fingerprint components and their recomputation remain unrepresented |
| L6 unit edges | **applied** in conversion: prerequisite refusal is propagated by withholding. v1 still has no unit edge. On the real data it is vacuous, because every unit is issued |
| L7 premise closure | unchanged |
| L8 binary vs four-valued verdict | unchanged |
| new: applicability basis | `current` rests on the closure record's assertion of each unit fingerprint |
| new: evidence kind | mutation and structural map to `control` approximately |
| new: undeclared record | `generated-model/core.time_civil_from_days`, not attached |
| new: issuance divergences | stronger refusal: a passing lane with no v1 kind, or a passing record with a mistyped or mismatched `unit_id`/`lane`, refuses the unit (MCP-RE: pass). Weaker counterevidence: an unmappable or non-string result, or a failure on a lane with no v1 kind, refuses the unit without a failure (MCP-RE: `ISSUE_FAIL`). Stronger counterevidence: a refused unit with a current failure is `failed` in v1 (MCP-RE: no attestation). None occurs in the real data |

Missing review bindings: none of the 133 v1 claims can carry a v1-compatible review. MCP-RE's reviews bind its theorem
fingerprint and semantic review digest, not a v1 `argument_digest`. That is L2, and no review was minted.

## 5. Rerun (informational, source-supported states only)

Evaluator: Dev Platform `main` `4d5272a` (unchanged). MCP-RE semantics: baseline `8262c5fa`.

| | 4e3ffbb6 | 9dab7082 | ffeafb22 |
|---|---|---|---|
| Artifact | run 39060691189 | run 38672416934 | run 38672416934 |
| Declared pairs bound at the record fingerprint | 585/585 `pass` | 585/585 `pass` | 585/585 `pass` |
| Run refusals / unit issuance | none / 308 `ISSUE_PASS` | same | same |
| Items `supports` / units established (record-bound) | 585 / 308 of 308 | same | same |
| Claims whose supporting units are all established | 133/133 | 133/133 | 133/133 |
| Claim reasons (E2 → now) | `unit-no-evidence` 286 → **0**; `review-incompatible` 133; `dependency-not-established` 165 | same | same |
| Dev Platform verdict | **`INCOMPLETE`**, `projection-inconsistent` | same | same |
| MCP-RE record | `PASS`, 133 `evidence_established` | same | same |
| Evidence axis comparison | **agrees** (133/133) on the record-bound basis | agrees | agrees |
| Verdict comparison | unscorable as equivalence: blocked by L2 | same | same |
| `unknown` applicability | 0 supports; `unit-not-established` 286; `INCOMPLETE` | same | same |
| Projection sha256 (record-bound, rev. 2) | `b8cee494…` | `e08d17d3…` | `be5de735…` |

**Cross-binding control** (real data). Projecting 4e3ffbb6 against run 38672416934's artifact gives 585/585
`fingerprint-differs`, every item `stale`, `unit-not-established` 286, and `INCOMPLETE`. It also gives run refusal
`run-id-mismatch` and 308 `REFUSE`.
The binding discriminates: the earlier run's evidence does not establish the later target.

Synthetic controls (`tests/test_mcp_re_evidence.py`, 25 tests) cover the following:

- A `fail` record gives `counterevidence` and `FAILED`.
- A missing record gives no item and a listed loss.
- A record at another fingerprint gives `stale`.
- Undeclared records are not attached, and malformed ones are dropped. That includes a non-string, empty or
  unhashable `unit_id`, `lane`, `result` or `fingerprint`, or an ill-formed fingerprint string, which is dropped
  without an exception or an item; a corrupt `bundle.json` is `bundle-absent`; a
  mistyped failure mints no counterevidence.
- A unit requiring test and mutation, with only the test passing, is not established. The same holds when the
  required record is missing, malformed or unmappable, when its lane has no v1 kind, and when a prerequisite is
  refused.
- A current failure stays counterevidence when another lane is missing or the bundle is `INCOMPLETE`.
- A scoped, `INCOMPLETE` or absent bundle establishes nothing, even with every record passing at a matching
  fingerprint. So does a mismatched or absent run id, attempt or policy revision, or a non-complete event.
- The CLI writes only its three outputs and leaves the artifact unchanged.

Control status changes from E2 §6:

- **N9** stays real-data-injected plus synthetic, because the artifacts contain no failure.
- Evidence **staleness** (N4/N7 in kind) is now **evaluated through faithful data** by the cross-binding control.
- **N8** (no evidence) is no longer vacuous: it is evaluated in `unknown` mode.
- N10, N13 and N14 stay unscorable. The mutation records carry only "N probe(s), each turning a declared control red",
  with no per-probe attribution.
- The other controls are unchanged.

Processing (rev. 2 rerun): 2.1 CPU-seconds for all seven projections and evaluations, 44 MB peak. The full suite took about 53 s.
Network: two artifact zips, run and artifact metadata, three `verification.yml` reads and one compare call, all
read-only GETs.

## 6. Limits

- Every `current` rests on the closure record's unit fingerprints. The artifact and the record agree with each other,
  but neither was checked against the source tree.
- The records and the bundle are unauthenticated producer output. GitHub's digest shows the zip is the one stored,
  not who wrote its contents.
- `bundle.json` `PASS` and the record `PASS` were never used to set an item, a unit or a verdict.
- Not read: the attestation store and `review --json` (`assurance-closure-*` artifacts), and `evidence-host-*` /
  `evidence-extraction-*` (the halves merged into these artifacts).
- The artifacts expire on 2026-10-29 and 2026-10-31. This report keeps digests and counts only, so the comparison is
  not re-runnable after expiry unless the owner archives them (not proposed here).

## Final assessment

**Demonstrated:**

- The two artifacts are the evidence the two closure runs attested, linked by workflow source, run identity, evidence
  commit and policy revision.
- They supply per-unit outcomes, evidence identities (the fingerprint measured at) and run completeness.
- At all three targets every declared pair passed at exactly the fingerprint the closure record asserts.
- The generic evaluator, given those items, establishes all 308 units. On the evidence axis it agrees with MCP-RE
  for 133/133 theorems.
- The earlier run's evidence is correctly stale for the later target.
- The generic verdict remains `INCOMPLETE`, and the sole remaining cause is the review mapping loss L2.

**Not demonstrated (hypothesis):**

- That the generic evaluator would reproduce MCP-RE's `PASS` if L2 were solved. This needs a v1-expressible review
  binding, which is a schema or ADR A question, not authorized here.
- That the asserted unit fingerprints are correct for the target trees. This needs fingerprinting.

**Still unscorable:**

- The verdict equivalence (L2).
- Independent applicability (fingerprint recomputation).
- MCP-RE's issuance and prerequisite-edge refusals on real failures. They are now applied and tested
  synthetically, but no real artifact contains a failure or refusal.
- Selection and mutation attribution (N10, N13, N14).
- Producer authentication.
