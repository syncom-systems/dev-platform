# 0027 Repository isolation

Status: Proposed (owner directive, 2026-10-25: Dev Platform and Infra are installed externally; the only
platform-managed file in a consuming repository is `dev-platform.toml`).

## Context
Until 0.16.0 a consuming project held, besides `dev-platform.toml`, `dev-platform.release-pins.json` (the release
identity), optionally `.dev-platform/infra-profile.json`, a proposed workflow, and, for Bazel profiles,
`dev-platform/` plus hook lines in `MODULE.bazel` and `.bazelrc`, which `setup` itself wrote (ADR 0025).
Installing therefore changed the repository, and a repository could not be reviewed for what it pinned without
reading several platform-generated files.

## Decision
1. **One file.** `dev-platform.toml` holds the whole pin: `[platform]` carries `version`, `sha256` (tree digest),
   `profile`, `source_revision`, `archive_sha256` and `[platform.verifier_pins]` (`verify_release`, `trust_policy`,
   `install_release`: sha256 of the three tools the installer trusts); the optional `[infra]` carries the exact
   configuration release and its release-tree digest (unchanged from ADR 0021/0023). The three identity keys
   are all or none; `release-pins.json` is no longer read.
2. **Everything else is external.** Releases, toolchains, caches and the infrastructure store live under the user's
   data directory (`~/.local/share/dev-platform`, `~/.cache/dev-platform`; ADR 0022). `setup`, `doctor`, `check`
   and `explain` write nothing into the project tree.
3. **`install` creates, `update` proposes.** `dev-platform install` writes `dev-platform.toml` when it does not exist
   (identity read from the platform's published `releases/<version>/identity.json`, required to name the commit its tag
   names; infrastructure identity from the configuration repository's own index, the received tree checked against
   it) and then runs `setup` for what the file pins. An existing file is never changed by `install`, so repeating
   it is idempotent. `dev-platform update` renders a diff of the same file only; `--write` applies it.
   Neither command trusts what it reads: the trusted installer still verifies the archive against the pins and
   the attestations, and the infrastructure store against the indexed digest.
4. **No generated repository files.** Preparing a toolchain profile never writes into the project. A Bazel profile
   is verified against the platform's generated Bazel files inside the repository (ADR 0025); nothing may install
   them any more, so such a profile is refused by `toolchain prepare` unless the project already holds
   `dev-platform/generated.json` (placed there by its owner; still never written by the platform). Closing that
   gap needs the Bazel configuration delivered from outside the repository and is not part of this decision.
5. **Older releases.** A project can pin only 0.17.0 or later: older releases do not know the identity keys, and
   0.15.0 and 0.16.x write Bazel files during `toolchain prepare`; `setup` refuses a pin in that range and names
   the update.

## Consequences
- A reviewer sees the complete pin in one file; an update is a diff of that file.
- The CI path (`consumer-pilot.yml`, `tools/consumer_run.py`) still reads `dev-platform.release-pins.json` and
  needs a workflow in the repository, so it is outside the isolation contract until it is reworked.
- Bazel-profile projects lose platform-managed Bazel integration until it is delivered externally.
