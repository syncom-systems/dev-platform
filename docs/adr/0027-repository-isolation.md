# 0027 Repository isolation

Status: Proposed (owner directive, 2026-10-25: Dev Platform and Infra are installed externally; the only
platform-managed file in a consuming repository is `dev-platform.toml`; completion decisions 2026-10-26, below; the owner accepted the architecture, ratification is a separate owner act).

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
   are all or none. `dev-platform.release-pins.json` is read only for a project whose toml lacks them (a pin before
   0.17.0), never written.
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
- The `bootstrap` job of `pre-merge.yml` (older published releases with Bazel profiles installed by the current
  launcher) is retired: it required `setup` to write Bazel files into the project. The bootstrap-compatibility gate of
  `tools/release.py ready` still installs and runs the candidate through the launcher.
- The CI path (`consumer-pilot.yml`, `tools/consumer_run.py`) still reads `dev-platform.release-pins.json` and
  needs a workflow in the repository, so it is outside the isolation contract until it is reworked.
- Bazel-profile projects lose platform-managed Bazel integration until it is delivered externally.

## Completion decisions (v0.17.0, owner 2026-10-26)
6. **Output-path guard** (`pathguard.py`). Every destination a caller chooses (output flags, evidence and store
   locations, toolchain destinations, installation roots, `DEV_PLATFORM_*` and XDG overrides, relative defaults such as
   `toolchain provision --dest .devenv`) is resolved with `realpath` and refused, exit 2 and nothing written, when it lies
   inside the working tree or the Git metadata (linked worktrees included) of a consuming project: the directory of the
   nearest `dev-platform.toml` from `--project` and from the working directory, and the Git working tree containing it. A
   pin file that cannot be parsed still protects. The destination is judged too: any ancestor holding a
   `dev-platform.toml`, and any `.git` component, is refused, so a command run from elsewhere cannot write into another
   project or into Git metadata. Containment is decided by file identity (`samefile`), not path text (letter case on a
   case-insensitive volume, links), and an existing file hard-linked into a protected tree is refused. The one exemption is
   the platform's own repository, and `self_hosted = true` alone does not make a repository that: the `dev-platform.toml`
   must also be the checkout the running code comes from (`<root>/src/dev_platform` is this very package, neither it nor
   `src` a link), so a consuming project or a cloned repository claiming the mode gets no privilege. No environment variable or flag takes part: a release the checkout launches is not the checkout's code, so qualification writes under the platform cache directory, outside it. `dev-platform.toml`
   written by `install`, `update --write` and `init` is the contract itself and does not pass the guard. A symbolic-link
   `dev-platform.toml` is never written through. Check-then-use only: a concurrent swap is not defended.
   Read-only consumer commands do not write Git metadata either: the engine's git calls use `--no-optional-locks` and
   `git diff` runs on a private copy of the index outside the repository (it rewrites `.git/index` otherwise).
7. **`toolchain materialize` writes nothing into a project.** `--check` and `--dry-run` remain; any writing mode is refused
   with the correction. A directory that is not a project (no `dev-platform.toml`, or the platform's own repository) can
   still be rendered into, which keeps the qualification tool working (it calls the library in process).
8. **Legacy files are reported, never consumed.** `.dev-platform/infra-profile.json` is no longer passed to `doctor`
   implicitly. `dev-platform.release-pins.json`, that file, a `dev-platform/` Bazel directory and the platform's entry lines in
   `MODULE.bazel` and `.bazelrc` are listed by `setup`, `install` and `update` and are never changed or deleted. The pins file is
   read only for a pin not yet migrated.
9. **One infrastructure store location**, `<data root>/infra` (`infra_store.location`), for `install` and the `infra`
   commands; the platform store overrides never move it (before, `install` derived it from the parent of the release store).
10. **Explicit versions.** A first installation requires `--version`; it never defaults to the bootstrap CLI's version. The
    dry-run and update output state the bootstrap CLI and the release that executes separately.
11. **Independent infrastructure digest.** `install` and `update` take `--infra-digest`, supplied independently of
    `--infra-source`; the received release must equal it, the source's index must name it, and the release and its index entry
    must implement `dev-platform.infra/v1`. The optional `[infra].source` records where to obtain the release and is not part of
    any result's identity; it is not an authority for authenticity.
12. **Untrusted events** get `public-default` from the generic provider with no policy needed or read; a trusted event
    without a valid policy resolves nothing. A `resolved` result is a logical resolution, not verified runner enforcement.
13. **Migration** from a pin before 0.17.0 is `dev-platform update --to <0.17.0 or later> --write`: it replaces `[platform]`
    (identity keys added, profile kept), keeps every other line and every other file, and is idempotent. A project with a Bazel
    profile can migrate its pin but not its generated Bazel files (blocked, below).

Blocked or deferred, recorded rather than worked around: platform-managed Bazel integration (a Bazel profile cannot be
prepared unless the project already holds `dev-platform/generated.json`, and files written by an older release cannot be
regenerated), the central CI/workflow path (`consumer-pilot.yml`, `tools/consumer_run.py` and `workflow` still use the pins
file), the hook hierarchy, runner enforcement verification (#141).
