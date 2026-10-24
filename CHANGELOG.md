# Changelog

## Unreleased

## 0.14.0
Added (cross-compilation; additive):
- Profiles `rust-aarch64-none-bazel-9.3` and `rust-python-ty-aarch64-none-bazel-9.3`: the Rust (and Python/Ty) baseline plus
  the `aarch64-unknown-none-softfloat` target. A profile's `bazel.extra_target_triples` (approved triples only) requires a
  `rust-std-<triple>` tool pinning the official archive per host; the generated toolchain declares the triple and every
  sha256, `dev-platform/BUILD.bazel` defines the platform, and `--config=dp-aarch64-none` selects it. New macro
  `dp_rust_no_std_library` and check `bazel.cross.dp-aarch64-none`. Qualified with a real `no_std` AArch64 build (rustc
  `--target`, ELF `EM_AARCH64` objects) and negative cases: wrong or missing archive hash, target removed, unsupported
  target, hosted code in the `no_std` crate.

Fixed (found by NGA's trial of 0.13.0):
- The generated Bazel module no longer declares `platforms` or `bazel_skylib`, which collided with a project's own
  declarations (`The repo name 'platforms' cannot be defined by a bazel_dep ...`). Nothing generated refers to either
  module: the ruff binary is wrapped by a platform rule and selected with `@bazel_tools` conditions. The
  `baseline-mixed` fixture now declares `platforms` 1.1.0 and `bazel_skylib` 1.9.2 itself and uses them, so every
  qualification of the mixed profiles resolves and builds an existing workspace with overlapping dependencies.
- `setup` (and `toolchain materialize`) report a project's `.bazelversion` that selects another Bazel than the profile
  pins, with the file, the observed and the pinned version and the correction, before anything is provisioned or
  run. The file is never edited. `toolchain materialize --check` and conformance report it as `bazel-version`.

Changed:
- A release pinned at a version newer than the running CLI that the CLI cannot validate is reported as such (`release X is
  newer than this dev-platform CLI (Y) ... upgrade the CLI`, validation result appended, nothing executed) instead of
  `invalid release`. Validation is unchanged. The upgrade path is documented
  ([distribution](docs/distribution.md#upgrading-the-cli)); published releases and CLIs are not modified.

Added (Ty as the platform type checker; additive, the published mypy profiles are unchanged):
- Profiles `python-ty-bazel-9.3` and `rust-python-ty-bazel-9.3`: the 0.13 baseline with Ty 0.0.91 (hash-locked, Bazel-managed)
  in place of mypy. A profile's `bazel.type_checker` (`mypy` by default, or `ty`) selects the generated `ty.toml`, lint
  aspect, wrapper and lock; a stray `ty.toml` or `[tool.ty]` is a conformance conflict like the other tool policies.
  Qualified with the same real-execution, host-independence and must-be-rejected scenarios as the mypy profiles.
  Pyright is not used anywhere in the platform.

## 0.13.0
Added (Bazel Rust and Python baseline, [ADR 0025](docs/adr/0025-platform-owned-bazel-configuration.md),
[guide](docs/rust-python-baseline.md); additive: no existing profile, release or consumer build changes):
- Profiles `rust-bazel-9.3`, `python-bazel-9.3` and `rust-python-bazel-9.3`: Bazel 9.3.1 (Bazelisk 1.30.0), rules_rust
  0.74.0 with Rust 1.99.1 (rustc, rust-std, rustfmt, clippy, rustdoc, rust-src, every component archive hash-pinned),
  rules_python 2.4.5 with CPython 3.15.1, Ruff 0.17.2, pytest 9.1.1, pytest-cov 7.1.0, coverage 7.17.0 and mypy 2.4.0
  (hash-locked). The host tools (Rust without Cargo including rust-analyzer, CPython, ruff, Bazelisk) are closure-verified
  on darwin-arm64 and linux-x86_64; Bazel is told to fetch the same bytes.
- A profile with a `bazel` section owns the project's Bazel configuration. `dev-platform toolchain materialize
  [--pinned] [--add-hooks] [--dry-run] [--check]` writes the files the release generates (module declarations, hashes,
  `.bazelrc` policy, rustfmt/clippy/ruff (target py315, the pinned Python minor)/mypy/coverage policy, `dp_py_test`, a Python lint aspect, `dp_rust_library`);
  it refuses foreign files and never edits project-owned ones. `setup` runs it (generated files only; entry lines only
  into files that do not exist) and refuses with the correction otherwise. Conformance (`check`, `toolchain verify`, `setup`) gains a
  `bazel-config` item that fails on missing or edited generated files and on independently maintained settings that
  conflict (second rules_rust/rules_python or toolchain, compiler or Python version pinned elsewhere, other formatter,
  linter, type-checker, pytest or coverage configuration), each with the action that resolves it. New identity strength
  `config-locked`; Bazel-managed tools can be `bound_to` the `bazel-config` item.
- `dev-platform init` adds the checks `bazel.lint` (`--config=dp-lint`) and `bazel.coverage` for a project whose
  configuration is materialized.
- `tools/admit_baseline.py` authors the profiles from the publishers' checksums; `tools/qualify.py` qualifies them
  (fixtures `fixtures-real/baseline-{rust,python,mixed}`), including host-independence (decoy compilers and interpreters
  first on PATH) and must-be-rejected scenarios for conflicting local settings.
- The dependency-graph submission now lists the PyPI tools of the new profiles, so they can raise Dependabot alerts.

Constraints reported by the admission (not worked around): rules_python 2.4.5 knows CPython 3.15.0rc3, so 3.15.1 is
declared to Bazel with `single_version_platform_override` and the same hash-pinned archive as the host; rules_rust 0.74.0
has no hashes for Rust 1.99.1, so the generated module supplies them; its toolchain still fetches (not invokes)
`cargo` and `llvm-tools`.
Added (toolchain manifest, additive; existing profiles and releases are unchanged):
- Source type `rust-components`: individually hashed official Rust component archives (`rustc`, `rust-std`, `rustfmt`,
  `clippy`, `rust-analyzer`, `rust-src`), assembled on the host from each component's `manifest.in`. Components marked
  `bazel_only` (`cargo`, `llvm-tools`) are pinned for the Bazel toolchain declaration and are not installed, so a host
  toolchain built this way has no Cargo. The SBOM and the independent verifier carry one pin per component archive.
- Archive sources accept `into`, extracting under a subdirectory of the tool's version directory (for a `bin/` layout).

## 0.12.1
Fixed:
- `dev-platform.infra/v1`: a provider profile can mark a runner `kind: "hosted"` (optional; absent means `self-hosted`, so
  existing profiles and immutable provider releases are unchanged). Previously every provider runner was treated as
  self-hosted, so a project's `fallback: "none"` did not exclude a GitHub-hosted runner the provider listed. A hosted runner
  must be ephemeral, public-trust and credential-less; the schema, validator, contract documentation and conformance kit
  (`contracts/infra/v1`) carry the field. A profile using `kind` is rejected by earlier releases (unknown key).

## 0.12.0
Single-owner release authority ([ADR 0024](docs/adr/0024-single-owner-release-authority.md)): a release that passes every
check of the independent verifier is `verified`, is published as a normal (latest) GitHub release and installs without
extra flags. Pushing a protected version tag is the release decision; no approval record exists or is read. Releases
up to 0.11.0 keep their policies, records and states (`verified-unaccepted`; 0.2.1 `accepted`) and still need
`--allow-unaccepted`.

Security and toolchains:
- uv 0.12.3 -> 0.13.4 (GHSA-hq85-5cpj-mr62: versions before 0.13.4 trust an emSign root whose intermediate CA keys are
  compromised) in the `dev-platform` profile and the `setup-uv` steps of both workflows.
- Rust 1.97.1 / 1.99.0 -> 1.99.1 in the `rust-bazel-9` and `rust-cargo-1.99` profiles (as mcp-re); new closure digests
  measured on darwin-arm64 and linux-x86_64.

Added:
- `tools/release.py`: `ready` gives one verdict (READY TO RELEASE or BLOCKED: predecessor identity, version policy
  with derived change kinds, tests, lint, docs, two identical builds from an export of the tracked files, predecessor
  continuity); `publish` performs the whole routine release (version and notes pull request, tag, release workflow,
  verification of the published release outside CI, `releases/<version>/` records, Homebrew tap), each pull request
  merged when its required checks pass, resumable and stopping at the first failure; `records` runs the follow-up only.
- Schema `trust-v2` (`dev-platform.trust/v2`: signers, runner and evidence requirements, continuity predecessor).

Declared incompatibilities (0.x minor; consumers reach them only by pinning this release):
- `trust/policy.json` is `dev-platform.trust/v2`; `tools/verify_release.py` refuses a `trust/v1` policy (exit 2, check
  `policy-schema`) and has no `--authorization`. Stable releases are `verified` instead of `verified-unaccepted` or
  `accepted`; the verification record's `acceptance` holds `state`, `reasons` and `not_conferred` only (`verification/v1`
  now allows `verified` and no longer requires `authorization`).
- `tools/install_release.py` admits `verified`; `install()` has no `authorizations` or `allow_unaccepted` parameters and
  `--authorization` is gone. `--allow-unaccepted` is still accepted and has no effect.
- `release.yml` publishes `verified` as a normal release titled `dev-platform <version>`; `.github/workflows/accept.yml`
  is removed. Lifecycle: `independently-verified -> released` for these releases. The 1.0.0 criterion
  `owner-accepted-baseline` is now `stable-baseline-released`.
- An application policy with `require_acceptance` accepts a `verified` platform release (application verifier of this
  release or later), and no platform authorization state is read for it; `tools/verify_platform_current.py` reports
  `verified` (exit 0) for such a release.
- A CLI up to 0.11.0 refuses to reuse an installed release of this version or later from the store ("the pinned
  release is verified; it is not admitted") unless run with `--reverify`; upgrade the CLI.
- The Homebrew formula's caveat no longer mentions `--allow-unaccepted` from this version on (formulas of earlier
  releases render unchanged).

## 0.11.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
Evidence correctness: certification needs a pass in the certifying run, carried evidence is bound to its identity,
and change sets cannot be narrowed by the configuration they change. Infrastructure modules, `dev-platform.infra/v1`,
the resolver protocol and the toolchain manifest are unchanged from 0.10.0.

Added (prototype, informational):
- `dev-platform assurance evaluate --projection FILE [--json]` evaluates claims, units, premises, reviews and closure
  from a `dev-platform.assurance-projection/v1` document (new schemas `assurance-projection-v1` and
  `assurance-evaluation-v1`). Conjunctive support only; `any-of` and other forms are reported `unsupported-form`.
  Producer verdicts are compared, and a disagreement is `projection-inconsistent`, never `PASS`. Read-only: runs and
  writes nothing, and its verdict satisfies no admission, certification, release or acceptance obligation. Draft ADR A
  is not ratified ([details](docs/assurance-evaluation.md)).

Declared incompatibilities (0.x minor; consumers reach them only by pinning 0.11.0):
- Certification requires every configured check to have **passed in the certifying run** (ADR 0006 §6,
  clarified). Previously a `verified` state carried via `--previous` satisfied certification for a check
  not defined for `full`, so a hand-supplied file could certify a check that never ran. Such a check is
  now a certification blocker (`check <id> did not pass in this run (not defined for stage full)`),
  `doctor` warns about it, and application-release assembly refuses a result that lists any check not
  passed. Development-stage carry and `pre-merge` admission are unchanged.
- `--previous` carries evidence only when its **evidence identity** still applies (R-5(i)). Each check entry
  in `result/v1` gains `identity` (component digests, encoding, boundary class) and `reuse`
  (`current | stale | unknown`, cause, carried, boundary, origin); the result gains `previous` (validation
  of the supplied record). All additive. Input digests are taken before the checks run; inputs edited during
  the run withdraw the identity (`identity.unstable`). A record without identities (any record from 0.10.0 or earlier),
  of another project, or malformed carries nothing; it no longer crashes the run. Stale evidence is reported
  with its cause. Nothing carries at `full`. `always`/`periodic` checks never carry. Admission is unchanged.
- A change to the root `dev-platform.toml` selects every non-periodic check: the selection configuration cannot
  narrow the change that edits it (#152, ADR 0006 §3 clarification).
- Change sets have one coordinate system (#153): `--base`/`--staged` give a known set only for a project at its
  git worktree root (a nested project, or a project outside a worktree, is unknown impact: every owed check runs),
  and `--changed` paths are project-relative (`./` is normalized; an absolute, `.`, `..` or escaping path makes
  the whole set unknown).

Fixed:
- `setup` refuses a host the pinned release has no toolchain sources for (Linux arm64, an Intel Mac) by name,
  before provisioning, instead of provisioning nothing and failing verification without saying why. From 0.11.0,
  `toolchain provision` also refuses a tool sourced only for other platforms instead of skipping it.

Documentation:
- [Installation runbook](docs/installation.md): fresh install, upgrade (including from 0.9.0), consumer pins,
  explicit unaccepted opt-in, diagnosis, CLI and release rollback, job-local CI, hosted-only and private
  infrastructure modes, the configuration-repository access boundary. Stale statements corrected in README,
  distribution and consumer quickstart (`check.yml` is an unfinished placeholder; use `consumer-pilot.yml`).

## 0.10.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
One public product with optional, explicitly configured infrastructure capabilities (ADR 0023). Nothing is activated
by installing or upgrading the CLI.

Declared incompatibilities (0.x minor; consumers reach them only by pinning 0.10.0):
- A resolver result with `decision: resolved` and an incomplete or missing `authorization_policy {id, revision, digest}`
  is now `unavailable` (it was accepted). Every known provider already sends the identity.
- `[infra] config_digest_kind` is new; releases before 0.10.0 reject it as an unknown key, so declare it only together
  with a 0.10.0 or later platform pin. Pins without it mean exactly what they meant before.

- Generic provider: release content that is not plain files (symlink, special file, missing directory) is denied as
  `release-unreadable`, as the previous private provider did; `release-tampered` stays for digest mismatches and
  generated files (#140).
- Infrastructure consolidation, stage 1 (ADR 0023, `docs/infra-consolidation.md`): generic configuration releases
  (`infra_release`: CalVer, release-tree digest = `tree_digest`, append-only index, `dev-platform infra release verify`,
  `infra digest releases/<v>`), the current authorization policy that narrows and never grants (`infra_authz`,
  `infra authorization check`) and the generic provider (`infra_provider`, `dev-platform infra resolve --root DIR`).
  Releases in the previous private layout resolve unchanged; results are identical to the previous private provider.
- Infrastructure consolidation, stages 2-3 (`docs/infrastructure.md`): `dev-platform.infra-config/v1`
  (`schemas/infra-config-v1.schema.json`, `infra_config`): runners (github-hosted or self-hosted), runner groups,
  caches, credential references, repositories, admission; fail-closed validation and projection onto per-repository
  `dev-platform.infra/v1` profiles. `dev-platform infra init` (templates `github-hosted`, `self-hosted`; writes files
  only), `infra validate` (config, profile, policy or repository; `--workflows` checks admission and undeclared runner
  groups), `infra profile`, `infra release build`. Validated examples in `examples/infra/`.
- `dev-platform workflow`: the proposed GitHub Actions workflow (reusable `consumer-pilot.yml` at the pinned release,
  GitHub-hosted runner) on stdout or a new file; never commits or enables anything.
- `dev-platform infra store fetch|import|sync|list` (exact selection only, write-once, forward-only policy, sources
  always named), `infra doctor` (identities only), `infra discover` (`gh api` GET only), `infra audit`, `infra drift`.
- Non-activation and boundary regressions (`tests/test_non_activation.py`, `tests/test_public_boundary.py`, `homebrew`
  workflow): installing or running the CLI creates no service, launch agent or home-directory file and reaches GitHub
  only from the explicit commands (GET only); an upgrade leaves an infrastructure store and `[infra]` pins unchanged;
  the public tree carries no secret shapes, private addresses or internal hosts (`DEV_PLATFORM_PRIVATE_DENYLIST` adds
  an organization's own identifiers). `infra doctor --config-release`.
- `[infra] config_digest_kind = "release-tree" | "profile-file"` (optional; omitted means exactly what it meant before).
- The engine refuses a `resolved` result without a complete `authorization_policy {id, revision, digest}`
  (incomplete authorization facts); new resolution conformance cases.

## 0.9.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Homebrew (ADR 0022, `docs/homebrew.md`): `tools/homebrew_formula.py` renders the formula of the public CLI from a release
  identity (release asset URL, archive sha256, test of the installed tree digest; depends on `gh` and `python@3.14`). The tap is
  `syncom-systems/homebrew-dev-platform`. Workflow `homebrew` installs, upgrades (`brew upgrade`) and rolls back (`brew extract`)
  the CLI through a local tap on macOS and Linux and checks that the store and the project pins are unchanged.
- `dev-platform setup`: finds the project (`dev-platform.toml` + `dev-platform.release-pins.json`, upwards), requires the pins to
  agree, installs exactly the pinned release with the trusted installer, verifier and policy taken at the pinned revision and
  checked against the pinned digests (or re-checks an installed one: tree digest and the installer's record; a different tree is
  refused, exit 3, and left untouched), verifies or provisions the profile with the pinned release itself and runs its `doctor`.
  Never writes the project. `--dry-run`, `--json`, `--print-env`, `--reverify`, `--allow-unaccepted`, `--allow-prerelease`.
  Supports pinned releases from 0.8.0.
- Locations (`dev_platform.locations`): `DEV_PLATFORM_HOME`, `DEV_PLATFORM_TOOLCHAINS`, `DEV_PLATFORM_CACHE` (and flags) beside
  `DEV_PLATFORM_STORE`; user-scoped XDG defaults; job-local `$RUNNER_TEMP/dev-platform` in CI. The launcher's store lookup
  honours `DEV_PLATFORM_HOME`.
- `pr-check --facts`: structured `runs_on` group/labels and per-job `non_public_label_sets` (#128), first released here.
- `DEV_PLATFORM_PYTHON`: the launcher re-executes the pinned release on this interpreter (setup exports a profile's provisioned
  python, which the release verifies). `doctor` now delegates to the pinned release like `check` and `explain`.

## 0.8.2 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
Corrective patch for the reusable consumer workflow, found by the first real consumer pilot (NGA, with an inline copy of the workflow):
- `consumer-pilot.yml` gives `gh attestation verify` the job's read-only token (`GH_TOKEN`, a step variable only; checkouts persist no
  credentials). `consumer_run.py` hands the token to the installer alone and removes it from the environment of every other process,
  including the consumer's builds and tests. Before, every install was refused ("attestation-signature ... failed").
- `consumer-pilot.yml` needs only `contents: read`. Attestation moved to the separate `consumer-pilot-attest.yml`, called as its own job
  by a caller that chooses it; the `attest` input is removed (a caller passing it now fails loudly instead of the whole workflow failing at
  startup unless the caller granted `id-token`/`attestations` write). No working caller existed before this release.
- The consumer, the platform source and the evidence are sibling directories (`consumer/`, `platform/`, `evidence/`), so a run no longer
  leaves untracked files in the consumer's tree (which failed certification: "working tree has uncommitted changes"); `consumer_run.py` refuses
  a work, evidence or platform directory inside the consumer directory.
- Regression tests: `tests/test_consumer_workflows.py` and additions to `tests/test_consumer_run.py`.

## 0.8.1 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Fix: `consumer_run.py` ran the Bazel Rust toolchain proof over `//...`; it now examines exactly the consumer's own Bazel check targets
  (`toolchain prove-bazel-rust --target` is repeatable; the build and the Rustc aquery use the same set). A consumer with a large
  workspace (for example one with bare-metal and QEMU targets) would otherwise have been rebuilt in full.
- Consumer evidence verdict renamed `consistent` / `inconsistent` (was `verified` / `rejected`): consistency with the consumer's pins
  is not trustworthy execution. `verification.json` gains `not_established` (job honesty, fabrication, current private-infrastructure
  authorization, the consumer's own gates). The pilot expectations follow.
- `contracts/infra/v1/reference-resolver.py` (a conformance aid showing the resolver wire format) with tests; the reusable workflow
  gets job timeouts (60/10 minutes); docs: verifier anchor lineage (791713d0 -> a2d53075 reconciled across 0.2.1-0.8.0), consumer
  integration limits.

## 0.8.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- `dev-platform pr-check --facts` (#114, #100): per-file triggers/PR reachability and per-job `runs_on` label sets (or unresolved + reason),
  environment, reusable-workflow `uses` and source line, from the same reader that decides admission; opt-in, never changes the decision.
- `dev-platform toolchain prove-bazel-rust` (#111): evidence that Bazel compiles with the declared Rust toolchain, not a host
  installation: Rustc action paths via external repositories, version equals the `MODULE.bazel` declaration, decoy host
  `rustc`/`cargo` never executed in a forced re-execution. Runs Bazel and the Bazel-provided `rustc --version` only (no
  Cargo). Part of the rust-bazel qualification on linux and darwin.
- Deterministic provisioning (#112): `toolchain provision --pinned --verify` realizes the pinned release's profile and verifies it
  against the same manifest in one step (exit 1 unless conformant and certifiable); the identity digest is identical for repeated
  clean provisioning (qualified in the pilot).
- Consumer evidence (#113): `tools/verify_consumer_evidence.py` (independent) checks a result record against the consumer's own
  pins (platform version/tree digest/profile, infra pin, Bazel Rust proof); `tools/consumer_run.py` and the reusable workflow
  `.github/workflows/consumer-pilot.yml` select the pinned release from public data only, provision, execute and verify; the
  pilot gains the public Bazel reference consumer (`fixtures-real/rust-bazel-9`) and attests the evidence bundle.
  `docs/consumer-integration.md` is the runbook (NGA phase 2 stays the owner's decision).
- Consumer-owned infrastructure configuration pin (ADR 0021, #99, #110): `[infra] provider/config_release/config_digest`
  in `dev-platform.toml`; the engine refuses any resolved identity that differs from the pin; untrusted events never call a
  provider and use only a vendored profile whose sha256 equals the pin; trusted events may use an operator-supplied
  resolver. The result record gains `infra`. `dev-platform infra digest` and `infra check-resolution`; conformance cases in
  `contracts/infra/v1/resolution-cases.json`. Breaking for 0.x: an infra profile without a pin is `unpinned` (not used).

## 0.7.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- New authorization provider `github-environment-approval` (ADR 0020): the owner accepts a platform release by approving a run
  of the manual `accept` workflow on the `owner-approval` environment; the workflow attests the resulting record and
  `verify_release.py` verifies it. Trust anchor change (new `verify_release.py` digest); `github-signed-commit` unchanged.

## 0.6.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- A current authorization state that cannot be established is its own result, `indeterminate` (exit 5), no longer folded
  into `failed` (breaking for 0.x consumers that matched `failed`): `approval.authorization_state`
  (`authorized`|`unauthorized`|`indeterminate`|`historical`|`not-established`), coded `currency.reasons`, and the same
  per-candidate `authorization_state` in `rollback select` rejections. `unapproved` keeps meaning the state was read
  and nobody authorizes the release; a defective release stays `failed`.
- Scalable evidence-history audit: up to 10 000 commits are listed (was 500 audited one by one);
  `--audit-state DIR` (verifier, `verify_platform_current.py`, `rollback select`) reuses per-commit facts between runs
  and candidates, saves progress when a run exceeds its budget (`audit-incomplete`), and notices a rewritten history
  (`history-rewritten`). The state caches immutable commit facts only; outcomes with and without it are identical.
- Recovery from deleted records: restore by an approver, or list the removal in the pinned application policy
  (`authorization.acknowledged_removals`); an acknowledged record is read from before its deletion and still counts.
- `docs/owner-acceptance-0.2.1.md` split into agent-executable and owner-only parts.

## 0.5.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Authorization freshness is mandatory (ADR 0019 item 12; breaking for 0.x). `tools/verify_app_release.py` defaults to
  the `operational` purpose: every record in the policy's evidence repository is read at one commit and judged, the
  history is audited for deleted records, and the result is `failed` when the current state cannot be established.
  `--discover-authorizations` is removed (it is no longer optional). `--historical` is the explicit inspection
  purpose: it never yields `approved` (it yields `historical-approval`, exit 4). Records carry `currency`
  (`observed_at`, `valid_until`, evidence commit); `AppVerifier` rejects an `approved` record that is not a fresh
  current-state one. Policy `freshness.max_age_seconds` (default 300).
- Platform acceptance required by an application policy is read as current state too; new
  `tools/verify_platform_current.py` answers "is this platform release currently accepted?" without changing
  `tools/verify_release.py` (the trust anchor).
- Test and qualification doubles model one repository (history, trees, deletions); new end-to-end negative cases:
  a revocation published independently of an old bundle, outage, deleted record, ref moving while read.

## 0.4.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Application policies may require an owner-accepted Dev Platform release (`require_acceptance` +
  `archive_sha256` + `source_revision` in `platform_releases`; schema-added, optional). `verify_app_release.py` and
  `rollback select` re-run the platform verifier (`--platform-*`) and add the `platform-acceptance` check; application
  and platform authority stay separate.
- `--discover-authorizations` (verifier and `rollback select`): records in the evidence repository are judged too, so
  a revocation missing from a bundle still counts. `rollback select` rejections now carry the authorization evidence.
- Qualification: Python profile application-release chain over a hash-locked dependency (`fixtures-real/python-locked`,
  zipapp built with `pip --require-hashes`); rollback refusal suite through the complete bundle/CLI/verifier path
  (`tools/qualify_rollback.py`); live GitHub signature/history qualification against a controlled fixture repository
  (`tools/qualify_live.py`; never reaches `approved`, see ADR 0019 item 13). 0.3.0's qualification claims are unchanged.
- Predecessor continuity: 0.3.0 (digest-pinned in the policy; verified-unaccepted) re-runs the full stage over this source.

## 0.3.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Application-release approval trust (ADR 0019, #52): `tools/verify_app_release.py` (independent, reuses the ADR 0016
  provider registry under a pin) authenticates application approvals, enforces an application-owned policy
  (`dev-platform.app-trust/v1`), binds source/dependencies/platform/toolchain/evidence/artifacts to the exact release
  digest, and handles revocation, supersession and advisories. `rollback select` now requires the pinned verifier
  (`--unauthenticated` is a labelled diagnostic). Shape validator aligned with the verified assertion shape.
- Immutable evidence bundles (`dev-platform evidence bundle|bundle-verify`, `verify_app_release.py --bundle`), retention
  contract, `rollback select --bundle`; qualification `--app-release` rejection cases over real results; pilot assembles
  and refuses to approve (flight). Stray `uv.lock` removed.
- Owner steps for formal acceptance of 0.2.1: `docs/owner-acceptance-0.2.1.md` (nothing pre-made).
- Dependency submission (#6): `dev-platform dependency-snapshot` and a workflow submit toolchain tool components to GitHub's
  dependency graph; observed on this repository: accepted, components listed, 0 alerts (only pypi purls can alert).
- Predecessor continuity: 0.2.1 (digest-pinned in the policy; verified-unaccepted) re-runs the full stage over this source.

## 0.2.1 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Installer consumes the predecessor-continuity record (found by independent verification of 0.2.0, whose tag's
  installer could not install it). 0.2.0 is retained verified-unaccepted and superseded.

## 0.2.0 (stable candidate; verified-unaccepted until an authenticated owner authorization exists)
- Declared host requirements (#60): `[[host]]` in dev-platform.toml, recorded in environment evidence (gates
  conformance, never raises assurance). New profiles `rust-cargo-1.99` and `rust-bazel-9` (qualified in CI).
  `toolchain provision [--pinned]`; `init` derives checks from build markers; `infra check|event-trust`;
  consumer pilot harness (flight); docs: infra integration, consumer quickstart, nga pilot plan.
- Advisory impact analysis (#7): version ranges, severity enum, `affected --impact [--github REPO]` with fix/patch/
  upgrade actions per release and pinned consumers. Proposals only.
- Predecessor continuity (#4): `tools/run_continuity.py`, `dev-platform.continuity/v1`, `continuity` check in the
  verifier, release workflow jobs `continuity`/`attest-continuity`; policy pins v0.1.2 as predecessor. Evidence only.
- ADR 0018: single admission policy contract. `runners.event_trust` (normative), optional `admission` section in
  `dev-platform.infra/v1`, `dev-platform pr-check` (violations / incomplete / indicators), conformance cases.
- Lifecycle: unauthenticated notices only suspend (warning); revocation is read from the pinned verifier's
  authenticated evidence. `plan queue`: milestone priority is not an exclusive queue.
- Release planning (ADR 0017): `dev-platform plan` (readiness, assign, version-check, patches, notes, manifest,
  state), `planning/release-policy.json` (versioning policy, assurance profiles), lifecycle state machine with no
  edge to `accepted` (observed only from a run of the pinned verifier), `release-plan.yml` (assign/report only),
  release milestones v0.1.3/v0.2.0/v0.3.0 and a Project; M1-M6 retired. v0.1.2 stays verified-unaccepted.
- Authorization trust boundary (ADR 0016): the verifier authenticates authorization records through a provider
  registry, enforces an approver registry in the trust policy, scope, validity, supersession and revocation; the
  separate validate_authorization tool is removed. Policy switch to waive authorization removed. Fixes the defect
  that any non-git provider name sufficed for `accepted` (v0.1.0 had no authorization and is unaffected).
- Infra contract conformance kit (contracts/infra/v1) and strict profile validation; schema $ids use the real org.
- Version-keyed toolchain store; scrubbed-environment execution mode (docs/execution-isolation.md).
- Owner acceptance packet for 0.1.0 (releases/0.1.0/ACCEPTANCE-PACKET.md), unsigned authorization template, and
  tools/validate_authorization.py (pinned-owner signed-commit validation). No authorization exists; 0.1.0 stays
  verified-unaccepted.
- 0.1.0 stable candidate (published verified-unaccepted; acceptance needs an owner authorization record):
  environment evidence states non-hermetic scope and limitations (also copied into certification);
  verifier checks the attested build-environment record against the manifest pins; policy requires
  it; workflow publishes by verified state, never implying acceptance. Supported scope is exactly the
  qualified combinations; others fail closed to diagnostic.
- 0.1.0-rc.4 candidate (0.1.0-rc.3 failed at the build-environment gate, see releases/0.1.0-rc.3): tool identity by runtime closure (`closure-verified`; a bare executable digest no
  longer certifies), pinned hash-locked release-profile environment, SBOM correspondence and SBOM
  attestation verification, trusted installer (`tools/install_release.py`), real Bazel/rules_rust and
  CPython qualification in CI, Bazel binary pinned and enforced at execution, Dependabot for Actions and
  pip, immutable-release probe and post-publish assertion. ADR 0015.
- 0.1.0-rc.2 pre-release: first fully verified pipeline run (see releases/0.1.0-rc.2).
- 0.1.0-rc.1 pre-release: first exercise of the release pipeline (never accepted; see docs/release-trust.md).
- Revision 2: releases are environments (toolchain manifest + profiles + SBOM, `release build|verify`);
  environment verification recorded in results (`environment`, breaking pre-release change to
  `dev-platform.result/v1`); verified-snapshot launcher closes the verify/exec race; self-hosted
  results are no longer certifiable; `platform.profile` is required in pins; app-release,
  authorization and advisory record contracts with `validate` and `affected`; ADRs 0010-0014
  (supersede 0009, part of 0003).
- Foundation: config schema v1, result schema v1, infra profile v1, launcher with digest-pinned
  releases, detection, selection and evidence state machine, adapters (bazel, python, cargo, exec),
  logical runner routing, CLI (init, detect, doctor, explain, check, digest), ADRs 0001-0009.
