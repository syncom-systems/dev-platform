# 0017 Release lifecycle and GitHub-native planning

Status: Proposed (approved by the owner as the development baseline). Planning and versioning policy only; it adds no trust anchor and changes no ratified decision
(ADR 0014, 0015, 0016 are untouched).

## Decision
Use GitHub's own features for planning and keep them strictly separate from verification and authority.

| Concern | Mechanism | Authority |
|---|---|---|
| Version scope and completion | Milestones (`vX.Y.Z`), one per release | none |
| Work and its verification tasks | Issues, pull requests (a PR inherits the milestone of the issue it closes) | none |
| Roadmap and cross-repository coordination | Project "Dev Platform roadmap" (fields Track, Release gate) | none |
| Immutable artifacts | GitHub Releases published only by `release.yml` | none (publishing is not acceptance) |
| Technical verification | `tools/verify_release.py` with operator pins | verifier |
| Owner acceptance | authenticated authorization record (ADR 0016) | owner, via the pinned approver policy |

Thematic milestones M1-M6 are retired (closed, history kept); the theme is the Project's Track field.

## Lifecycle
`planned` -> `implementation-complete` -> `candidate-built` -> `independently-verified` ->
`verified-unaccepted` -> `accepted`, with overlays `superseded` and `revoked`.

- The first two are planning facts (milestone readiness). The next three are derived from verification
  records bound to the archive digest; `verified-unaccepted` additionally needs an immutable GitHub release.
- `accepted` has no incoming edge. `lifecycle.advance(.., "accepted")` is refused, and `derive` returns it
  only when handed a `VerifierResult`, an object constructible only by `lifecycle.run_verifier`, which runs the
  operator-pinned `verify_release.py` and reads its record. A record, label, milestone closure, merged PR or
  workflow result that says `accepted` is reported as a claim, not authority.
- Nothing in the lifecycle can widen trust. Overlays only narrow it, and they are two different things (see
  Amendments): a `suspended` overlay from an unauthenticated warning, and a `revoked` overlay that is a
  governance decision.
- Pre-releases stop at `independently-verified`.

## Versioning
`planning/release-policy.json` maps change kinds to bump levels; unknown kinds fail closed. A release is an
immutable tested environment: any toolchain pin change (`plan version-check --old-manifest`), schema change
(`--old-schemas`), or platform change needs a new release; components of an existing release are never replaced.
During 0.x an incompatible change is a minor bump and must be declared; 1.0.0 additionally requires the policy's
`one_zero_criteria`. Security fixes are patch releases on the supported line (`latest-minor`); `plan patches`
proposes candidates for affected supported lines and says "upgrade" for others.

## Assurance profiles
`assurance` selects a profile. `open-source` needs planning completeness and the standard gates. `regulated` adds
issue-to-PR traceability and named external attestations (`change-authorization`, `traceability-export`) that the
public core can only require to be present; their content and authority are private organization policy and
absent evidence fails closed. Consumers get the same contract through the platform, not their own workflows.

## Consequences
- `release.yml` stays the single publisher; `release-plan.yml` only assigns milestones and reports readiness.
- Release notes and the release-plan manifest are descriptive indexes that say so; they never replace
  verification records or authorization decisions.
- A milestone may be complete while its release is verified-unaccepted; the next milestone proceeds meanwhile.

## Amendments (owner refinements, 2026-10-11)
1. **Warnings are not governance decisions.** Any notice supplied without authenticated provenance, whatever
   it calls itself ("revoked", "superseded", an advisory), is a *warning*: it sets the `suspended` overlay
   (use is conservatively unavailable) and is listed under `warnings`, with `governance_decision: false`. It
   never changes the authorization outcome, and cannot un-accept a release. Revocation or replacement of an
   approval is a governance decision: it is read only from `authorization_evidence` entries of a
   `VerifierResult` (authenticated by a registered provider and authorized by the approver policy, ADR 0016);
   ignored records never count. The `decisions` list in the lifecycle output names those decisions. Lifting a
   suspension is a deliberate step: remove the warning or obtain an authenticated decision.
2. **Priority, not exclusivity.** The lowest open release milestone has priority; it is not an exclusive queue.
   `plan queue` orders eligible open issues by milestone (unscheduled last) and lists *held* (labels
   `owner-decision`, `held`, `proposal`) and *blocked* ("Blocked by #n" on an open issue) separately. A held
   patch, a pending authorization or an unrelated blocked item never stops independent work in other
   milestones.
