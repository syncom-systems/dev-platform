# 0.1.0 records (stable candidate, verified-unaccepted)

Own tag, source revision and archive; not the rc.4 or rc.5 artifact. Published through the release
workflow after the rc.5 rehearsal exercised the same paths. The GitHub release is immutable, a
pre-release titled "NOT accepted".

Independent verification, unmodified `tools/verify_release.py` run from `main` under explicitly pinned
verifier and policy digests (see `identity.json`), expected revision from the git tag, archive digest
computed locally: all 26 checks passed (archive, structure, version and source binding, SBOM vs manifest,
provenance and SBOM and build-environment attestations against the signer policy, environment evidence
against the manifest pins). Acceptance state: `verified-unaccepted`: no owner authorization exists.
`verification.installer.json` is the record stored by `tools/install_release.py`, which refused without
`--allow-unaccepted`.

Observed rejections on this artifact: wrong source revision; appended byte (no attestation for the new
digest); other version claimed; build-environment record missing (policy requires it); the rc.4
environment record (no scope statement, wrong source revision); wrong verifier pin and wrong policy pin
(exit 3).

The environment evidence is not a hermeticity claim: system libraries are trusted by name, host kernel,
CPU and filesystem are outside it (see `build-environment.json` `scope`).

Consumer use: the `python` fixture pinned to this release, `full` stage, clean tree, certified
(`consumer-use.result.json`) - certification of that consumer's checks, not of this release.

Owner decision required: an authorization record (kind `platform-release`, digest = archive sha256).
