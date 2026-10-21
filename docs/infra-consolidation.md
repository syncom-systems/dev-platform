# Infrastructure consolidation: ownership inventory, stages and private handoff

Decision: [ADR 0023](adr/0023-infrastructure-capabilities-in-the-public-platform.md). This page is the public-safe
record of what moved and what did not. It names capabilities, never an organization's runners, hosts, endpoints,
credential references, authorization records or findings.

## Ownership inventory
Classes: **G** generic (public platform), **O** organization-specific data or rules (stays in the organization's
private repository), **C** consumer-specific (the consumer repository).

| Capability (as it existed privately) | Class | Public home |
|---|---|---|
| Immutable configuration releases: CalVer, release-tree digest (the platform `tree_digest`), append-only index, verify against the protected branch's index | G | `infra_release`, `dev-platform infra release build/verify`, `infra digest` |
| Current authorization policy: floor, revocations, enabled repositories, withdrawals; narrows only | G (format and evaluation) / O (the policy document itself) | `infra_authz`, `dev-platform infra authorization check` |
| Provider side of `dev-platform.infra-resolve/v1`: strict request, denial codes, untrusted gets the public default, verified-from-parsed-bytes release, narrowing | G | `infra_provider`, `dev-platform infra resolve` |
| Local store of exactly selected releases and the forward-only policy; user, job-local or explicit location | G | `infra_store`, `dev-platform infra store ...` |
| Identity-only diagnostic (CLI, store, selection, decision codes) | G | `dev-platform infra doctor` |
| Read-only discovery of runner groups, repository runners, workflow token default, fork-PR approval, rulesets | G | `dev-platform infra discover` (`gh api` GET only) |
| Audit rules over a discovery snapshot (public-repository runner groups, ungrouped runners, persistent runners for public repositories, ...) | G | `dev-platform infra audit` |
| Desired-versus-observed drift | G (algorithm) / O (desired values) | `dev-platform infra drift` over `dev-platform.infra-config/v1` |
| Runner capability and trust model, credential classes and references, caches and access modes, runner groups, repository assignments, admission | G (schema) / O (values) | `dev-platform.infra-config/v1` (`infra_config`), `dev-platform infra init/validate/profile` |
| GitHub-hosted runner classes | G | templates in `infra_config`, `dev-platform workflow` preview |
| Organization runner inventory, placement, cache endpoints, credential bindings, repository assignments, the current policy, releases | O | stays private |
| Organization trust tiers per ref and their projection; capacity; rules stricter than the public admission verdict | O | stays private (projects onto `dev-platform.infra/v1`) |
| Live enforcement inspection that encodes organization rules | O (for now) | stays private; uses `pr-check --facts` |
| Observed state, assessments, change procedures, handoffs, private CLI distribution | O | stays private |
| Workflows, requirements, `[infra]` and platform pins | C | each consumer |

Routing (`runners.route`), admission (`prcheck`) and event trust (`runners.event_trust`) were already public and are
reused; nothing above introduces a second policy engine.

## Compatibility evidence
- The release-tree digest equals `tree_digest` for every tree the public reader accepts (it refuses what `tree_digest`
  would skip or the previous reader would include).
- The public provider gives byte-identical results (result document and effective profile bytes) to the previous
  private provider on an existing private release (checked read-only, outside this repository; no private data is
  committed). Public tests use a synthetic release in the previous layout.
- Every result of the public provider is judged identically by the engines of 0.8.0, 0.8.1, 0.8.2 and 0.9.0
  (`tests/test_infra_compat_releases.py`, from the release tags).
- `[infra]` pins without `config_digest_kind` parse and resolve exactly as before in every release.

## Stages
1. Releases, authorization, provider, explicit digest kind, mandatory authorization facts, compatibility tests.
2. `dev-platform.infra-config/v1`, `infra init/validate/profile`, `infra release build`, templates, `workflow` preview.
3. Local store, `infra doctor`, discovery, audit, drift.
4. Non-activation and boundary regressions, documentation.

