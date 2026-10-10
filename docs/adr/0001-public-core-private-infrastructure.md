# ADR 0001: Public core, private infrastructure

Status: Ratified

## Context
Organization-specific facts (runner inventory, routing, deployment, private integrations) must not
leak into a public repository, and public users must never need them.

## Decision
- `dev-platform` is public and self-sufficient: install, build, local checks and public CI work with
  no access to `dev-platform-infra`.
- The only coupling is a versioned data contract, `dev-platform.infra/v1`
  ([schema](../../schemas/infra-profile-v1.schema.json)): an infrastructure provider supplies a JSON
  runner profile; the platform consumes it via `--infra-profile`. Data flows private -> public at run
  time; no code or secret flows the other way and nothing private is committed here.
- The contract is additive within a major version; the platform rejects an unknown `schema`.
- The absence of a profile is a normal state: routing falls back to GitHub-hosted runners.

## Consequences
Private routing can change without a platform release. The contract stays deliberately small
(runner inventory only) until a second concrete need appears. `dev-platform-infra` was not accessed
during the initial implementation.
