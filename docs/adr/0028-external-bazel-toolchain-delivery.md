# 0028 External Bazel toolchain delivery: the project stays root, the launcher enforces

Status: Proposed — candidate architecture (owner decision, 2026-11-03, issue #190: Design C is the authorized
direction; Design B is not). The prototype (`dev-platform bazel`, `src/dev_platform/bazel_launch.py`) is
experimental: not released, not used by any consumer, and not yet part of `check`, `setup` or a workflow.

## Context
ADR 0027 removed every platform-generated file from consuming repositories, which left Bazel profiles without a
delivery path: the toolchain declaration, formatter and lint policy that ADR 0025 rendered into `dev-platform/` and
hooked into `MODULE.bazel` and `.bazelrc` may no longer be written there. Earlier decisions recorded in #190 bound the
replacement: Dev Platform owns the tested toolchains and the core rule versions (`rules_rust`, `rules_python`); each
project owns its `dependencies.toml`, which is the only authority for application package versions; each project
keeps its own `MODULE.bazel` and `.bazelrc`; Dev Platform writes no project-owned file. Bazel itself decides who may
configure a module extension: rules_rust's `rust` extension reads `rust.toolchain` tags from the root module only
(`root.tags.toolchain or rules_rust.tags.toolchain`).

Three designs were tested on Bazel 9.3.1 and rules_rust 0.74.0, the last two against unmodified NGA (12d20ca) in
isolated scratch directories (#190, comments of 2026-11-02 and 2026-11-03).

## Decision
1. **The project stays the Bazel root module.** Its `MODULE.bazel`, `.bazelrc`, `MODULE.bazel.lock`, overrides of
   modules the platform does not own, development dependencies, custom rules, module extensions and toolchain
   registrations for toolchain types the platform does not provide are its own and keep working. Labels and output
   paths do not change.
2. **The platform supplies its verified rules_rust as a module override from outside the repository.** On every
   verified run the launcher derives the tree from the release's pins: the BCR `source.json` whose hash the manifest
   pins, the archive by the integrity that file names (a `source.json` with registry patches or overlays is refused),
   extracted into the platform cache and changed in three anchored places, each required to occur exactly once
   (otherwise the source is not the qualified one and the run fails):
   - rules_rust's own `MODULE.bazel` declares the release's Rust toolchain (version, rustfmt version, every component
     sha256, the extra target triples, the default edition), which therefore applies when the root declares none;
   - its `rust` extension accepts a root `rust.toolchain` only when every platform-owned attribute equals that
     declaration (its `edition` may differ) and refuses any root `rust.repository_set`: a conflicting root declaration
     fails closed with a Dev Platform message instead of selecting another compiler;
   - a policy package `@@rules_rust+//dev_platform` carries `rustfmt.toml`, `clippy.toml` and the cross-compilation
     platforms (`aarch64_none`).
   A cached tree is used only when its tree digest equals the fresh derivation; otherwise it is replaced and the run
   record says `repaired`. The platform carries and qualifies this patched rules_rust for each release.
3. **The launcher controls the effective arguments.** `dev-platform bazel [launcher options] <command> [args]`
   (`build`, `test`, `coverage`, `run`, `cquery`, `aquery`, `info`, `query`, and `lint`):
   - startup: `--nohome_rc --nosystem_rc --bazelrc=<platform rc>`; the project's `.bazelrc` is read by Bazel
     unchanged, the platform's rc after it;
   - before Bazel runs, the project's `.bazelrc` and every file it imports or try-imports (all sections and configs,
     continuation lines joined) and the command line are scanned; a run is refused, nothing executed, when they name
     `--override_repository`, `--override_module`, `--inject_repository`, `--extra_toolchains`, `--registry`,
     `--lockfile_mode`, `--vendor_dir`, `--repository_cache`, `--distdir`, a rules_rust toolchain setting
     (`//rust/toolchain/...`), `--noenable_bzlmod` or `--enable_workspace`;
   - after the user's options the launcher appends its own, so that each wins over any earlier value:
     `--override_module=rules_rust=<derived tree>`, `--lockfile_mode=error`,
     `--extra_toolchains=@@rules_rust++rust+rust_toolchains//:all` (the platform's toolchains are considered before
     any registration of the root module), and the lint policy settings (`rustfmt.toml`, `clippy.toml`,
     `clippy_flags=-D,warnings`); Bazel locations (`--output_user_root`, `--repository_cache`) are launcher options,
     never the project's;
   - Bazelisk is held to the release: `USE_BAZEL_VERSION` and `BAZELISK_VERIFY_SHA256` (ADR 0025's binary pin) are
     set, `BAZELISK_SKIP_WRAPPER` disables a project `tools/bazel` wrapper, and a Bazel that reports another version is
     refused.
4. **The repository-override vulnerability is closed at the argument boundary and re-checked in the result.**
   `--override_repository` on a platform toolchain repository swapped the compiler while every repository name still
   pointed at the platform (#190). It is refused wherever it can come from (project rc chain, command line; user and
   system rc files are not read; the wrapper is skipped). `--audit` reads the version from every rustc binary the
   Rustc actions name, never from the repository name, and requires the platform's toolchain repositories.
5. **Verified execution is a record, not a command name.** A run is verified Dev Platform execution exactly when
   `dev-platform bazel` produced a record (`dev-platform.bazel-run/v1`) with `verified: true`: Bazel exited 0, no
   refusal, the derived rules_rust tree and its digest, the lockfile unchanged under `--lockfile_mode=error`, the
   Bazel version, the effective argv, and for `lint` and `--audit` their evidence. Plain `bazel` in the same repository
   is the project's own build: it produces no record and is never reported as verified, whatever it prints (with no
   root declaration it uses rules_rust's default compiler). CI follows the same rule: a job may state a
   platform-verified result only from a record with `verified: true` produced in that job by the release's
   `dev-platform bazel`, uploaded with the job's evidence; steps that call `bazel` directly are project checks.
   Wiring the record into `check`, the result record and the consumer workflow is a later change.
6. **The committed lockfile is verified, never updated.** Every run passes `--lockfile_mode=error`; a project without
   `MODULE.bazel.lock` is refused with the instruction to create and commit one. The lock is the project's: it creates
   and updates it itself (`bazel mod deps --lockfile_mode=update`); a lock produced that way verifies under the
   launcher (it differs from a launcher-produced one only by the two rules_rust registry entries the override makes
   unnecessary). Error mode refuses a registry file whose content differs from the lock and a module the lock lacks,
   including one the platform's rules_rust would add; `--lockfile_mode=off` accepts both silently and is not used.
7. **Lint must have checked something, and everything it should.** `dev-platform bazel lint <patterns>` builds with
   rules_rust's rustfmt and clippy aspects and the Build Event Protocol. For every applicable Rust target (library,
   binary, test, proc-macro, shared and static library) and each of clippy and rustfmt the record states `checked` (a
   result file), `skipped` (not built in this configuration, e.g. a bare-metal target in a host build), `opted-out`
   (a rules_rust skip tag), `failed`, `not-run` (the build stopped first), or for rustfmt only `no-source` (no hand-written source file, established by a
   query). A run fails when either check produced no result for any target, or when a target completed without a
   result and without one of those reasons: the false green of #190, where the aspects skipped every target, fails.
