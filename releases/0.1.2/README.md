# 0.1.2 records (corrected stable candidate, verified-unaccepted)

Own tag, revision, archive, manifest, SBOM, attestations and verification record (not v0.1.0, not 0.1.1, not an rc).
Release workflow run 38136676056: build, verify, publish succeeded; the publish gate's bounded wait for the
asynchronous release attestation was used ("not yet available") and then `gh release verify` succeeded.

Independent verification: `tools/verify_release.py` from `main` under pinned digests (see `identity.json`), expected
revision from the git tag, archive digest computed locally: 27 checks passed (archive, structure, version and source
binding, SBOM vs manifest, provenance + SBOM + build-environment attestations against the signer policy, environment
evidence, policy-cannot-waive-authorization). State `verified-unaccepted`, `confers: []`.

Rejections observed on this artifact (`rejections.txt`): an unsigned record naming an invented provider (ignored,
"not supported"); a record naming the supported provider that was never committed (ignored, "no commit touches
the path"); wrong source revision; appended byte (no attestation for the new digest); installer refusing the
unaccepted release without `--allow-unaccepted`, and with that flag still recording `verified-unaccepted` even when
handed the invented record; wrong verifier pin (exit 3). Wrong policy pin and the remaining negative authorization
cases are covered by `tests/test_authorization.py` (no signed approval can be fabricated here).

Acceptance packet: `ACCEPTANCE-PACKET.md`. No authorization exists or was created.
