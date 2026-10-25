# Homebrew installation and project setup

Decision: [ADR 0022](adr/0022-homebrew-cli-and-project-setup.md). The tap is the public repository
`syncom-systems/homebrew-dev-platform`; its formula is rendered from a release identity by
`tools/homebrew_formula.py` and updated by a pull request after each release.

Two things are installed, and they are deliberately separate:

| | What | Selected by | Changed by |
|---|---|---|---|
| **CLI** | `dev-platform`, the command and verifying launcher | Homebrew | `brew upgrade` |
| **Platform release** | the exact release a project runs, plus its toolchains | the project's committed pins | a reviewed edit of the pins |

The CLI's version never selects a project's release. In a project, `check`, `explain` and `doctor` run the
pinned release (from a verified snapshot), not the CLI's own code, and `setup` only reads the pins.

## Development Mac
```sh
brew install syncom-systems/dev-platform/dev-platform   # taps syncom-systems/homebrew-dev-platform; pulls gh and python@3.14
gh auth login                                           # once: the trusted installer verifies attestations with gh
dev-platform --version
```
Installing by the fully qualified name trusts that one formula (Homebrew's tap trust); nothing else from the tap is
trusted implicitly. No sudo, nothing global: the CLI lives in the Homebrew prefix, releases and toolchains in your home directory.
Toolchain profiles have sources for macOS on Apple silicon and Linux x86_64; on an Intel Mac the CLI works but
`setup` cannot provision a profile.

In a project that commits `dev-platform.toml` (its `[platform]` table holds the release identity; the only platform file in
a project, [ADR 0027](adr/0027-repository-isolation.md); `dev-platform install` writes it on first installation,
[installation](installation.md#2-a-projects-pinned-release)):
```sh
cd my-project                      # or any subdirectory: setup looks upwards for dev-platform.toml
dev-platform setup                 # releases up to 0.11.0 are verified-unaccepted: add --allow-unaccepted (your decision)
eval "$(dev-platform setup --print-env)"   # this shell: DEV_PLATFORM_STORE, DEV_PLATFORM_PYTHON, PATH
dev-platform doctor
dev-platform check --stage pre-merge --base origin/main
```
`setup` is idempotent: a second run reverifies the store entry and the toolchain directory and downloads nothing.
`--dry-run` shows what it would do (no network, no writes), `--json` gives the record, `--reverify` runs the
trusted installer again for an installed release.

### Upgrade, pin, roll back
```sh
brew update && brew upgrade dev-platform   # the CLI only; project pins, installed releases and CI are unchanged
brew pin dev-platform                      # keep the current CLI (brew unpin to resume upgrades)
brew tap-new --no-git local/dev-platform-versions                       # once, a local tap for old versions
brew extract --version=0.9.0 syncom-systems/dev-platform/dev-platform local/dev-platform-versions
brew unlink dev-platform && brew install local/dev-platform-versions/dev-platform@0.9.0   # roll back
brew uninstall dev-platform@0.9.0 && brew link dev-platform                               # forward again
```
Upgrading a *project's* platform release is an edit of its two pin files in a reviewed change, never a Homebrew
action. Several releases and their toolchains coexist; each project selects its own.

## Locations
Precedence for each location: its flag, its variable, then the data root (`--home`, `DEV_PLATFORM_HOME`, in CI a
job-local `$RUNNER_TEMP/dev-platform`, else `${XDG_DATA_HOME:-~/.local/share}/dev-platform`).

| | Default (development machine) | In CI | Flag / variable |
|---|---|---|---|
| CLI | `$(brew --prefix)/opt/dev-platform`: `bin/dev-platform`, `libexec/` = the release tree | - | Homebrew |
| Releases | `~/.local/share/dev-platform/versions/<version>/` (read-only), records in `versions/.records/` | `$RUNNER_TEMP/dev-platform/versions/` | `--store`, `DEV_PLATFORM_STORE` |
| Toolchains | `~/.local/share/dev-platform/toolchains/<version>/<profile>/` | `$RUNNER_TEMP/dev-platform/toolchains/` | `--toolchains`, `DEV_PLATFORM_TOOLCHAINS` |
| Cache | `${XDG_CACHE_HOME:-~/.cache}/dev-platform/` (git objects of the pinned revision, lock) | `$RUNNER_TEMP/dev-platform/cache/` | `--cache`, `DEV_PLATFORM_CACHE` |

`DEV_PLATFORM_HOME` moves all three (cache under it too). The launcher finds releases through `DEV_PLATFORM_STORE`,
else `DEV_PLATFORM_HOME/versions`, else the user default, which is why `--print-env` exports the store. Remove
everything with `chmod -R u+w ~/.local/share/dev-platform && rm -rf ~/.local/share/dev-platform ~/.cache/dev-platform`;
`brew uninstall` never touches these.

## What is verified, by whom, when
1. **`brew install` / `brew upgrade`.** Homebrew checks that the downloaded release archive has the formula's
   sha256, which is the archive digest the release's independent verification recorded
   (`releases/<version>/identity.json`). The formula's test requires the installed `libexec/` to have the release's
   tree digest. Before a formula change merges, the tap's CI verifies that archive with the trusted installer
   (provenance, SBOM and build-environment attestations under the pinned verifier and policy). A matching checksum
   on your machine says the bytes are the ones the formula names; it does not by itself establish who built them.
   To check that yourself, run the trusted installer on the exact archive Homebrew downloaded, with the pins from
   the release's identity record ([release trust](release-trust.md#trusted-installation-toolsinstall_releasepy)) and
   the release's build-environment and continuity records:
   ```sh
   gh release download v<v> --repo syncom-systems/dev-platform --dir d \
     --pattern '*.build-environment.json' --pattern '*.continuity.json'
   python3 -I tools/install_release.py --version <v> --archive "$(brew --cache dev-platform)" \
     --environment d/dev-platform-<v>.build-environment.json --continuity d/dev-platform-<v>.continuity.json \
     --store "$(mktemp -d)" --verifier-sha256 <pin> --policy policy.json --policy-sha256 <pin> \
     --archive-sha256 <pin> --tree-sha256 <pin> --source-revision <pin> --allow-unaccepted
   ```
   (`tools/` and `policy.json` taken at the release's source revision, as `setup` does.)
   The CLI is a launcher: it never certifies anything about itself, and a project's results name the pinned
   release, not the CLI.
2. **`dev-platform setup`**, in order, stopping at the first refusal:
   1. finds the project; `dev-platform.toml` must parse, must not be self-hosted, and must agree with the pins file
      on version and tree digest; the pins must be well formed (exit 2 otherwise);
   2. if `<store>/<version>` exists: its tree digest must equal the pin (otherwise exit 3, and the entry is left
      untouched for you to inspect and remove), and the installer's record beside it must name exactly this
      version, tree and archive (otherwise `--reverify`); the recorded state must be admitted (`verified` or `accepted`,
      or `--allow-unaccepted` / `--allow-prerelease`);
   3. otherwise: `tools/verify_release.py`, `trust/policy.json` and `tools/install_release.py` are read from the
      public platform repository **at the pinned source revision** and must equal the pinned digests (exit 3
      otherwise; nothing is installed). That pinned `install_release.py` runs with the pinned verifier and policy and
      the pinned archive sha256, tree digest and revision: archive digest, structure, version binding, source
      revision, SBOM correspondence, provenance/SBOM/build-environment/continuity attestations, admission; only then
      are the verified bytes extracted, frozen read-only and renamed into the write-once store with the verification
      record. Only this process receives `GH_TOKEN`/`GITHUB_TOKEN`;
   4. the pinned release is snapshotted into a private directory while hashing (digest must equal the pin) and run
      from there: `toolchain verify --require-certifiable` against the release's own manifest decides whether the
      toolchain directory is reused; otherwise `toolchain provision --pinned` (hash-pinned sources) and the same
      verification again. A profile whose python is the interpreter running the platform is verified on the
      provisioned interpreter, and `DEV_PLATFORM_PYTHON` makes the launcher run the release on it afterwards;
   5. the pinned release's `doctor` (with the vendored infra profile if the project has one) must exit 0.
   Exit status: 0 ready, 1 refused or unsatisfied, 2 configuration or usage, 3 integrity.
3. **Every later `check` / `explain` / `doctor`**: the launcher snapshots `<store>/<version>`, refuses a digest
   other than `[platform] sha256` (exit 3, "integrity failure"), and runs the release from the snapshot; the child
   re-hashes the tree it runs from.

`setup` never writes the project's files, never calls an infrastructure provider (only a vendored profile the
project committed is passed to `doctor`), and never creates or implies acceptance.

## What installing never does
`brew install` and `brew upgrade` install the CLI's release tree under the Homebrew prefix and the `dev-platform`
launcher, nothing else: no service, launch agent or scheduled job, no file in your home directory, no private
configuration, no credential, no runner registration, no workflow and no GitHub setting. The CLI reads GitHub only
when a command is explicitly about it (`setup` installing a pinned release; `infra discover`, `infra store fetch` and
`infra store sync`, each with a source you name), always with `gh api --method GET` for the infrastructure commands.
The optional infrastructure capabilities ([infrastructure](infrastructure.md)) are available but inactive until you
configure and activate them through your own review. The `homebrew` workflow checks this on macOS and Linux: no
launch agent or service appears, the job's data root does not exist after installation, reading commands leave an
empty home empty, and an upgrade leaves an infrastructure store and the consumer's `[infra]` pin byte for byte
unchanged while the new CLI still resolves the pinned configuration release.

## Self-hosted runners
CI runs **job-local verified releases**; a user-local CLI installation is a convenience for people.
- Preferred: the reusable workflow [`consumer-pilot.yml`](consumer-integration.md) or `tools/consumer_run.py --work
  "$RUNNER_TEMP/dp"`. It installs the pinned release into a job-local store with the trusted installer, provisions twice
  (determinism), checks, and writes verifiable evidence. It does not use Homebrew.
- If a job uses the Homebrew CLI (installed for the runner's user by whoever administers the runner), `setup`
  detects CI and defaults to `$RUNNER_TEMP/dev-platform`, so a job never runs a release or toolchain another job
  left in a shared home; without `RUNNER_TEMP` it refuses unless you name a location. Give the read-only job token to
  setup alone and drop it before anything runs the project's code:
  ```yaml
  - name: dev-platform (job-local release)
    env: {GH_TOKEN: "${{ github.token }}"}
    run: |
      dev-platform setup --allow-unaccepted --print-env > "$RUNNER_TEMP/dp.env"
      unset GH_TOKEN GITHUB_TOKEN
      . "$RUNNER_TEMP/dp.env"
      dev-platform check --stage pre-merge --base origin/main --result result.json
  ```
  Setting `DEV_PLATFORM_HOME` to a persistent directory on a runner shares releases and toolchains between jobs;
  integrity is still re-checked on every use, but only do it where the runner's user account is trusted.
- `brew upgrade` on a runner changes the CLI only. The release a job runs is the one its repository pins, so
  CI behaviour changes only through a reviewed pin change.
- Private runner inventories, labels' meaning, credentials and policy live in Dev Platform Infra and reach a run
  only through the consumer's `[infra]` pin and its provider ([infra integration](infra-integration.md)); the tap
  and `setup` carry none of it.
