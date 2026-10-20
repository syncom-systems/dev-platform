# Defect report (candidate): certification can rest on carried, unexecuted evidence

> Status: **candidate defect, established by source inspection only. Not reproduced, not executed.** No code, test or
> configuration was changed. Revision examined: `dev-platform` @ `6c0e7b4`. Register entries: R-5, R-6. This is a
> correctness concern in the current implementation, independent of the proposed assurance architecture, and takes
> precedence over it.

## 1. Summary
A `dev-platform check --stage full` run can report `certification.certified = true` while a configured check did not
execute in that run, if (a) the check's `stages` omit `full` and (b) a caller-supplied `--previous` record lists that
check as `verified`. The previous record is not validated or bound to any revision, configuration or environment. A
certified result is the input from which an application release record is assembled
(`src/dev_platform/provenance.py:28-58`, `assemble`), so the gap reaches release provenance.

## 2. Control flow (`src/dev_platform/engine.py` unless stated)
1. `cli.py:67` — `check` and `explain` accept `--previous PATH`; `cli.py:672` loads it with `json.loads`, no schema,
   revision, configuration or environment check.
2. `:113` — `prev_state = {c["id"]: EvidenceState(c["state"]) …}`: only `id` and `state` are read.
3. `impact.py:50` — `select` considers only checks whose `stages` contain the run's stage; at `full` every such check
   is selected (`impact.py:56-58`).
4. `:129-131` — a configured check absent from the selection (not defined at `full`) gets `outcome = NOT_RUN`,
   `impacted = False`, reason "not defined for stage full". No command runs.
5. `:166-167` → `model.py:49-71` — `advance(VERIFIED, impacted=False, outcome=NOT_RUN)` returns the previous state
   unchanged: `verified`.
6. `:206` — the per-check certification blocker is `state != "verified"`; it does not ask whether the check passed in
   this run. No blocker is added.
7. `:186-207` — with a pinned platform, known revision, conformant certifiable environment, clean tree and execution,
   `certified = not blockers` is `true`.
8. `provenance.py:35-38` — `certified_problems` checks stage `full`, `executed`, `certified`, pinned mode, environment
   and revision; all hold, so `assemble` accepts the record.

## 3. Preconditions
- Configuration: a check with `obligation = "always"` or `"change"` whose `stages` include `pre-merge` but not `full`.
  This passes validation: `config.py:314-318` requires `pre-merge` for mandatory checks; only `periodic` checks must
  include `full` (`config.py:319-320`).
- Previous record: any JSON with `{"checks": [{"id": "<that check>", "state": "verified"}]}`. It need not come from
  the same revision, configuration, environment or platform release, and need not be a `result/v1` record.
- All other certification conditions satisfied by the current run.
- Without `--previous` the check is `pending` and blocks certification (`model.py:63-64`); the gap needs the file.

## 4. Intended guarantee versus code
- ADR 0006 §6: certification requires "a full-stage run, all checks verified". The evident intent, consistent with
  ADR 0006 §4 and ADR 0015's separation of claims, is that the full-stage run is itself the evidence.
- ADR 0006 §4: `verified` is carried only across a change that "provably does not reach the check". An unbound file
  proves nothing about reach (R-5).
- Code: "verified" is satisfied by carried state, and carry is from an unvalidated file. Both readings of §6 ("verified
  in this run" vs "verified state after this run") are possible from the text; the code implements the weaker one.
- Exposure: no known consumer is affected — NGA's only check (`bazel.pilot`) and Dev Platform's own checks include
  `full`; no committed workflow passes `--previous` (reconciliation §3.3). Not verified for unknown consumers.

## 5. Minimal reproduction plan (not executed; needs authorization)
In a scratch copy inside the workspace (no consumer, CI or record touched):
1. `dev-platform.toml` with two checks: `a` (`always`, stages `pre-merge`, `full`, command `true`) and `b` (`change`,
   inputs `["src/**"]`, stages `pre-merge` only, command `false` — would fail if run).
2. `prev.json`: `{"checks": [{"id": "b", "state": "verified"}]}` (hand-written, no revision).
3. Run `check --stage full --previous prev.json --json` under conditions where every other blocker is absent (pinned
   platform, conformant environment, clean committed tree).
4. Expected under the defect: `b.outcome = not_run`, `b.state = verified`, `certification.certified = true`.
5. Control: same run without `--previous` → `b.state = pending`, certification blocked.
Cheaper equivalent: a unit test calling `engine.build` directly with a `Resolution("pinned", …)` and a conformant
environment, as `tests/test_engine.py:100-117` already does; no subprocess, no environment setup.

## 6. Expected negative regression test
`test_full_stage_never_certifies_from_carried_state`: configuration as in §5, `build(Stage.FULL, …, previous={b:
verified})` must give `certified = false` with a blocker naming `b` (e.g. "check b did not pass in this run" or "check
b is not defined at stage full"). Companion assertions: carry at `pre-merge` keeps today's behaviour; a `full` run in
which every check passes certifies as today (`test_engine.py:101-102`).

## 7. Corrective options
| Option | Change | Consequence | Compatibility |
|---|---|---|---|
| **(a) recommended** | Certification blocker for every configured check whose `outcome` in this run is not `passed` | Closes the gap with no config change; carried state never certifies | A configuration with a mandatory check lacking `full` can no longer certify (today it can only via `--previous`). Existing certified results unaffected |
| (b) | Validator: mandatory checks must include `full` | Rejects such configurations at load | Breaking for any such consumer; does not stop a forged `--previous` from carrying other state at `pre-merge` |
| (c) | `full` runs every configured check regardless of `stages` | Changes stage semantics (ADR 0006 §5) | Behaviour change for every consumer |
| (d) | (a) plus a `doctor` warning for mandatory checks without `full` | Same as (a), earlier signal | Additive |

Recommendation: (d). Independently, the unbound carry itself (R-5) remains a development-loop defect; (a) removes its
effect on certification but not on admission reports. A narrow interim for R-5 — refuse `--previous` unless its
`revision`, `platform` and configuration digest match the current run, else ignore it — is separable from draft ADR B.

## 8. Governance
- (a)/(d) is a **clarification** of ADR 0006 §6 ("all checks verified" means passed in the certifying run). The owner
  must confirm it is a clarification, not an amendment (R-6). R-19's wording fix to §6 can be done in the same change.
- Release note: behaviour change in certification; 0.x minor bump under `planning/release-policy.json`.

## 9. Authorization requested (separately for each)
1. **Reproduce:** add and run the §6 test (or the §5 scratch run) on a branch; no other code change; output used only
   to confirm or refute this report. Budget: one local test run plus the existing CI on that branch.
2. **Fix:** implement option (a)/(d) with the regression test, update `docs/verification-model.md` and ADR 0006 §6
   wording (R-6, R-19), through the normal release process.
Neither is authorized by this report.
