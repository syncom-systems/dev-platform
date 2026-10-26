# Installation, upgrade and rollback (runbook)

One public product: the `dev-platform` CLI. It works with no private infrastructure repository, credential, runner
inventory or organization-specific configuration. Private infrastructure is an optional, separately pinned attachment
([below](#private-infrastructure-mode-optional)); it never needs a second CLI or a private Python package.

Two things are installed, and only the second decides what a project runs ([homebrew.md](homebrew.md) has the details):

| | What | Selected by | Changed by | Rolled back by |
|---|---|---|---|---|
| **CLI** | `dev-platform`, a verifying launcher | Homebrew | `brew upgrade` | `brew extract` of the older formula |
| **Platform release** | the exact release a project runs, plus its toolchains | the project's committed pins | a reviewed edit of the pins | reverting that edit |

`dev-platform --version` is the CLI. `dev-platform doctor` in a project reports the release it runs
(`platform resolved: mode=pinned version=<pinned>`). A CLI upgrade never changes the second line.

## Supported hosts
| Host | CLI | `setup` (release + toolchains) |
|---|---|---|
| macOS, Apple silicon | yes | yes |
| Linux x86_64 (Homebrew on Linux) | yes | yes |
| Linux arm64, macOS Intel | yes | no: no release ships toolchain sources for them. `setup` refuses by name ("no pinned source of ... for this host"; CLIs up to 0.10.0 refuse later, at toolchain verification, without naming the host) |

Requirements: Homebrew (it brings `gh` and `python@3.14`), and `gh auth login` once (the trusted installer verifies release
attestations with `gh`; any GitHub account can read the public attestations). No sudo; nothing outside the Homebrew prefix,
`~/.local/share/dev-platform` and `~/.cache/dev-platform`.

## 1. Fresh installation
```sh
brew install syncom-systems/dev-platform/dev-platform   # the fully qualified name: trusts this one formula
gh auth login                                           # once
dev-platform --version                                  # dev-platform <CLI version>
```
Installing creates no service, launch agent, scheduled job, store, configuration or credential, and changes no GitHub
setting ([what installing never does](homebrew.md#what-installing-never-does)).

## 2. A project's pinned release
The project holds exactly one platform file, `dev-platform.toml` (repository isolation, [ADR 0027](adr/0027-repository-isolation.md)):
the exact releases it runs. Installing writes nothing else into the repository; releases, toolchains and the
infrastructure store live under `~/.local/share/dev-platform` and `~/.cache/dev-platform`. A project can pin 0.17.0 or later.

**First installation** (creates `dev-platform.toml`, then installs and verifies what it pins):
```sh
cd my-project
dev-platform install --version 0.17.0 --profile <toolchain profile>
# with an infrastructure configuration release (exact; there is no "latest"):
dev-platform install --version 0.17.0 --profile <profile> \
  --infra-source OWNER/CONFIG-REPO --infra-provider <name> --infra-release 2026.10.2 \
  --infra-digest sha256:<release-tree digest from the configuration owner's release notice>
```
`--version` is required on a first installation and never defaults to the CLI's own version: the CLI is only the
bootstrap that verifies and launches the release that runs, and `--dry-run` prints both (`bootstrap CLI` and
`executes release`). The platform identity is read from the published `releases/<version>/identity.json` (which must name
the commit its tag names). `--infra-digest` is supplied independently of `--infra-source`: a digest read from the same
mutable source as the release would only prove that the source agrees with itself. The received release must equal it,
the source's index must name it, and the release must implement `dev-platform.infra/v1`; anything else is refused and
nothing is written. `install` never changes an existing `dev-platform.toml`: run again it verifies and reuses
(idempotent), and `--dry-run` writes nothing.

Format of the pin (the three `[platform]` identity keys are all present or all absent; `[infra]` is optional):
```toml
[platform]
version = "0.17.0"
sha256 = "<tree digest>"            # releases/<version>/identity.json tree_digest_pin
profile = "<toolchain profile>"
source_revision = "<40 hex>"        # the release commit
archive_sha256 = "<64 hex>"

[platform.verifier_pins]            # sha256 of the tools the trusted installer takes at source_revision
verify_release = "<64 hex>"
trust_policy = "<64 hex>"
install_release = "<64 hex>"

[infra]                             # optional; exact, no ranges
provider = "<name>"
config_release = "2026.10.2"
config_digest = "sha256:<release-tree digest>"
config_digest_kind = "release-tree"
source = "OWNER/CONFIG-REPO"        # optional: where to obtain the release; never an authority (the digest is)
```
`source` only tells `install` where to fetch a release that is missing from the store; it is not part of any result's
identity, and a held release is never fetched again by `install`.

Then, in the project root (`install` and `setup` also find the project from a subdirectory; `doctor` and `check` default to the
current directory, so run them from the root or pass `--project <root>`). `install` already ran `setup`; run it directly to
re-verify without any of the creation options:
```sh
dev-platform setup --dry-run                                  # what it would do: no network, no writes
dev-platform setup                                           # installs exactly the pinned release, provisions, runs its doctor
eval "$(dev-platform setup --print-env)"                     # this shell: DEV_PLATFORM_STORE, DEV_PLATFORM_PYTHON, PATH
dev-platform doctor                                           # platform resolved: mode=pinned version=<pinned>
dev-platform check --stage pre-merge --base origin/main
```
From 0.12.0 a published release is **verified** (every check of the independent verifier passed) and needs no flag.
Releases up to 0.11.0 are **verified-unaccepted**: pinning one needs `--allow-unaccepted` on every `setup` (without it
`setup` refuses, installs nothing and `--print-env` prints no exports). A pre-release needs `--allow-prerelease`.
Reusing an installed 0.12.0+ release needs a CLI of 0.12.0 or later (older CLIs refuse it unless `--reverify`).

`setup` is idempotent: a second run reverifies and downloads nothing (`release: present`, `toolchain: reused`). Several
releases coexist; each project gets exactly its own.

## 3. Upgrading the CLI (including from 0.9.0)
```sh
brew update && brew upgrade dev-platform    # CLI only
dev-platform --version
dev-platform setup                          # in a project: release present, toolchain reused, nothing downloaded
```
An upgrade leaves every project's pins, every installed release and toolchain, the infrastructure store and every
`[infra]` selection byte for byte unchanged, and the newer CLI runs and resolves all of them. `brew pin dev-platform` holds the
current CLI.

**From a CLI up to 0.14.0** this upgrade is the one-time step to a release that uses newer manifest features: those CLIs
validate a release with their own schema and answer `invalid release` (0.12.1, 0.13.0) or `release X is newer than this
dev-platform CLI` (0.14.0). From 0.15.0 the CLI only verifies and runs the pinned release, which validates itself
([distribution](distribution.md#bootstrap-contract-and-upgrading-the-cli)), so no later release can strand it.

## 4. Upgrading a project's release
`dev-platform update` proposes the change to the same file and never writes without `--write`:
```sh
dev-platform update --to 0.17.1                              # prints the diff of dev-platform.toml; nothing written
dev-platform update --to 0.17.1 --infra-source OWNER/CONFIG-REPO --infra-release 2026.10.3 \
  --infra-digest sha256:<release-tree digest>
dev-platform update --to 0.17.1 --write                      # apply it (review and commit the file)
dev-platform install                                         # install and verify what the file now pins
```
Only the `[platform]` and `[infra]` tables are replaced; every other line (the project's own configuration and its
comments) is kept. A toolchain change is always a new release. A release that adds a configuration key (for example
`[infra] config_digest_kind`, 0.10.0) is required before the project may use that key.

### Migrating a pin from before 0.17.0
A project pinned to 0.8.0 to 0.14.x (identity in `dev-platform.release-pins.json`, or in neither file) moves with one
command; it writes `dev-platform.toml` and nothing else:
```sh
dev-platform update --to 0.17.0                # the diff, the bootstrap/executing identities and any legacy files; no write
dev-platform update --to 0.17.0 --write        # writes dev-platform.toml only
dev-platform install                           # installs and verifies what the file now pins
```
`--to` is required and must be 0.17.0 or later; 0.15.0 and 0.16.x are refused (their toolchain preparation writes into the
project). The `[project]`, `[[check]]`, `[impact]`, `[runner.*]` tables and every comment stay byte for byte; an existing
`[infra]` pin is kept. Until `--write` is run, a project still pinned before 0.17.0 keeps working from its pins file, which
is read and never written. Afterwards `dev-platform.toml` alone is the pin and the legacy files are ignored.

**Legacy repository files** (`dev-platform.release-pins.json`, `.dev-platform/infra-profile.json`, a `dev-platform/` Bazel
directory, the platform's entry lines in `MODULE.bazel` and `.bazelrc`) are reported by `update`, `install` and `setup`
and are never read as an operational input (except the pins file of a not yet migrated pin), changed or deleted.
Removing them is the project owner's decision. A vendored infra profile is used only when passed explicitly with
`--infra-profile`.

**Blocked: a project whose profile is a Bazel profile** (for example `rust-aarch64-none-bazel-9.3`). Its pin migrates, but
`setup` verifies the platform's generated Bazel files inside the repository, which can no longer be installed or refreshed
by the platform; the project's existing `dev-platform/` files, written by an older release, are verified as they are and
conflict with 0.17.0 unless regenerated. Regenerating them writes into the repository, which this milestone does not do
(next section).

## 5. Rollback
**CLI** (Homebrew keeps no old versions; the tap's history does):
```sh
brew tap-new --no-git local/dev-platform-versions                    # once
brew extract --version=<old> syncom-systems/dev-platform/dev-platform local/dev-platform-versions
brew unlink dev-platform && brew install local/dev-platform-versions/dev-platform@<old>
# forward again:
brew uninstall dev-platform@<old> && brew link dev-platform
```
**Project release:** revert the pin change (to 0.17.0 or later; earlier releases write into the repository and are refused). The previous release is still in the store, so `setup` uses it without a download
(`release: present`). Infrastructure rollback is pinning the previous configuration release and digest; the current
authorization policy still applies, so a rollback never reinstates anything revoked or withdrawn since.

## 6. Diagnosing a failed installation
`dev-platform setup --json` gives the full record; `problem` names the first refusal. Exit status: 0 ready, 1 refused or
unsatisfied, 2 configuration or usage, 3 integrity.

| Symptom | Meaning | Action |
|---|---|---|
| exit 2, `[platform] lacks source_revision, archive_sha256 and verifier_pins` | `dev-platform.toml` predates 0.17.0 (the identity was in `dev-platform.release-pins.json`) | `dev-platform update --to 0.17.0 --write` |
| exit 2, `predates repository isolation` | the pin is 0.15.0 or 0.16.x, whose toolchain preparation writes into the project | `dev-platform update --to 0.17.0` |
| exit 1, `needs the platform's Bazel configuration (dev-platform/) inside the repository` | a Bazel profile: its verification needs generated files that repository isolation forbids installing | [unsupported until the configuration is delivered externally](adr/0027-repository-isolation.md) |
| exit 3, `does not equal` a pinned digest | the installer, verifier or policy at the pinned revision is not what the pins name | the pins are wrong or tampered with; nothing was installed |
| exit 1, `trusted installer refused` | archive digest, attestations or admission failed | read the installer's reason; `acceptance state 'verified-unaccepted' is not admitted` (a release up to 0.11.0) means `--allow-unaccepted` is missing |
| exit 1, mentions `gh auth login` | `gh` is missing or not authenticated | `gh auth login` |
| exit 3, `not the pinned` tree digest | the store entry was altered (it is left untouched for inspection) | remove `<store>/<version>` (`chmod -R u+w` first) and run `setup` again |
| exit 3, `integrity failure` from `check`/`doctor` | the launcher refused to run an altered release | as above |
| exit 1, `no pinned source of ... for this host` | the host is not supported by that release | use a supported host ([above](#supported-hosts)) |
| exit 1, `doctor (release ...) reports` | the project is not ready under its pinned release | the listed doctor errors (missing host tools, configuration) |
| `--reverify` requested | the installer's record beside the release is missing or does not match | `dev-platform setup --reverify` |

Locations and how to move them (`--home`, `DEV_PLATFORM_HOME`, `DEV_PLATFORM_STORE`, ...): [homebrew.md](homebrew.md#locations).
Remove all installed releases and toolchains:
`chmod -R u+w ~/.local/share/dev-platform && rm -rf ~/.local/share/dev-platform ~/.cache/dev-platform`.

## 7. CI: job-local installation (no Homebrew)
CI runs a job-local verified release, never a user's Homebrew installation or a shared home:
- the reusable workflow [`consumer-pilot.yml`](consumer-integration.md) at the pinned release's commit, or
- `python3 platform/tools/consumer_run.py --consumer-dir consumer --work "$RUNNER_TEMP/dp" --evidence-dir evidence
  --dev-platform-checkout platform [--allow-unaccepted]` (the flag only for releases up to 0.11.0) with the platform
  checked out at the pinned revision.

Either one checks the pins against each other, refuses the installer, verifier and policy unless they equal the pinned digests,
installs the release with the trusted installer into a job-local store, provisions the toolchain twice (identical identity
required), runs `doctor` and `check --stage full`, writes the evidence bundle and judges it against the consumer's pins
(`consistent` is consistency with the pins, not trustworthy execution). The job's read-only token goes to the installer's
`gh attestation verify` only and is removed from every later process. Nothing registers a runner, enables a workflow or
service, calls a provider or binds a credential or environment.

Known limit: `consumer-pilot.yml` provisions its bootstrap interpreter with `actions/setup-python`, which cannot install on a
self-hosted macOS runner (it writes to `/Users/runner`). On such a runner use `consumer_run.py` directly with an available
Python 3.11+ (for profiles other than `python`, whose verification covers the running interpreter), or a GitHub-hosted
runner; the platform's own toolchain is provisioned from the release's pins either way. Toolchain sources exist for
macOS arm64 and Linux x86_64 only, so a Linux arm64 runner cannot run a pinned release.

## Repository isolation: locations, output paths, what is unavailable
Everything the platform installs or generates lives outside the project:
```
~/.local/share/dev-platform/        --home, DEV_PLATFORM_HOME (in CI $RUNNER_TEMP/dev-platform)
  versions/<version>/               verified platform releases, write-once      --store, DEV_PLATFORM_STORE
  toolchains/<version>/<profile>/   provisioned toolchains                      --toolchains, DEV_PLATFORM_TOOLCHAINS
  infra/                            infrastructure store: releases/, authorization/   --infra-store (install), --store (infra store)
~/.cache/dev-platform/              git objects of the pinned revision, lock    --cache, DEV_PLATFORM_CACHE
```
The infrastructure store has one calculation, `<data root>/infra`, for `install` and every `infra` command. Overriding the
platform release store (`--store`, `DEV_PLATFORM_STORE`) never moves it; only `--infra-store` / `infra store --store` does.

**Output-path guard.** A destination the caller chooses is resolved through symlinks and refused (exit 2, nothing written)
when it lies inside a consuming project's working tree or its Git metadata (including a linked worktree's). The project
is the directory of the nearest `dev-platform.toml` from `--project` and from the working directory. Guarded: `check --result`;
`toolchain provision|prepare --dest` (the default `.devenv` is inside a project, so pass a directory outside it);
`toolchain prove-bazel-rust --out`; `release build|pack --out`, `release install --store`; `provenance assemble --out`;
`dependency-snapshot --out`; `evidence put --store`, `evidence bundle --out`; `workflow --output`; `infra init|release build
--root`, `infra resolve --evidence-out` and the request's `profile_out`; `infra store --store`; and the release, toolchain,
cache and infrastructure-store locations, whether chosen by flag, by environment variable (a relative value is resolved
against the working directory) or by default. Not guarded, because it is the contract itself: `dev-platform.toml`, written
by `install`, `update --write` and `init`. The platform's own repository is not a consumer, so its maintainer and build operations still write there; a
repository is that only when its `dev-platform.toml` says `self_hosted = true` and it is the checkout the running platform
code comes from, so claiming the mode in a consuming project grants nothing. The destination is judged as well: a command
run from elsewhere cannot write into another project's tree, into any `.git` directory, or through a hard link of a project
file, and containment is decided by file identity (letter case, links). Read-only commands do not touch `.git` either (the
engine's `git diff` works on a private copy of the index). The check is made immediately before use; it does not defend
against another process swapping a path in between.

**Unavailable until the external CI, Bazel and hook architecture exists** (none of them can be installed into a repository):
- `toolchain materialize` writes nothing into a project (`--check` and `--dry-run` remain); the platform-managed Bazel
  configuration, and therefore Bazel profiles in a project that does not already hold `dev-platform/generated.json`
  (`toolchain prepare` refuses them);
- the central CI path: `dev-platform workflow` previews a caller workflow, and `consumer-pilot.yml` / `tools/consumer_run.py`
  still read `dev-platform.release-pins.json`; no workflow is installed;
- hooks of any kind, and runner configuration in a repository;
- the implicit vendored infra profile (`.dev-platform/infra-profile.json`); `--infra-profile FILE` still takes one explicitly.

## Hosted-only mode (the default)
No `[infra]` table, no configuration repository, no resolver. The engine offers GitHub-hosted runners only;
`dev-platform workflow` prints a proposed caller workflow. There is nothing else to configure ([infrastructure](infrastructure.md)).

## Private infrastructure mode (optional)
An authorized operator attaches an organization's configuration with the same CLI:

1. **The consumer pins it** in `dev-platform.toml` (a reviewed change):
   ```toml
   [infra]
   provider = "my-org-infra"
   config_release = "2026.10.1"                    # exact; no ranges, no "latest"
   config_digest = "sha256:<release-tree digest>"  # from the configuration repository's releases/index.v1.json
   config_digest_kind = "release-tree"             # needs a platform pin of 0.10.0 or later
   ```
2. **A trusted job, or an operator, obtains exactly that release** plus the current authorization policy into the store, with
   an identity that can read the configuration repository:
   ```sh
   dev-platform infra store fetch --project . --source my-org/infra   # GET only, via gh; or `infra store import` from a checkout
   dev-platform infra store sync --source my-org/infra                # later: refresh the policy (forward only)
   dev-platform infra store list
   dev-platform infra doctor --project .                              # pinned vs resolved, policy, decision
   ```
3. **The operator names the resolver** for trusted events; nothing finds one automatically:
   ```sh
   dev-platform check --stage full --event-trust trusted \
     --infra-resolver "dev-platform infra resolve --root $RUNNER_TEMP/dev-platform/infra"
   ```
Untrusted events (fork pull requests) never consult a provider. Anything other than the exact pinned release under a valid
current policy fails closed: `digest-mismatch`, `version-unknown`, `release-stale`, `release-revoked`, `policy-invalid`,
`release-tampered`, and others ([infra integration](infra-integration.md)).

**Access boundary.** A consumer repository's `GITHUB_TOKEN` is scoped to that repository; it cannot read another private
repository, and nothing here assumes it can. Reading the configuration repository needs a credential the organization issues
for that purpose (for example a GitHub App installation token with `contents: read` on the configuration repository only),
given to the `infra store fetch`/`sync` step alone, in a job only trusted events reach (for example behind a protected
environment). Alternatively the operator fills the store outside the job (`infra store import`). The platform never stores a
credential and never defaults a source.

**Two digests.** The *release-tree digest* identifies an immutable configuration release (all its files) and is what a
consumer pins with a provider; a newer policy can narrow what that release yields but never changes the digest. A
*profile-file digest* (`dev-platform infra digest profile.json`) identifies the bytes of one vendored profile; it is the pin for
untrusted CI (`config_digest_kind = "profile-file"`) and the `effective_profile_digest` a provider reports.

## Verification behind this runbook
The `homebrew` workflow (macOS 15 and Ubuntu 24.04, every change to `src/`) installs, tests, upgrades and rolls back the
formula from a tap with history, runs `setup` against published releases, and checks the refusals and that upgrades leave
releases, pins and the infrastructure store unchanged. The upgrade from the published 0.9.0 and 0.10.0 CLIs to the current
code was verified on macOS (Apple silicon) by running each CLI, laid out as its formula installs it, against one store.