## Regression tests
| Property | Where |
|---|---|
| Public-only use works without any infrastructure repository | `test_workflow_preview`, `test_non_activation` (no store, no provider, no network) |
| GitHub-hosted CI configurable without private infrastructure | `test_infra_config.Templates`, `test_workflow_preview` |
| Installing or upgrading activates nothing | `test_non_activation` (formula, empty home, GET-only, static guards); `homebrew` workflow (real Homebrew) |
| An explicitly configured self-hosted profile validates | `test_infra_config.Templates`, `Projection` |
| Unauthorized or incompatible runner configuration is rejected | `test_infra_config.FailsClosed`, `test_infra_provider.Denies` |
| Existing immutable releases stay resolvable (also the previous private layout) | `test_infra_release.Formats`, `test_infra_provider.Resolves` |
| Current authorization narrows or revokes older pins, never widens | `test_infra_provider.Narrowing`, `test_infra_store.Policy` |
| Missing or invalid authorization fails closed | `test_infra_provider.Denies`, `test_infra_pin.AuthorizationFacts`, conformance kit |
| No private infrastructure data in the public tree, fixtures or release tree | `test_public_boundary` (plus an organization's deny-list via `DEV_PLATFORM_PRIVATE_DENYLIST`) |
| CLI upgrades preserve consumer pins and stores | `test_non_activation.UpgradePreservesSelections`; `homebrew` workflow |
| Compatibility at the pinned platform version, including older releases | `test_infra_compat_releases` (engines of 0.8.0 to 0.9.0) |

## Handoff to the private infrastructure workspace (not performed from here)
The private repository is not modified from this workspace. After a platform release with these modules exists:
1. Pin that platform release in the private CI's public checkout (exact commit) and run the public provider against
   the private store and repository in CI next to the private one; require identical results on every release.
2. Replace the private release builder's generic half (`build` and `verify`) with `dev-platform infra release`; keep
   the organization's projection as the producer of `profiles/<repo>.json`. Existing releases stay byte for byte;
   new releases may keep the previous format or adopt `dev-platform.infra-config-release/v1` (a new format is a new
   release, never a rewrite).
3. Switch trusted callers from the private resolver command to `dev-platform infra resolve --root <store>` only after
   step 1 shows equality; keep the private command available for rollback until consumers have moved.
4. Remove the duplicated generic code (release verification, resolution, store, doctor, discovery, audit, drift)
   and the private CLI's Homebrew distribution once nothing calls them; keep the organization data, rules,
   procedures and handoffs.
5. Optionally express the organization configuration as `dev-platform.infra-config/v1` (or keep the private model and
   its projection). Its own CI should run its deny-list of runner ids, endpoints and credential references against
   the public tree (it already does).

Owner decisions: when to pin the new platform release privately, whether the organization adopts the public
configuration schema, and when the private CLI is retired.

## Interface for the private infrastructure workspace (2026-10-21)
Public-safe summary of what an organization's configuration repository and its operators can rely on. Nothing here
requires a change in the private repository; nothing here was done there.

- **CLI.** The published CLI is 0.10.0 (tag `v0.10.0`, commit `59ac8a3c752de106a8f1d3df1c31a559fe0fd824`, archive
  sha256 `a3473a0260b16d571c2832228e2e02e9d07c8b535da2439cc4f2f69ccd74099b`, tree `a8d7a5004a2f56109d1c3b6c1cb2623ab6d8eb185bd445dc345834250af894aa`,
  verified-unaccepted). The `infra` modules, `dev-platform.infra/v1`, the resolver protocol and the conformance kit are
  unchanged on `main` since 0.10.0; the next release (proposed 0.11.0) carries them unchanged.
- **Install and upgrade:** `brew install syncom-systems/dev-platform/dev-platform`, `brew update && brew upgrade
  dev-platform`; rollback by `brew extract` ([installation](installation.md#5-rollback)). No private package and no second
  CLI is needed for any command below.
- **Configuration release:** `releases/index.v1.json` (`{"schema_version": 1, "releases": [{"version", "digest" (bare
  hex), "contract"}]}`, append-only), immutable `releases/<YYYY.MM.N>/`, `authorization/current.v1.json` (exactly the
  eight documented keys; `revoked_releases` entries are `{version, reason?}`). Identity is the release-tree digest
  `sha256:` + `tree_digest(releases/<version>)` (`dev-platform infra digest releases/<version>`), which is what a consumer
  pins with `config_digest_kind = "release-tree"`. The profile-file digest is only for vendored profiles and the reported
  `effective_profile_digest`. `dev-platform infra release verify --root . --base-index <protected index>` is the
  immutability check for the configuration repository's CI.
- **Store and resolver:** `<data root>/infra` (`DEV_PLATFORM_HOME`; `$RUNNER_TEMP/dev-platform` in CI; else
  `~/.local/share/dev-platform`), or `--store`. Fill it with `infra store fetch --project . --source <owner>/<repo>`
  (exactly the pinned release plus the current policy, GET only) or `infra store import`; refresh the policy with
  `infra store sync` (forward only: an older revision is refused). Trusted jobs name the resolver explicitly:
  `--infra-resolver "dev-platform infra resolve --root <store>"`. Untrusted events always get `public-default`.
- **Authentication and trust:** `fetch`/`sync` use the caller's `gh` identity. A consumer repository's `GITHUB_TOKEN`
  cannot read the configuration repository; a job that fetches needs a credential issued for that repository only
  (for example a GitHub App token with `contents: read`), given to that step alone, in a job only trusted events reach.
  Without access `fetch` fails `access-denied` and writes nothing.
- **Verified end to end (2026-10-21, read-only, scratch store, no private data committed):** the current code (its `infra`
  modules are identical to 0.10.0's) fetched the organization's current configuration release by its pin with the public CLI alone;
  `store list` showed it `ok`; `infra doctor` resolved it for an enabled repository; `infra resolve` resolved the exact pin
  with complete authorization facts and denied a wrong digest (`digest-mismatch`), an unknown release
  (`version-unknown`) and a repository not enabled (`repo-not-enabled`), and returned `public-default` for an untrusted
  event.
- **Compatibility and rollback:** formats are only added; a newer CLI resolves every older release unchanged, and a CLI
  upgrade leaves the store and every `[infra]` pin byte for byte unchanged. Consumer rollback is pinning the previous
  release and digest; the current policy still applies. Do not publish a release in `dev-platform.infra-config-release/v1`
  while the private CLI is still in use: it cannot read that format.
- **Open on the private side (owner decisions):** retiring the private CLI and its Homebrew distribution (qualification
  gate 3); re-running the recorded qualification gates against the next platform release once it exists.
