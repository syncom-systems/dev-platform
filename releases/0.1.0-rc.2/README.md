# 0.1.0-rc.2 verification records

Pre-release. Verified by the release pipeline's separate verify job (`verification.ci.json`) and again
independently from a clean download using `tools/verify_release.py` run from `main`
(`verification.independent.json`): expected source revision taken from the local git tag, expected
archive digest computed locally, policy from the repository. Installing the archive with
`release install` reproduced the published tree digest.

Negative checks run against the same artifact, all failing as required: wrong source revision, an
archive with one appended byte (digest mismatch, and no attestation exists for its digest), a policy
naming a different signer workflow, and claiming the rc archive as stable `0.1.0`. The SBOM
attestation (`https://cyclonedx.org/bom`) also verified with `gh attestation verify`.

Not established: stable acceptance (needs an owner authorization record), tool-identity strength
sufficient for certification (release profile tools are `version-only`), tag/release immutability
rules on the repository.
