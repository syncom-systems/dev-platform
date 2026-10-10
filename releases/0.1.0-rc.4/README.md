# 0.1.0-rc.4 records

First pre-release produced by the full pipeline: build in the pinned, closure-verified environment
(`build-environment.json`, certifiable, attested with the archive), separate verify job
(`verification.ci.json`), publish to an **immutable** GitHub release, post-publish assertion
(`immutable == true`, `gh release verify`, `verify-asset`) all green. State: pre-release, verified, not
accepted. Predecessors: rc.1 and rc.3 failed and are retained unpromoted; rc.2 is the earlier verified
pre-release.

Independent verification (from a clean download, `tools/verify_release.py` run from `main`, expected
revision from the local git tag, archive digest computed locally): 21 checks passed, including SBOM
correspondence with the toolchain manifest and the SBOM attestation (`verification.independent.json`).

Trusted installation (`tools/install_release.py`, pins computed from `main`: verifier sha256
`1960284465caf2ea...8604`, policy sha256 `747c510c09377e63...9f30`, revision resolved by `git ls-remote`):
installed write-once; `verification.installer.json` is the stored record. Refusals observed: wrong
verifier pin (exit 3, nothing fetched), no `--allow-prerelease` (exit 1), archive with one appended byte
(attestation signature, SBOM attestation and attested-SBOM content checks fail; nothing installed).

Consumer use of the installed release: the `python` fixture, pinned to this release, at `full` on a clean
git tree under the pinned interpreter: certified (`consumer-qualification.result.json`).

Not established: stable acceptance (owner authorization record), any certification of the release
itself beyond its build environment, Windows/aarch64 platforms.
