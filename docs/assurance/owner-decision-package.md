# Owner decision package (rev. 2)

> Status: **for owner decision; nothing here is decided or authorized.** Summarizes the [decision register](decision-register.md)
> after the owner review of PR #146. Ratified ADRs keep their authority; draft ADRs A–D remain proposals.

## 1. Decisions by readiness

### 1.1 Urgent
| ID | Decision asked | Recommendation | Why now |
|---|---|---|---|
| **R-15** | Authorize E0 (§2) | authorize | earliest MCP-RE logs expire ~**2026-11-09**; `select-units`-era logs from ~2026-12-24 |
| **R-6** | Certification requires every configured check to *pass in the certifying run* (clarification of ADR 0006 §6) | approve; authorize the reproduction test, then the fix ([defect report](certification-carry-defect.md) §9) | current-implementation correctness concern reaching release provenance; independent of all other work |

### 1.2 Ready (evidence sufficient for the decision itself)
| ID | Decision asked | Recommendation | Remaining dependency |
|---|---|---|---|
| R-5(i) | Carry requires matching identity; an unbound `--previous` contributes nothing (clarification of ADR 0006 §4) | approve | none for the rule; an interim (revision + platform + config digest match) can precede full ADR B |
| R-8 | Unmapped provider paths are owed unless the provider's read set is `complete` for every non-ignored path | approve | none: with no `complete` provider it equals today's fail-closed rule |
| R-1 | Module inside Dev Platform; a projected consumer's own verdict stays authoritative | approve | — |
| R-3 | Dev Platform owns `assurance-projection/v1`; MCP-RE would own its exporter | approve the boundary; requesting the exporter is a separate MCP-RE decision | MCP-RE owner |
| R-4 | Four axes; `PASS/INCOMPLETE/FAILED/UNDECLARED`; argument subset of ADR A §4a (`all`, explicit `incomplete`, premises, review bound to argument digest; `any-of` reserved) | approve the subset as explicitly partial | see §3 open questions |
| R-19 | Correct `verification-model.md` / ADR 0006 §6 wording on self mode | approve; bundle with the R-6 fix | — |
| R-13, R-14 (deterministic part), R-16, R-18 | CLI/runtime enforcement split; deterministic planner first; migration criterion; separate observation record | approve | R-18 is draft ADR D, not part of ADR B |

### 1.3 Need evidence first
| ID | Question | Evidence needed |
|---|---|---|
| R-5(ii) | Refuse `declared`-boundary carry at admission? | E4 read-set measurement (how often globs under-approximate) |
| R-7 | Option B1 (release-due obligations) | E1 replay of MCP-RE's mutation-lane deferral; a consumer that needs it. Baseline stays A |
| R-11 | Counterexample attribution levels | E4 / N13 |
| R-14 (LLM part) | Any LLM ranker | E1 + E3 showing deterministic baseline gains and residual headroom |
| R-2 | Native declaration format | E2 equivalence |

### 1.4 Safely deferred
R-9 (reviewer identity strength), R-10 (formal-methods boundary — no conflict today), R-12 (terminology), R-17
(release composition — current release procedure unchanged until decided).

## 2. R-15: E0 archival authorization proposal

**Purpose.** Preserve the only record of MCP-RE historical selection decisions, lane outcomes, probe kills and
timings, for later evaluation (E1). Data collection only; nothing is executed, analysed or published under E0.

**Scope.**
- Repository `syncom-systems/mcp-re`; workflows `.github/workflows/verification.yml` and `mutation-probe.yml`.
- Every run of those workflows from 2026-08-11 to the authorization date, all events and conclusions (including
  cancelled and failed), all attempts. Reported at investigation time: ~1,327 `verification.yml` and 888
  `mutation-probe.yml` runs.
- Per run: run metadata (`GET /repos/{o}/{r}/actions/runs/{id}` and `/attempts/{n}`), job list with step timings
  (`/runs/{id}/jobs`), and each job's log (`/actions/jobs/{job_id}/logs`).
- Not in scope: artifacts (14-day retention; only their listing is recorded), other workflows, other repositories,
  local agent transcripts (excluded; separate consent required, not requested here).

