# ADR 0005: Logical runner requirements and trust-based routing

Status: Ratified

## Decision
- Projects declare **logical** requirements (`[runner.<name>]`: os, arch, isolation, credentials,
  fallback). Physical names and labels are rejected in project configuration.
- Routing maps a requirement onto offered runners: the infra profile first, then the built-in
  GitHub-hosted runners (unless `fallback = "none"`).
- **Trust is an input from the CI event**, not from project config (`--event-trust`, default
  `untrusted`). Untrusted events only reach `trust = public` runners and never credentials.
- Unsatisfiable requirements yield an *unroutable* check, which blocks admission. There is no
  silent downgrade.
- Routing is advisory about *where*; GitHub permissions, runner groups and repository settings
  remain the enforcement. The platform must never be the only control keeping untrusted code off a
  trusted runner (see nga's fork-PR rule in the investigation notes).