8. **Compiler versus language settings.** The compiler, its components and hashes, rules_rust, the target standard
   libraries and the lint and format policy are the platform's. The edition chosen per target (`edition = ...`),
   `rustc_flags`, target platforms and constraints, and tools outside the Rust toolchain type are the project's.

## Demonstrated (prototype on unmodified NGA 12d20ca, macOS arm64, Bazel 9.3.1; evidence in #190)
Every run used the same derived rules_rust tree (tree digest `eb1446ddeb1b02b3…`, from archive sha256 `d8bcc1e1…`,
`source.json` sha256 `04eac31b…`), Bazel 9.3.1 with the pinned binary digest, and left `MODULE.bazel.lock` and every
project file byte-identical (Bazel created its usual `bazel-*` links).

| Run | Result |
|---|---|
| `test` of 309 representative targets (all non-mutation tests, a mutation sample, kernel QEMU, Kani, TLA+) | 295 pass, 14 fail: the identical failure set of NGA's own root build (8 expected mutation kills, 6 failures already on `main`); not verified (Bazel exit 3), as it must be |
| `build --audit` host, and `--config=dp-aarch64-none` / NGA's own `--config=kernel` for `nga-kernel` | verified; every rustc is rustc 1.99.1 from `rules_rust++rust+…aarch64-apple-darwin…` or `…aarch64-unknown-none-softfloat…` |
| `lint //...` | 165 applicable targets: clippy 159 checked, 1 opted out, 1 skipped (bare-metal), 4 failed (clippy findings that NGA's own build also reports); rustfmt 159 checked, 5 without a hand-written source, 1 skipped; not verified |
| `lint` of nga-abi, nga-kcore, nga-cap, the mutation package | verified: clippy 93 checked, rustfmt 92 checked, the rest accounted for |
| `lint --config=dp-aarch64-none //crates/kernel:nga-kernel` | not verified: rustfmt reports formatting differences in `crates/kernel/src/` that NGA's host `fmt //...` never checks (the kernel is incompatible with the host and skipped); confirmed with NGA's own configuration |

Negative tests (scratch root project with its own lock):

| Attempt | Result |
|---|---|
| root registers its own rustc 1.98.0 toolchain (from rules_rust's internal `rust_repository_set`) | launcher: verified, rustc 1.99.1; plain `bazel` in the same project: 1.98.0 (no record) |
| root `rust.toolchain(versions = ["1.80.0"])` | fails closed: `dev-platform: rust.toolchain(...) in the root module differs from the verified toolchain` |
| `.bazelrc` `common --override_repository=<platform toolchain repository>=<dir>` | refused before Bazel runs (exit 2), file and line named |
| `.bazelrc` `build:ci --extra_toolchains=...`; `try-import` of a file with `--override_module` | refused (exit 2) |
| command line `--override_repository=...`, `--lockfile_mode=update` | refused (exit 2) |
| project `tools/bazel` wrapper that appends `--override_repository` | not executed; verified, rustc 1.99.1 |
| `.bazelversion` 7.4.1 | Bazel 9.3.1 runs |
| derived tree in the cache edited (the fail-closed check disabled) | detected and replaced (`repaired: true`) |
| module added without updating the lock | Bazel refuses (`Missing checksum ... not permitted with --lockfile_mode=error`); not verified |
| no `MODULE.bazel.lock` | refused with the instruction to create and commit one |
| `lint` of an unformatted target | not verified; after formatting: clippy and rustfmt `checked`, verified |

## Limitations (outstanding)
- **Enforcement holds only through the launcher.** Plain `bazel` cannot be prevented; it is made distinguishable
  (decision 5), not impossible.
- **Cache trust.** The derived rules_rust tree is re-derived and compared on every run, but repositories Bazel itself
  fetches (the toolchain archives) are reused from the repository cache's content store without re-verification;
  the launcher chooses that cache, the project cannot. A tampered repository-cache entry was shown in #190 to change
  code silently. `--audit` checks the rustc version, not every byte.
- **A release-pinned digest of the derived tree** (computed during qualification) would remove the need to re-derive
  for trust; today the trust comes from the pinned sources and the anchored derivation.
- **Bazelisk** is the one on `PATH` (or `--bazel`); the launcher sets the release's version and binary digest but does
  not yet locate the release's provisioned Bazelisk itself.
- **Bazel's convenience symlinks** (`bazel-bin`, `bazel-out`, ...) are created in the project as with plain Bazel
  (NGA's scripts use them); `--symlink_prefix` can move them. Whether they count as writes under ADR 0027 is an owner
  decision.
- **Lint scope:** `lint` covers rustfmt and clippy for Rust; Python (ruff, ty) is not part of the prototype.
- **Not covered:** Python (rules_python), `dependencies.toml` and application dependency locks (#190, later), Linux
  hosts, `check`/workflow integration, remote execution and remote caches.
- **Platform changes to rules_rust's module dependencies** would invalidate every project lock (decision 6); the
  derivation keeps upstream's dependencies unchanged.

## Rejected alternatives
- **A: the project root declares `bazel_dep(dev_platform)` and the toolchain comes from the platform module.** Builds
  green with rustc 1.98.0, rules_rust's default: the `rust` extension honours toolchain tags only from the root
  module, so the platform module's declaration is ignored silently and the cross target is lost.
- **B: a platform-generated root module outside the repository, the project as a dependency.** Enforced by Bazel's
  root-only rules, but on NGA 16 test targets and every one of the 2,508 mutation targets broke (main-repository path
  assumptions: `short_path` checks, `$(BINDIR)/crates/...` linker arguments, runfiles reads), labels and output paths
  changed (`@nga//...`, `bazel-bin/external/nga+/...`), the project lost its overrides, `dev_dependency` and native
  `.bazelrc`, and rules_rust's clippy and rustfmt aspects silently skip every target outside the main repository: a
  green lint that checked nothing.

## Consequences
- A Bazel-profile project needs no platform file but `dev-platform.toml`; its Bazel files stay its own. The legacy
  `dev-platform/` directory and hook lines (ADR 0025) become unnecessary; removing them is the project's change.
- Each release qualifies one patched rules_rust per profile; a rules_rust bump re-qualifies the anchors.
- The `rust.toolchain` a project may still declare must equal the release's or be removed: a mismatch fails the build.
