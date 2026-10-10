# ADR 0014: Release trust, bootstrap and verify-then-execute

Status: Ratified (mechanisms implemented where stated)

Supersedes the launcher mechanism of [ADR 0003](0003-version-selection-and-overrides.md) (the
override rules there stand) and the TOCTOU limitation recorded in the architecture notes.

- **Race closed (implemented).** The launcher copies the release into a private `0700` directory
  while hashing the exact bytes copied, compares to the pin, runs the child from that copy, and
  deletes it. The child re-verifies the tree it runs from. Mutating the store after resolution cannot
  change what executes (`test_verified_bytes_are_the_executed_bytes`).
- **Self-hosted results never establish trust (implemented).** `self` and `override` modes are not
  certifiable. A release is trustworthy only via an *independent* trust root, below.
- **Trust roots (designed).** (1) The digest committed in the consumer repository (reviewed change).
  (2) For bootstrap, the release's Sigstore attestation verified with `gh attestation verify` against
  repository `syncom-systems/dev-platform` and the release workflow identity, **by a tool not taken
  from the release being verified** (GitHub CLI / cosign). (3) Protection against substitution:
  write-once store, digest pin, tag protection and required review on the release workflow.
- **Self-release.** Release N is produced by the workflow at a protected tag, verified by release N-1
  (pinned) re-running its full stage over N's source, and attested. The first release has no N-1: it
  is bootstrapped by owner verification of the attestation and manual digest pin, and is documented
  as such. This is **not yet performed**; no release has been signed.

## Owner ratifications (2026-10-10)
1. The first release may be accepted through an explicit owner authorization record, but only after
   independent verification of source revision, artifact digest, toolchain manifest, build
   provenance, signing identity and release process. The authorization is the initial trust anchor and
   never replaces technical verification (`tools/verify_release.py` computes acceptance in that order).
2. `dev-platform.result/v1` is retained. After the first public release, incompatible changes require
   a new schema version.
3. Version-prefix probes are development diagnostics only (ADR 0010, identity strength).

## Implemented
Deterministic archive, write-once verified installer, independent verifier with trust policy,
three-job release workflow with Sigstore provenance and SBOM attestations, SHA-pinned actions, tag
ruleset (`v*` cannot be deleted or moved) and repository immutable releases. First exercise:
`0.1.0-rc.2` (see `releases/0.1.0-rc.2/`); `0.1.0-rc.1` failed at SBOM attestation and was retained
as evidence (`releases/0.1.0-rc.1/ATTEMPT.md`).
