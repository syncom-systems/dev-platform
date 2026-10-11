# Owner review of the v0.1.0 acceptance packet (2026-10-11)

Recorded as directed by the owner. This is not an authorization.

- Technical verification work: accepted.
- Release acceptance of v0.1.0: **not authorized**. v0.1.0 remains immutable and `verified-unaccepted`.
- The separate `tools/validate_authorization.py` mechanism: **not ratified**. It was removed from `main`; the
  packet that references it is preserved unchanged as a historical record.
- Defect: the pinned verifier (`49ff13fd…`) accepted unauthenticated authorization assertions from arbitrary
  providers. Fixed in the foundation (ADR 0016) and delivered in the corrected candidate v0.1.1.
- v0.1.0 is not to be accepted using the old verifier: its pin is superseded as an acceptance authority.
