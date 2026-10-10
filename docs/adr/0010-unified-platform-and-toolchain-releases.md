# ADR 0010: Unified platform and toolchain releases

Status: Ratified

Supersedes the definition of "release" in [ADR 0002](0002-immutable-versions-and-pinning.md)
(a release is no longer only orchestration code).

## Decision
- A dev-platform release is an immutable, tested **development environment**. Its identity
  (`release.json`, `dev-platform.release/v1`) contains the toolchain manifest
  (`dev-platform.toolchains/v1`): named **profiles**, each listing tools with an exact version, how to
  probe it, an optional binary sha256, and a package URL for the SBOM.
- A consumer pins one release (version + tree digest) **and one profile** from it. There is no
  per-tool override: a different tool version is a different release.
- Toolchain upgrades, including security fixes, are new releases. Existing releases and the
  consumers pinned to them never change until a consumer edits its pin.
- **Environment verification.** Before any claim is made, the platform probes the environment and
  records `environment` in every result: per-tool expected/observed/status/identity
  (`version-only | digest-verified | bazel-reconciled`) and an `identity_digest` over what was
  observed. A non-conformant environment blocks admission and certification. Missing tools are
  `unavailable`, never a pass.
- **Bazel stays the executor.** Tools marked `bazel_managed` are never executed or replaced by the
  platform; their *declarations* in the consumer (e.g. `.bazelversion`) are reconciled against the
  manifest. Competing compiler paths are not introduced.

## Consequences
Tool identity is only as strong as the probe: `version-only` is weaker than `digest-verified`; results
say which one applied. Hermetic Bazel toolchain digests (module lock files) are a planned
reconciliation source (milestone M3).
