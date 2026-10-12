# NGA pilot adoption plan (v0.8.1, explicit opt-in, additive)

Status: **plan only.** Nothing here modifies NGA, authorizes a change to it or grants any acceptance. It becomes actionable only when
the owner authorizes this specific change to the consumer repository. v0.8.1 is **verified-unaccepted**; using it is an explicit
opt-in recorded in the workflow file (`allow_unaccepted: true`). Nothing about v0.2.1's acceptance extends to it.

## What the pilot is
One new, **non-required** pull-request workflow in NGA that, in addition to NGA's own `check` and `full-gate`, selects the pinned
platform release from public data, provisions its Bazel/Rust toolchain profile, runs a small Bazel target set, proves Bazel used the
declared Rust toolchain, and uploads an evidence bundle judged against NGA's own pins. NGA's existing gates, scripts, runner
selection, Bazel configuration and branch rules are not touched, wrapped, reordered or made to depend on it.

## Read-only preflight (done 2026-10-12, repeat at adoption; no clone, no write)
| Observed in NGA | Consequence |
|---|---|
| `.bazelversion` = 9.2.0 | matches the `rust-bazel-9` profile (Bazel 9.2.0 pinned by digest at execution) |
| `MODULE.bazel`: `rules_rust` 0.74.0, `rust.toolchain(versions = ["1.97.1"], edition = "2024", extra_target_triples = [bare-metal AArch64])`, `rules_java` 9.1.0 | the profile's `declared_in` pattern matches; `MODULE.bazel.lock` holds the `rules_rust` 0.74.0 registry source entry the profile pins |
| `.bazelrc`: "Bazel is the only build system. Never invoke cargo."; remote JDK 21; no remote cache or executor endpoint | the pilot needs no private endpoint; Cargo stays prohibited (`bazel_only = true` rejects the cargo adapter and a direct `cargo` exec) |
| existing PR job picks runner labels from a repository variable (may be self-hosted for same-repo PRs) and writes a disk-cache `~/.bazelrc` on hosted runners | the pilot must **not** read that variable: `runs-on` is the literal hosted label |
| required status on `main` is the existing `check` job | the pilot job has another name and is never added to the ruleset |
| wide host needs (QEMU boot test, Kani/Apalache/TLC, bare-metal target) | out of pilot scope; not covered by evidence (limitations carried from `docs/pilot-nga-plan.md`) |

## The change (three new files; nothing else)
1. `dev-platform.toml`
```toml
schema_version = 1
[platform]
version = "0.8.1"
sha256 = "35d5b2c99cc11e3da5b618ae4a19223b97834da2de2ac55f3a4e9f00759bffea"
profile = "rust-bazel-9"
[project]
name = "nga"
bazel_only = true
languages = ["rust"]
[[check]]
id = "bazel.pilot"
adapter = "bazel"
targets = ["<OWNER-CHOSEN small host-buildable test target(s)>"]   # see "Target choice"
stages = ["pre-merge", "full"]
obligation = "change"
inputs = ["**"]
```
No `[infra]` table: hosted runners only, so the evidence records `hosted-only` and no private access is even described.
2. `dev-platform.release-pins.json` (exact, from `releases/0.8.1/identity.json`)
```json
{
  "version": "0.8.1",
  "source_revision": "5fa25c68814ee9f4d284682215fa4c98198103ff",
  "archive_sha256": "5671100327d3b8bdfbf74277ae0b21bde39ec2f1f85d4abde12799647740a898",
  "tree_digest_pin": "35d5b2c99cc11e3da5b618ae4a19223b97834da2de2ac55f3a4e9f00759bffea",
  "verifier_pins": {
    "verify_release.py_sha256": "a2d53075b8bf11bb14f4a2dffb0b40fc6e66b04af73801951fcd768ba29f6f2e",
    "trust_policy_sha256": "9074871080b437518cf0c7ad9558409297faf023b09365aa0ac6f52f7dba1120",
    "install_release.py_sha256": "473a2c73eb71904ea6ee0e010f2288976126d4560e3efd11c33c11e44f15bb93"
  }
}
```
3. `.github/workflows/dev-platform-pilot.yml`
```yaml
name: dev-platform-pilot          # distinct from `check` and `full-gate`; never a required status
on:
  pull_request:                   # not pull_request_target: forks get no secrets and a read-only token
  workflow_dispatch:
permissions:
  contents: read
concurrency:
  group: dev-platform-pilot-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true
jobs:
  dev-platform:
    uses: syncom-systems/dev-platform/.github/workflows/consumer-pilot.yml@5fa25c68814ee9f4d284682215fa4c98198103ff
    with:
      platform_source_revision: "5fa25c68814ee9f4d284682215fa4c98198103ff"
      allow_unaccepted: true      # explicit opt-in: v0.8.1 is verified, NOT accepted
      runs_on: ubuntu-24.04       # GitHub-hosted, literal: never the repository's runner variable
      attest: false               # turn on later only if the owner wants Sigstore-attested evidence
```
(`attest: true` additionally needs `id-token: write` and `attestations: write` on the calling job; keep it off for the first run.)

