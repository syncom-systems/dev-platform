# Investigation of existing implementations

Method: read-only `gh api` reads of `matssun/code` (private), `matssun/nga` (private) and
`matssun/mcp-re` (public). No clones, no writes, no execution. For each repository only the CI
workflows' headers and the documents named below were read (typically the first 80-120 lines), so
this is **evidence from in-repo prose and workflow text, not measured behavior**. Statements that
the repositories themselves flag as estimates are repeated as estimates.
`matssun/dev-platform-infra` was not visible to this account (HTTP 404) and was not touched.

## Verified from text read

### matssun/code (mixed-language Bazel monorepo)
- `pr-gate.yml` is **disabled** (`workflow_dispatch` only): a 58-minute failure motivated moving
  the merge gate to `pre-merge.yml`. `pre-merge.yml` targets < 3 minutes, which its own header says
  is "an estimate, not a measurement".
- Pre-merge selects only the packages owning changed files (`//<package>:all`, no Bazel call);
  reverse dependents are **left to `validation.yml`** because `rdeps(//..., file)` measured > 30 min.
  A global-input change is *routed* to a small sentinel suite and the broad validation is recorded
  as outstanding. `NEVER //...` in the fast lane.
- Pre-commit hooks are relied on to have already run lint/format/secrets; the gate does not repeat
  them. `validation.yml` runs `//...` on main (every push collapsed, every 3h), fails on a target
  *newly* failing, and sets `validation/certified` when all pass. Releases run `--config=live`.
- Self-hosted macOS (and Colima Linux) runners on one Mac; the workflow README states a rule
  that CI workflows stay general and "which tests run is Bazel's decision".

### matssun/nga (Rust, Bazel-only kernel)
- Four tiers with measured latencies (edit 0.3-1.5 s, pre-commit ~2 s, pre-merge 3-122 s, full
  5 s cached to 10-23 min cold). `tools/check.sh` is the authoritative full gate.
- Test targets classified on **two independent axes**: cost (`fast|slow`, measured) and obligation
  (`always|change|periodic`, derived from contracts). "Nothing is `periodic` for being expensive."
  This is the model ADR 0006 adopts.
- Selection is fail-closed (`nga-ci select`): unknown file, deleted file, any query failure, or
  global-policy file -> every test. Selector has unit tests and a self-test against the real graph.
- Evidence states `verified|pending|invalidated|failed|unrealized`, carried across revisions when
  no affecting change; a fast gate reports `pending` rather than implying a theorem.
- Runner policy: `pull_request` (never `_target`), no secrets on PRs, fork PRs forced onto
  GitHub-hosted runners, one-credential runner account. ADR 0005 generalizes this.
- Bazel is the only execution authority (never cargo): what `bazel_only` encodes.

### matssun/mcp-re (public, security-sensitive Rust)
- `verification.yml` is "AUTHORITATIVE" and gates via `./tools/verification/verify --gate`. Its
  header records that it once claimed to be report-only long after it started gating: *prose that
  understates enforcement costs trust* (a lesson for docs-versus-executable policy).
- Ratchet gates (`module_size_gate.py`, `clippy_ratchet_gate.py`): thresholds that may not worsen.
- Trigger path filters were hand-maintained until `verification_trigger_gate.py` derived them from
  the manifest: hand-kept path filters drift.
- Mixed host split: Verus native on macOS, Charon/Aeneas/Lean in a pinned Linux container via
  `docker run` on a self-hosted Mac mini.

## Reusable mechanisms (extracted)
Two-axis check model; fail-closed selection with recorded reasons; evidence state machine with
carry/invalidate; logical runners with trust-based routing; ratchets (future adapter); the stage
ladder shared by all three repositories.

## Repository-specific policy (not extracted)
Bazel target names and tag filters, the sentinel suite, `validation/certified` status, Lean/Verus/
Kani/TLA+ lanes, EvidenceManifest/UnsafeLedger formats, module-size limits, runner hostnames.

## Weaknesses and tensions found
1. `code` defers dependents to the async lane; under ADR 0006 that is only legitimate if the
   dependents' checks are *not* mandatory for that change. A consumer must declare which.
2. Several "measured" targets are estimates or measured on one warm machine.
3. `code`'s workflow list is "checked against the directory by nothing" (self-described): a
   single machine-readable definition would remove this class of drift.
4. Bazel-graph-based impact (`rdeps`) is the right oracle but is slow in `code`; the platform's glob
   impact is a conservative stand-in until a Bazel impact provider exists.

## Not examined
Bazel enforcement internals in `mcp-re`, `code`'s `scripts/affected_targets.py`, `nga-ci` source,
git hooks, `.claude/` agent configuration, anything private beyond the files named above.
