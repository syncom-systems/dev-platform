# Release management

Planning (GitHub) and trust (the independent verifier) are separate. The owner releases; pushing a protected version
tag is the release decision and a release that passes every check is `verified` ([ADR 0024](adr/0024-single-owner-release-authority.md),
[release trust](release-trust.md), [ADR 0017](adr/0017-release-lifecycle-and-planning.md)). Closing a milestone,
merging a PR or a green workflow never makes a release verified; only the verifier does.

## Routine release
Two ordinary instructions from the owner, no other approvals:

> **Owner:** Is it ready to release?
>
> **Agent** runs `python3 tools/release.py ready [--version V] [--kind feature ...]` and answers with its verdict:
> `READY TO RELEASE — v0.12.0 (after 0.11.0; commit 1a2b3c4d5e6f)` and the checks that passed, or `BLOCKED` and
> the problems to correct.
>
> **Owner:** Go ahead and release.
>
> **Agent** runs `python3 tools/release.py publish --version 0.12.0` and reports its result: the merged version
> commit, the release workflow run, archive and tree digests, the state (`verified`), the release records and the
> Homebrew tap update.

`ready` changes nothing. It finds the predecessor (the newest published stable release, checked against its recorded
identity), derives change kinds from toolchain-manifest and schema differences and adds the declared ones, proposes or
checks the version against `planning/release-policy.json`, refuses an existing tag, runs the unit tests, lint and the
docs check, applies the version and release notes to an export of the tracked files (so an ignored local file can
never reach the archive), builds it twice and requires identical digests, and runs the predecessor's full stage over
the source as the release workflow will (`--skip-continuity` to save time).

`publish` (after the go-ahead, without further questions):
1. finalizes the version: `__version__`, the continuity predecessor in `trust/policy.json` and the notes under
   `## Unreleased` of `CHANGELOG.md` become `## <version>`, in a pull request merged when its required checks pass;
   the merge must change exactly those three files;
2. pushes the annotated tag `v<version>` on that merge commit, which starts `release.yml` (build, provenance and SBOM
   attestations, predecessor continuity, independent verification, immutable publication), and waits for it;
3. downloads the published assets, checks GitHub's digests, `gh release verify` and `verify-asset`, and re-runs the
   verifier and policy of the tagged revision outside CI;
4. records `releases/<version>/` (identity, both verification records, build environment, continuity, Homebrew
   formula) and updates the formula in the tap, each in a pull request merged when its checks pass (the tap's checks
   install the formula on macOS and Linux and verify the archive with the release's own trusted installer).

Every step is skipped when already done, so an interrupted `publish` resumes when run again; `records --version V`
runs steps 3 and 4 alone. It stops at the first failed check or verification, unexpected security finding, change
of scope or missing permission, and reports it; nothing is bypassed. Commits and pull requests are made with the
caller's `gh` identity and checkout (`--trailer` adds attribution lines). Not part of a routine release: retiring
legacy infrastructure software and changing runner infrastructure (separate operational work). The public
infrastructure compatibility tests run in the release's unit tests; an organization's private qualification runs in
its own repository against the published release.

## Versioning policy
- **Patch** (`0.1.x`): bug and security fixes and toolchain patch bumps. No change to configuration, evidence
  schemas, manifest shape or adapters.
- **Minor** (`0.x.0`): features, new profiles or tools, toolchain minor bumps, additive schemas. During 0.x also
  any incompatible change, which must be declared in the CHANGELOG.
- **Major** (`x.0.0`): incompatible changes once at 1.0 or later; removed profiles or tools, toolchain majors,
  breaking config, evidence-schema, manifest or adapter contracts.
- **Pre-releases**: `-alpha.N`, `-beta.N`, `-rc.N`. Verified, published as pre-releases (`--allow-prerelease`).
- **Security and emergency**: a patch on the supported line (the newest MAJOR.MINOR). Older affected lines get
  "upgrade". An emergency release uses the same pipeline; there is no bypass of verification.
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
`planning/release-policy.json` `one_zero_criteria`: a released stable baseline; predecessor continuity verified
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
States: planned, implementation-complete, candidate-built, independently-verified, released (trust/v2, from 0.12.0;
releases up to 0.11.0 end at verified-unaccepted or accepted); overlays superseded, revoked.
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
`accepted` (releases up to 0.11.0) appears only if the pinned verifier, run through `--verifier`, reports it.

## Priorities
The lowest open release milestone has priority; it is not an exclusive queue (`plan queue`). Unrelated work
continues in parallel, and a held item never blocks it (labels `owner-decision`, `held`, `proposal` mark items that
are waiting on someone else). Agents mark no issue done without a merged PR. Owner-reserved decisions: trust anchors
(the trust policy's signers, signing keys), GitHub permissions and rulesets, anything regulated.

An advisory or report about a release suspends its use conservatively and is recorded as a warning. A release is
never changed or re-published: a fix is a new release that consumers pin.

## Assurance profiles for consumers
`planning/release-policy.json` `assurance`: `open-source` (default) or `regulated` (traceability plus external
attestations the public core cannot evaluate, so absent evidence blocks). Organization-specific policy and
evidence providers live in private infrastructure and are supplied through the platform.
