# ADR 0009: Distribution and integrity

Status: Proposed. Design in [distribution.md](../distribution.md).

- Release = a tagged, deterministic source tree; integrity pin = sha256 tree digest
  (`dev-platform digest`).
- Today's trust anchor is the digest committed in the consumer repository (reviewed in a PR).
  Producer authenticity (signed tags, Sigstore/SLSA provenance) is specified but **not yet
  implemented**; the first release must not be described as signed.
