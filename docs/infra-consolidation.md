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
