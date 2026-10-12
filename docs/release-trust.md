# Release trust, bootstrap and self-release

Normative decision: [ADR 0014](adr/0014-release-trust-bootstrap-and-execution.md).

## Verify-then-execute (implemented)
1. Launcher reads the consumer pin.
2. It snapshots `<store>/<version>` into a fresh `0700` temp dir, hashing the exact bytes written.
3. If the digest differs from the pin: abort (exit 3), delete the snapshot.
4. It runs the child from the snapshot (`PYTHONPATH`, no bytecode writes); the child re-hashes the
   tree it runs from and refuses a mismatch.
5. The snapshot is deleted afterwards. Residual risk: a same-user attacker can modify the running
   snapshot (it is writable by its owner); the threat model excludes same-user compromise.

## Release pipeline (implemented; first exercise recorded in the pre-release notes)
`release.yml` on a version tag: tag commit must be an ancestor of `main` -> unit tests ->
`release build` (strict: `__version__` must equal the tag) -> `release pack` (deterministic tar.gz) ->
`attest-build-provenance` (Sigstore, SLSA v1) and `attest-sbom` -> separate read-only **verify** job
runs `tools/verify_release.py` with `trust/policy.json` -> **publish** (pre-release flag when the
version contains `-`) with the archive, `.sha256`, SBOM and the verification record attached.

## Independent verification
`tools/verify_release.py` imports nothing from `dev_platform` (its digest/structure logic is a
deliberate second implementation, tested to agree) and uses `gh attestation verify` as the signature
verifier. Checks, each recorded in a `dev-platform.verification/v1` record: archive digest; safe
extraction; version binding (archive root = `release.json` = source `__version__` = expected);
source digest; **source revision** recorded in `release.json` = expected; SBOM digest and toolchain
coverage; tree digest; policy allows the ref; `gh attestation verify` pinned to repo, signer workflow,
source digest and ref, GitHub-hosted runner; then **our own re-check of the signing certificate**
against the policy (issuer, source repository, revision, ref, signer workflow, runner) and of the
attestation subject digest and predicate type.

## Signature is not trust
A valid Sigstore signature only proves *some* GitHub workflow signed the bytes. Trust requires the
signer to match `trust/policy.json` (repository, workflow path, tag-ref pattern). Even then:
- **Pre-releases** end at `pre-release`: verified artifacts, never accepted, never certified.
- **Stable releases** end at `verified-unaccepted` unless an *authenticated, authorized, in-force*
  `dev-platform.authorization/v1` record exists: kind `platform-release`, digest = archive sha256, identity
  verified by the verifier through a registered provider (`github-signed-commit`), signer listed as an approver
  in `trust/policy.json`, `scope.confers` within that approver's authority and within `platform-baseline`,
  inside its validity window, not superseded or revoked. Unsigned records, invented providers, git authorship
  and unlisted identities are ignored. Only the owner can create it; the workflow and the verifier cannot.
  Acceptance confers `platform-baseline` only, never certification, qualification or consumer migration
  ([ADR 0016](adr/0016-authorization-trust-boundary.md)).
Verification records are attached to the release and retained in git under `releases/<version>/`.

## Trust roots and bootstrap
| Question | Trust root |
|---|---|
| Is this the release my repo pinned? | digest committed in the consumer repo (reviewed diff) |
| Was this release built by the project's workflow from that source? | Sigstore attestation, checked with `gh attestation verify <archive> --repo syncom-systems/dev-platform` using a verifier **not shipped inside the release** |
| Can a release be substituted? | write-once store; digest pin; protected tags; required review on `release.yml` |

Fresh machine: obtain the archive, verify the attestation with the independent verifier, check the
archive digest, unpack to the store (never executing release code first), then run normally.

## Self-release and predecessor continuity
A result produced by a release about itself (`mode = self`) is never certifiable. `trust/policy.json` names
the predecessor N-1 (version, archive sha256, tree digest); `null` declares a first release. For release N,
`tools/run_continuity.py` (in a job with a read-only token and no OIDC or attestation permissions) downloads N-1, has the independent
verifier check it against those pins, then runs N-1's own `dev_platform check --stage full` in N's checkout.
The resulting `dev-platform.continuity/v1` record is attested by the release workflow and published with the
release; `tools/verify_release.py --continuity` fails verification unless the record names exactly the policy's
predecessor, was produced over N's source revision and archive, shows N-1 itself verified (it may be
verified-unaccepted) and a passing full stage, and carries a valid attestation.

A policy belongs to the release it was written for. Because it pins release N's predecessor, `main`'s `trust/policy.json`
verifies only the newest candidate; verifying any earlier release (for acceptance or audit) uses the policy at that
release's source revision (`git show <revision>:trust/policy.json`, digest in its packet), with the approver entry
added as a separate pinned file. Using `main`'s policy for an older release fails the `continuity` check by design
(observed for v0.2.1); it is not a defect of that release.

Continuity is *evidence, never authority*: it cannot make N accepted (only an authenticated authorization can),
and N-1 being accepted does not either. The operator's pins stay the root of trust. The first release's
acceptance is an owner action recorded as an authorization (ADR 0016).

## Immutable releases (observed behavior)
See `releases/probes/immutability-2026-10-10.md` for the probe, including failure cases. Summary: a
published release rejects asset upload, overwrite and deletion and tag move/delete; but deleting the
release (admin) then permits deleting the tag, so the `v*` tag ruleset is required alongside immutable
releases. `release.yml` ends by asserting the new release is immutable and by running
`gh release verify` / `verify-asset`; if the repository setting is missing it fails loudly after
publication (the release must then not be used or accepted). A failed publication leaves the tag and
its diagnostics in place as history (`releases/<version>/ATTEMPT.md`); the version is never reused.

## Trusted installation (`tools/install_release.py`)
```
python3 tools/install_release.py --version 0.1.0 --store ~/.dev-platform/store \
  --verifier-sha256 <pin> --policy-sha256 <pin> [--tree-sha256 <consumer pin>] \
  [--allow-prerelease | --allow-unaccepted] [--previous-record <record>]
```
Order (nothing from the archive is imported or executed): check the pinned digests of the verifier and
trust policy (exit 3 if they differ) -> obtain the archive -> resolve the expected commit from the git
tag -> independent verification, including the SBOM attestation -> admission by acceptance state ->
extract the verified bytes to staging, require the verified tree digest -> atomic write-once rename,
freeze read-only, store the verification record under `<store>/.records/`. A pre-release installs only
with `--allow-prerelease`, a stable release that lacks an owner authorization only with
`--allow-unaccepted`; the admitted state is recorded. The verifier is executed from the exact bytes that
were hashed, not re-read from the path. `--previous-record` adds continuity evidence (is the signer
policy unchanged since a previously verified release); it is informational and never substitutes for
the operator's pins.

The operator obtains the two pins out of band (for example from a reviewed commit of this repository
whose history they trust, compared against a second source). The pins are the root; the release being
installed cannot supply or alter them. `dev-platform release install` remains the low-level installer
that takes already-trusted digests and performs no provenance verification.

Planning and lifecycle (milestones, readiness, version policy) are separate from this trust model: see [release management](release-management.md).