**Procedure (bounded).**
1. *Inventory* (metadata only, no log content): list runs and jobs; compute exact job count and earliest expiry.
   ~2,300–2,600 API requests.
2. *Download* oldest first (expiry order), ≤ 1 request/s, read-only token (`actions:read`), GET only, ≤ 3 retries
   per job. HTTP 404/410 recorded as missing, not retried further.
3. *Seal*: write the manifest and verify every digest.

**Estimated volume and cost.** Jobs per run were not counted (requires step 1); assuming 5–15 jobs per run gives
~11,000–33,000 job logs at roughly 20 KB–2 MB each, i.e. ~0.5–20 GB. Proposed hard caps: 35,000 job logs, 25 GB,
12 hours wall clock; stop and report on reaching any cap. CI minutes: zero. Model tokens: negligible — a script
performs the download; no log content is read into an agent's context.

**Provenance and integrity.** A manifest entry per file: run id, attempt, job id, workflow path, head SHA, event,
conclusion, API URL, retrieval time, HTTP status, byte size, SHA-256. Files stored byte-for-byte as returned. The
manifest is canonicalized and its SHA-256 recorded in the eventual evaluation report and given to the owner.

**Missing or expired records.** Expected gaps: runs cancelled before any job started (no log), skipped jobs, logs
deleted or already expired, re-run attempts whose earlier attempt logs are gone, artifacts. Each is a manifest entry
with its status, so absence is explicit rather than silent.

**Storage, access and non-publication.**
- Location chosen by the owner, outside any git working tree and outside any synced or published folder. (Under the
  workspace rule, the agent writes only where the owner names; the session scratchpad is discarded and unsuitable.)
- Treated as confidential: logs may contain internal paths, runner details or unmasked data. No upload to any
  service, no commit to any repository, no paste into PRs, issues or documents.
- Later use (E1) publishes only aggregates; any excerpt needs owner review first.
- Retention and deletion date set by the owner at authorization.

**Success criteria.** Every run in the window has a manifest entry; every job is either stored with a verified SHA-256
or recorded missing with its HTTP status; the summary (runs, jobs, bytes, missing by reason) is reported; no write was
made to GitHub or any repository.

**Authorization needed (one statement).** "Authorize E0 as specified: GET-only download of MCP-RE `verification.yml`
and `mutation-probe.yml` run metadata, job lists and job logs since 2026-08-11, to <path>, within the stated caps,
retained until <date>." Requested by **~2026-11-01** to leave margin before the first expiry.

## 3. Open questions on the generic model (R-4)
1. Is `any-of` needed in v1, or reserved (`unsupported-form`) until a consumer needs it? Recommendation: reserve.
2. May an accepted `assumed` premise stand at the release gate? Recommendation: yes, listed in the `PASS` record.
3. Should the argument digest be part of the claim fingerprint or a separate digest?
4. Should evidence `kind` be a closed vocabulary (`proof, test, measurement, analysis, control`) or a free tag?
   Recommendation: closed, so `PASS` records are comparable across consumers.

## 4. Recommended sequence (each step separately authorized; none started)
1. **Certification defect:** decide R-6 → reproduction test (defect report §9.1) → fix with regression test and
   R-19 wording (§9.2). Smallest, highest-value change; no dependency.
2. **E0** (R-15), in parallel with 1, before ~2026-11-09.
3. **Carry binding:** decide R-5(i) → interim identity check on `--previous`, then draft ADR B identity with boundary
   classes once ratified.
4. **Evaluator, data only:** after R-1/R-3/R-4, a projection evaluator implementing the `all` subset; E2 against
   MCP-RE closure records and controls (EQ/CORR/SPEC, evaluation §5). MCP-RE exporter only on MCP-RE owner request.
5. **Observations and budgets:** R-18 record and per-check timeouts (draft ADR D); then E1 replay over the E0 archive.
6. **E4** read-set measurement — prerequisite for any `complete` boundary, R-5(ii) and R-11.
7. **E3** shadow planner; LLM ranking only after that (R-14).
