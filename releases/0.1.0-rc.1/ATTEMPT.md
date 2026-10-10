# 0.1.0-rc.1: failed attempt (no release published)

Tag `v0.1.0-rc.1` (commit `e0982a9d4529e4894e3e328c5d7b3c108836a54e`) ran the release workflow
(run 38052640477). The build job produced the archive and a SLSA build-provenance attestation, then
failed at `attest-sbom` ("Unsupported SBOM format": the CycloneDX document lacked `serialNumber`).
The verify and publish jobs were skipped. **No GitHub release and no verification record exist for
rc.1; its archive must not be used.** The tag is retained unmoved as evidence. Fixed in 0.1.0-rc.2.
