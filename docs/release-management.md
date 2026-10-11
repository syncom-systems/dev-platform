# Release management

Planning (GitHub) and trust (verifier plus owner authorization) are separate. See
[ADR 0017](adr/0017-release-lifecycle-and-planning.md), [release trust](release-trust.md) and
[ADR 0016](adr/0016-authorization-trust-boundary.md). Closing a milestone, merging a PR or a green workflow
never accepts a release.

## Versioning policy
- **Patch** (`0.1.x`): bug and security fixes and toolchain patch bumps. No change to configuration, evidence
  schemas, manifest shape or adapters.
- **Minor** (`0.x.0`): features, new profiles or tools, toolchain minor bumps, additive schemas. During 0.x also
  any incompatible change, which must be declared in the CHANGELOG.
- **Major** (`x.0.0`): incompatible changes once at 1.0 or later; removed profiles or tools, toolchain majors,
  breaking config, evidence-schema, manifest or adapter contracts.
- **Pre-releases**: `-alpha.N`, `-beta.N`, `-rc.N`. Verified, published as pre-releases, never accepted.
- **Security and emergency**: a patch on the supported line (the newest MAJOR.MINOR). Older affected lines get
  "upgrade". An emergency release uses the same pipeline; there is no bypass of verification or authorization.
- **A toolchain change is a new platform release.** Components inside a published release are never replaced
  (immutable GitHub release plus the write-once store).
- Compatibility surfaces: consumer config (`dev-platform.toml`), evidence schemas, the toolchain manifest, the
  adapter interface and `dev-platform.infra/v1`. `plan version-check` derives change kinds from manifest and schema
  diffs and rejects too small a bump.

### Compatibility during 0.x
Nothing is guaranteed stable across minors, but every incompatibility is declared, checked by tooling, and a
patch release never contains one. Consumers pin an exact version and tree digest (ADR 0002), so a minor bump
cannot reach them unrequested. Records already published stay valid for the release that produced them.

### Criteria for 1.0.0
`planning/release-policy.json` `one_zero_criteria`: an owner-accepted baseline; predecessor continuity verified
(issue #4); two consumers in production profile; evidence schemas unchanged across two minors; infra contract v1
conformance adopted; authenticated application-release approvals (#52). `plan version-check` refuses 1.0.0
unless each is asserted.

## Roadmap (hypotheses; scope follows dependencies and evidence; no dates committed)
| Milestone | Objective |
|---|---|
| v0.1.0 (closed, history) | First trusted candidate; immutable, verified-unaccepted |
| v0.1.2 | Corrected stable candidate (ADR 0016); verified-unaccepted, awaiting the owner |
| v0.1.3 | Corrective patch lane, opened only for defects/advisories (#54) |
| v0.2.0 | Predecessor continuity, advisories, profiles, synthetic consumers, pilot plan, tag signing |
| v0.3.0 | Application-release provenance, authenticated approvals, evidence store, rollback |

The GitHub milestone is authoritative for scope. Each carries Objective, Scope, Verification, Compatibility,
Security and provenance, Exit criteria and Decisions sections; `plan readiness` fails without them. Unscheduled
and proposal items (#16, #18, #20, #48) sit in the Project without a milestone.

## Lifecycle and commands
States: planned, implementation-complete, candidate-built, independently-verified, verified-unaccepted,
accepted; overlays superseded, revoked.
```
dev-platform plan readiness --milestone v0.2.0 [--snapshot f.json]   # exit 1 while work is open
dev-platform plan queue                                               # eligible work by priority, held/blocked listed
dev-platform plan assign [--apply]                                    # PRs inherit the closed issue's milestone
dev-platform plan version-check --previous 0.1.2 --new 0.2.0 --old-manifest old.json
dev-platform plan patches --affected 0.1.2 --existing 0.1.2           # advisory -> patch candidates
dev-platform plan notes --milestone v0.2.0 --version 0.2.0 [--verification rec.json]
dev-platform plan manifest --milestone v0.2.0 --identity identity.json --verification rec.json
dev-platform plan state --milestone v0.2.0 --archive-sha256 .. --ci-verification .. --independent-verification .. \
    --immutable [--verifier tools/verify_release.py --verifier-sha256 <pin> --verifier-arg ..]
```
`accepted` appears only if the pinned verifier, run through `--verifier`, reports it.

## Working with a release awaiting acceptance
The lowest open release milestone has priority; it is not an exclusive queue (`plan queue`). The next
milestone, and unrelated work, continue in parallel while a release awaits acceptance, and a held patch or
pending authorization never blocks them (labels `owner-decision`, `held`, `proposal` mark items that are
waiting on someone else). Agents mark no issue done without a merged PR and never create, sign or attribute
an authorization. Owner-reserved decisions: trust anchors (approver policy, signing keys), acceptance, anything
regulated.

Suspending versus revoking: an unauthenticated notice (an advisory, a report, a file that says "revoked")
suspends use conservatively and is recorded as a warning, never as a governance decision. Revocation or
replacement of an approval needs an authenticated, authorized record evaluated by the pinned verifier
(ADR 0016, 0017).

## Assurance profiles for consumers
`planning/release-policy.json` `assurance`: `open-source` (default) or `regulated` (traceability plus external
attestations the public core cannot evaluate, so absent evidence blocks). Organization-specific policy and
evidence providers live in private infrastructure and are supplied through the platform.
