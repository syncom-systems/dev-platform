# 0024 Single-owner release authority

Status: Proposed (owner decision, 2026-10-22: "go ahead and release" is sufficient authorization for the complete
routine release). Takes effect for the first release whose policy is `dev-platform.trust/v2` (the next one, 0.12.0).
Supersedes [ADR 0016](0016-authorization-trust-boundary.md) and [ADR 0020](0020-environment-approval-provider.md) for
platform releases; amends [ADR 0014](0014-release-trust-bootstrap-and-execution.md) (bootstrap clause 1),
[ADR 0017](0017-release-lifecycle-and-planning.md) (lifecycle and authority table) and
[ADR 0019](0019-application-release-approval-trust.md) §11 (a policy that requires an accepted platform release).

## Context
One developer owns, develops and releases the platform. Since 0.1.0 a stable release became `accepted` only with an
authenticated owner authorization record (ADR 0016, 0020): an approver registry in the trust policy, a separate
acceptance workflow, acceptance packets, and a separate approval for each follow-up (evidence, Homebrew tap, Infra
re-pin). In practice every stable release except 0.2.1 stayed `verified-unaccepted`, every consumer passed
`--allow-unaccepted`, and each release took several rounds of permission requests. The approval itself added no
assurance over the owner's GitHub account: the recorded click cannot distinguish the owner from an agent working
through the same session (ADR 0020, issue #115).

## Decision
1. **Authority.** Releasing is pushing a protected version tag on a commit of `main`. Ordinary GitHub repository
   permissions and the rulesets (`main`: pull request plus required checks; version tags: immutable) decide who can.
   The owner authorizes their agent in ordinary words ("is it ready?", "go ahead and release"); nothing records,
   signs or verifies that instruction, and it is not presented as a security control.
2. **Verified.** A release is `verified` when every check of the independent verifier passes: archive and tree digests,
   safe extraction, version and source-revision binding, SBOM correspondence, provenance, SBOM, build-environment and
   continuity attestations from the release workflow on a GitHub-hosted runner for a protected version tag, and the
   predecessor's full stage over the new source. `-alpha.N`, `-beta.N` and `-rc.N` versions are `pre-release`. Anything
   else is `failed`. No approval record is read. The policy schema is `dev-platform.trust/v2`: signers, runner and
   evidence requirements and the continuity predecessor; no approver registry and no `stable_requires_authorization`.
   The verifier refuses a `trust/v1` policy instead of reinterpreting it.
3. **Publication.** `release.yml` publishes a `verified` stable release as a normal (latest) GitHub release and a
   pre-release as a pre-release; both immutable, and `gh release verify` / `verify-asset` must pass.
4. **Installation.** The trusted installer and `setup` admit `verified` without a flag. A pre-release still needs
   `--allow-prerelease`. `--allow-unaccepted` remains for releases published before 0.12.0.
5. **The routine release is one operation.** `tools/release.py ready` gives one verdict (READY TO RELEASE or BLOCKED);
   after the owner's go-ahead `tools/release.py publish` finalizes the version and notes in a pull request, merges it
   when its required checks pass, tags that exact commit, waits for the workflow, re-verifies the published release
   outside CI, records `releases/<version>/` and updates the Homebrew tap, each through a pull request merged when its
   checks pass. It uses the caller's `gh` identity and checkout: no new workflow, token, permission or stored state.
   A workflow-based follow-up would need a cross-repository credential (a GitHub App); that is a one-time owner setup
   decision, not taken here.
6. **Stops.** A failed check or verification, an unexpected security finding, a material change of scope or a new
   permission requirement stops the release with an explanation. Nothing is bypassed or retried around a failure.

## Kept
Automated tests and readiness checks; exact commit and version binding; deterministic builds (`ready` builds twice
from an export of the tracked files); immutable releases and protected tags; archive and tree digests; provenance,
SBOM, build-environment and continuity attestations; independent verification in CI and again outside it;
fail-closed installation; explicit consumer pins; ordinary GitHub permissions.

## Removed
Platform-release authorization records, the approver registry and `stable_requires_authorization`; the `accept.yml`
workflow; the `verified-unaccepted` state for new releases; acceptance packets; separate approvals for the tag,
the release records and the tap. The identity providers stay in `tools/verify_release.py` only as the library that
application-release approvals use (ADR 0019); application approvals are the consumer's own policy and are unchanged.

## History is not reclassified
Releases up to 0.11.0 keep their verifier, `trust/v1` policy, records, GitHub release titles and states
(`verified-unaccepted`; 0.2.1 `accepted`). A consumer pinning one of them still runs that release's own installer and
still needs `--allow-unaccepted`. Current tools keep reading their records: the lifecycle, the current-acceptance
wrapper and the application-release verifier are tested against the v0.11.0 verifier.

## Compatibility
- Schemas: `trust-v2` added. In `verification/v1`, `acceptance.state` gains `verified` and `acceptance.authorization`
  is no longer required (old records stay valid).
- A CLI up to 0.11.0 installs a 0.12.0+ release (its pinned installer admits it) but refuses to reuse it from the store
  ("the pinned release is verified; it is not admitted") unless run with `--reverify`; upgrade the CLI.
- An application policy with `require_acceptance` accepts a `verified` platform release (it is the platform baseline)
  when verified with the application verifier of 0.12.0 or later; older application verifiers require `accepted`.
- Lifecycle: `independently-verified -> released` for trust/v2 releases. The 1.0.0 criterion
  `owner-accepted-baseline` becomes `stable-baseline-released`.
- The `owner-approval` GitHub environment is no longer used; deleting it is an owner settings change, not made here.

## Known limits
Release authority is exactly as strong as the owner's GitHub account and the repository rulesets. An agent working
through the owner's session can release; that was already true of the recorded approval and is now stated plainly.
