# 0019 Application-release approval trust

Status: Proposed (v0.3.0; implements issue #52 under the ADR 0016 provider model)

## Problem
`rollback select` shape-checked application-release approvals and reported `approval_authentication: unverified`.
Any file with a plausible shape counted as an approval, so a rollback target could be "approved" by anyone, and
nothing re-derived the links (source, dependencies, platform release, toolchain identity, evidence, artifacts).

## Decision
1. **A second independent verifier, `tools/verify_app_release.py`**, imports nothing from `dev_platform` and
   produces `dev-platform.app-release-verification/v1`. It *reuses* the ADR 0016 provider registry
   (`PROVIDERS`, `github-signed-commit`) by loading `tools/verify_release.py` from a path whose sha256 the operator
   pins (`--platform-verifier-sha256`); there is no second provider implementation to drift. `dev_platform`
   (`appverify.AppVerifier`) only runs it under pins and reads its record, as `lifecycle.run_verifier` does.
2. **Application approval is a different decision from platform acceptance.** Authority comes from an
   application-owned policy (`dev-platform.app-trust/v1`, [schema](../../schemas/app-trust-v1.schema.json)), not
   from `trust/policy.json`. A platform approver has no authority over applications; an application approver
   has none over the platform. Approvers are listed per application (`applications`, no wildcard). The policy also
   lists the Dev Platform releases (version + tree digest) the application accepts; whether the platform release
   itself was accepted is not an input, and acceptance of one never implies approval of the other.
3. **The subject is the exact release record**: `subject.digest` is the canonical digest of the
   `app-release/v1` document, which in turn pins source revision, dependency resolution digest, platform
   release version/tree digest/profile, toolchain identity digest, artifact digests and result digests. Changing any
   byte of the record, or an approval of another release, no longer binds. The record's optional `authorizations`
   field is informational and never consulted (an approval cannot be listed in the thing it approves).
4. **An approval confers exactly `application-release-approval`**: eligibility for selection/rollback. It never
   confers platform acceptance, deployment or rollout authorization, regulated release approval, or approval of
   any other release (`approval.not_conferred`).
5. **Binding checks (all must pass, else `failed`)**: release shape; operator-pinned source revision
   (`--source-revision`); dependency resolution recomputed from lock files; artifact bytes recomputed; every
   evidence entry resolved by digest to a supplied `result/v1` that is an executed, certified, pinned, certifiable
   full-stage run whose revision, toolchain identity, platform tree digest/version and profile equal the release's
   (unknown evidence kinds cannot be verified and fail); platform release allowed by the application policy; no
   supplied advisory affects `dev-platform@version`, the application, or (with the platform SBOM) a platform component.
   `--mode select` (rollback) cannot re-read lock files or artifact bytes; it re-derives what digests establish and
   lists the rest under `coverage.not_evaluated`. No advisories supplied is reported, not treated as safe.
6. **Revocation and supersession** use the ADR 0016 rules: only authenticated, authorized records about this exact
   release count; the latest live decision wins; equal timestamps fail closed; `revoked`/`rejected` end eligibility;
   a later approval can re-approve. Removing an approver from the policy ends their approvals (policy is evaluated
   at verification time).
7. **States**: `approved` (checks passed, live authenticated approval), `unapproved` (checks passed, no approval),
   `failed` (any binding check failed, even with an authentic approval). Only `approved` is eligible.
8. **`rollback select` fails closed**: it needs `--app-policy`, `--verifier` and `--platform-verifier` with pins,
   and reports `approval_authentication: verified`. `--unauthenticated` keeps the old shape-check as a labelled
   diagnostic (`unverified`), never an approval.

9. **Evidence is immutable by one pin.** `dev-platform.app-release-evidence/v1` bundles (`src/dev_platform/bundle.py`)
   list every file by sha256; the manifest digest is pinned by the operator. The independent verifier reads bundles
   itself (`--bundle`, `--manifest-sha256`) and uses nothing from a bundle that fails its pin. Rollback targets must
   come from pinned bundles unless `--allow-unbundled`.
10. **Exercised against real consumers.** `tools/qualify.py --app-release` runs the chain over the real certified
   result of each qualification fixture (13 accept/reject cases; GitHub is a double at the `gh api` boundary);
   `tools/pilot.py` assembles the flight pilot's result and requires `unapproved`, even with a forged approval.

11. **Application policy may require an owner-accepted platform release** (0.4.0). A `platform_releases` entry with
   `require_acceptance: true` also names `archive_sha256` and `source_revision`. The verifier then re-runs the
   platform verifier (`--platform-archive`, `--platform-policy` with `--platform-policy-sha256`, platform
   authorizations/bundles) and adds the check `platform-acceptance`: the verified archive must be the one named, the
   release the record was built with, and `acceptance.state` must be `accepted` conferring `platform-baseline`.
   This is an extra eligibility condition only. It never supplies an application approval, platform approvers have no
   authority in the application policy (and the reverse), and a record for one subject cannot bind to the other.
   The same flags exist on `rollback select`; with the requirement set and no platform verification supplied,
   every candidate fails closed. Only one platform archive can be verified per run, so candidates built with another
   platform release are refused rather than guessed at.
12. **Freshness.** `--discover-authorizations` also judges every `authorizations/*.json` at the policy's evidence
   ref, through the same provider path. A revocation that no bundle contains therefore still ends eligibility.
   Without it a stale bundle shows its old approval: the operator must supply the newest evidence or discover.
13. **Live GitHub qualification** (`tools/qualify_live.py`, private fixture repository, `github-actions[bot]` as
   the only identity). GitHub signs API-made commits with its own key and records `web-flow` as committer, so such a
   record is refused by design; the live path therefore reaches `unapproved` for every case, never `approved`. The
   `approved` positive needs a second GitHub identity with its own signing key (an owner provisioning decision) and
   is exercised only against the recording `gh` double (`tools/qualify_rollback.py`: complete bundle -> pinned CLI
   -> verifier-subprocess path with revoked, superseded, vulnerable, tampered, unsigned, edited, non-approver,
   unbundled and evidence-less releases, each refused with its reason).

## Consequences
- The shape validator (`records.validate_authorization`) now requires the assertion shape the verifiers actually
  authenticate (`login`, `path`) and a `scope.confers` matching the subject kind; it previously asked for a
  `reference` field no verifier read.
- Known limits (unchanged from ADR 0016): authenticity depends on GitHub's signature verification at verification
  time; the application policy is a trust anchor the application owner pins out of band; the verifier does not
  prove the artifact was built from the source (that is the result's certified, pinned-platform run) and is not
  hermetic. No regulatory-compliance claim is made.
