# Verification model

## Vocabulary

- **Check**: one authoritative definition (`[[check]]`, unique id) with an adapter, the stages it is
  executed at, an obligation, a cost, and impact inputs.
- **Stage**: `edit` -> `pre-commit` -> `pre-merge` -> `full`. Stages say *where* a check may run.
  `pre-merge` and `full` are admission stages.
- **Obligation**: `always` (owed at every admission), `change` (owed when the change can reach the
  check's inputs), `periodic` (owed on a schedule, uncoupled to inputs).
- **Cost**: `fast | slow`. Informational. **Selection never reads it.**
- **Outcome** of an attempt: `passed | failed | unavailable | not_run`.
- **Evidence state**: `pending | verified | failed | invalidated`.

## Selection (fail closed)

For stage `S`, candidates are checks whose `stages` include `S`. At `full`, all are selected. Else:

| Situation | Effect |
|---|---|
| `always` obligation | selected |
| changed path matches a check's `inputs` | that check selected, reason names path and pattern |
| path matches `impact.global` | every owed (non-periodic) check selected |
| path matches `impact.ignore` | nothing selected for it |
| path matches no input, no ignore, no global (unmapped) | every owed check selected |
| change set unknown (no git, bad ref, nothing supplied) | every owed check selected |

A check that is not selected says why: "no changed input reaches this check".

## Evidence transitions

`advance(prev, impacted, outcome)` ([model.py](../src/dev_platform/model.py)):

| outcome | impacted | prev | next |
|---|---|---|---|
| passed | any | any | verified |
| failed | any | any | failed |
| unavailable / not_run | any | none | pending |
| unavailable / not_run | any | failed | failed |
| unavailable / not_run | yes | verified / invalidated | invalidated |
| unavailable / not_run | no | verified / invalidated / pending | unchanged (carry) |

Tested invariants: `verified` requires a pass or an un-impacted carry; an impacted check that did
not pass is never `verified`; `failed` persists until a pass; a never-run slow check is `pending`,
never realized. A `verified -> failed` transition is reported as a **regression**.

## Admission, certification, release

- **Admitted** (`pre-merge`/`full`): the run executed and every selected check passed. A dry run is
  never admitted. A selected check that is `unavailable`, unroutable or failed blocks.
- **Certified**: stage `full`, executed, every configured check **passed in this run** (a carried
  `verified` never substitutes; a check not defined for `full` blocks, and `doctor` warns about it),
  revision known, platform mode `pinned` (`self` and overrides never certify). **Release eligible** currently equals certified; release-specific obligations
  (provenance, signing) will extend it.

## Configuration invariants (rejected at load)

1. `always`/`change` checks must include `pre-merge`: slow-but-mandatory cannot hide in `full`.
2. `periodic` checks must include `full`. 3. `change` checks must declare `inputs`.
4. Unique ids. 5. `bazel_only` forbids the cargo adapter and direct cargo. 6. Unknown keys fail.

## Exit codes

`0` ok; `1` check failed or obligation unsatisfied; `2` usage/config error; `3` platform
resolution/integrity error. Explaining (`explain`, `check --dry-run`) exits 0 if it could plan.
