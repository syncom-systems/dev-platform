# ADR 0002: Immutable side-by-side versions and pinning

Status: Ratified, amended by [ADR 0010](0010-unified-platform-and-toolchain-releases.md) (a release includes its toolchain profiles)

## Decision
- A platform release is an immutable directory `<store>/<version>/` holding `src/dev_platform/`.
  Many versions coexist; nothing is installed globally or mutated in place.
- A consumer pins an exact `version` and the `sha256` tree digest of that directory in
  `dev-platform.toml`. Ranges are rejected by the config validator.
- Resolution verifies the digest on every invocation. A mismatch or missing version is a hard
  failure (exit 3), never a fallback to another version.
- Consumers never execute code from the platform's development checkout implicitly (ADR 0003).

## Consequences
Upgrades are an explicit, reviewable diff in the consumer (version + digest). Digest verification
costs one tree hash per invocation (small tree; measure before optimizing). See ADR 0009 for how
releases are produced and authenticated.
