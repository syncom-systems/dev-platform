# ADR 0013: Governance and auditability

Status: Ratified (record shape Proposed)

Four distinct concepts, four distinct records, linked only by digest:
1. **Technical execution identity** - result `environment` + `platform` (what ran, on what).
2. **Verification evidence** - `dev-platform.result/v1`.
3. **Change authorization / release approval** - `dev-platform.authorization/v1`: subject digest,
   decision (`approved|rejected|revoked`), approver id + role + **identity assertion** (provider +
   reference), basis, UTC timestamp, explicit `supersedes`, and retention (class + until/indefinite).
4. **Release** - the app-release record.

Git commit authorship is never approval: the validator rejects `git-commit-author` as an identity
provider. Effective decisions are derived from explicit supersession, not from clock order alone.
Records are append-only by convention; retention and tamper-evidence are the storing system's duty
(see [provenance-and-governance.md](../provenance-and-governance.md)). The platform does not claim
regulatory compliance (e.g. for pharmacovigilance); it supplies evidence an accountable quality
system can use.