## Target choice (owner, one decision)
Pick one to three fast, host-buildable test targets with no QEMU, Kani, TLA+ or bare-metal dependency, such as the test of a small
`no_std` library crate with no dependencies. The pilot builds on a cold hosted runner (no cache, no remote cache), so avoid targets
that fan out into the seeded-mutant variants or exhaust disk. The proof examines the Rustc actions of exactly these targets.

## Guarantees and how each is checked
| Requirement | How it holds | Check at the first run |
|---|---|---|
| Additional, non-required | separate workflow file and job name; ruleset untouched | the `check` status and its job name are unchanged; the pilot is not in the ruleset |
| No change to existing gates | no edit to `check.yml`, `full-gate.yml`, `tools/ci/*`, `.bazelrc`, ruleset | diff of the adoption PR touches only the three new files |
| Hosted runner | literal `ubuntu-24.04`; `runner.environment == github-hosted` | job log shows a GitHub-hosted runner; the platform's policy also requires hosted for its own signatures |
| No Cargo execution | `bazel_only = true`; profile has no cargo; the proof runs only Bazel and Bazel's own `rustc --version`; a decoy `cargo` is a trap | `bazel-rust-proof.json`: `host_decoy.invoked == false`, every rustc `bazel_external_repo == true`, observed == declared 1.97.1 |
| No private infrastructure | no secrets, no `[infra]` pin, no provider call, read-only token, public data only | `result.json` `infra.status == hosted-only`; `consumer-run.json` `event_trust == untrusted` on PRs |
| Exact release identity | pins file + toml; trusted tools fetched at the pinned revision must equal the pinned digests | `consumer-run.json`: `pinned_tools`, `installed`, `provision_deterministic` all true |
| Evidence consistency is not trustworthy execution | the verdict is `consistent` with NGA's pins; `verification.json` `not_established` lists what it does not show | reviewers read `verification.json` including its limits |

## Expected outcomes and what to do
| Outcome | Meaning | Action |
|---|---|---|
| pilot green | the pinned release installs, provisions deterministically, the chosen target passes, the Rust toolchain proof holds | read the evidence; nothing else changes |
| pilot red, install or pin step | a pin disagrees or a digest changed | stop; do not edit pins to make it pass; investigate (the same stop applies to a moved tag) |
| pilot red, Bazel step | NGA's target fails under the platform's invocation (for example a missing `--lockfile_mode=error` fix) | NGA's own gates are unaffected; fix or drop the target |
| decoy invoked | a host Rust tool was used | treat as a toolchain-isolation defect in NGA's Bazel setup |
| runner out of disk or time | the target set is too heavy for a cold hosted runner | shrink the target set |

## Authorization and steps (owner decisions marked)
1. **Owner:** authorize this specific change (three new files in NGA) and choose the target(s). Without that, nothing happens.
2. Agent prepares the adoption PR from this plan against a throwaway branch of NGA; owner reviews and merges (no force, no admin bypass).
3. First run on `workflow_dispatch`, then on pull requests. Read the evidence; compare the existing `check` run before and after.
4. **Owner:** keep, extend (for example `attest: true`, more targets) or remove. Removal is deleting the three files; no other state exists.
5. Anything beyond this (an `[infra]` pin, making the job required, replacing a gate, a platform acceptance of v0.8.1) is a separate
   decision and a separate change.

## Known gaps
- v0.8.0 is not suitable for this pilot: its consumer entry point proved the Rust toolchain over `//...` (fixed in 0.8.1: the proof examines only
  the consumer's own Bazel check targets). The plan therefore pins v0.8.1.
- Cold hosted builds download the Rust toolchain and the remote JDK from public mirrors each run, and the proof rebuilds the chosen targets once
  more with a fresh action-environment nonce, so the pilot costs about two builds of the chosen targets.
- The evidence verdict is `consistent` (consistency with NGA's pins); `verification.json` lists what it does not establish.
