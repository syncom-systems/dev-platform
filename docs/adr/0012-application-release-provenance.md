# ADR 0012: Application release provenance

Status: Ratified

- The **application release** is the atomic unit of deployment and rollback.
- `dev-platform.app-release/v1` references (by digest) the exact source revision, dependency
  resolution, platform release + profile + toolchain identity digest, built artifact digests,
  verification evidence (result records) and authorization records.
- **Rollback is selection** of a previously approved application artifact, never reverting
  compilers/dependencies or rebuilding history.
- Scope limit: dev-platform defines and validates these records. It does not deploy, approve, or
  store them long-term; external release and governance systems consume them.
