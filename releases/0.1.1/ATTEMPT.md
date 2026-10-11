# 0.1.1: failed attempt (never promoted)

Tag `v0.1.1`, revision `983478bfaa4ab745df11513a424fe1e958109f47`, release workflow run 38135756220.
Build and verify jobs passed; the publish job **failed** at its final gate: `gh release verify` reported
"no attestations for tag v0.1.1" one second after publication (GitHub creates the immutable-release attestation
asynchronously). The release object exists, is immutable and was published as a pre-release; minutes later
`gh release verify` and `verify-asset` succeed. Archive sha256
`2cd705be9ff7fcd87aaef6f55a06912995412ccbc2260309a412bccea2476eec`.

Because the workflow's own gate failed, this candidate is **not promoted, not retroactively passed and not offered
for acceptance**, regardless of the later successful check. The workflow gate was the defect (no wait for the
asynchronous attestation); it is fixed by a bounded retry, and the corrected candidate is v0.1.2.
Do not install or accept 0.1.1.
