# Integrating an infrastructure provider (dev-platform.infra/v1)

The public platform and a private infrastructure repository (for example `dev-platform-infra`) are coupled by
exactly one data contract, `dev-platform.infra/v1` ([ADR 0001](adr/0001-public-core-private-infrastructure.md),
[ADR 0018](adr/0018-admission-policy-single-contract.md)). The provider never imports platform code and the
platform never reads provider internals: the provider emits a profile (JSON) and its own CI runs the public
tools below against it. Nothing here requires access to the private repository.

## What the provider supplies
```json
{"schema": "dev-platform.infra/v1",
 "runners": [{"id": "...", "labels": ["..."], "os": "linux", "arch": "x86_64",
              "isolation": "ephemeral", "trust": "public|trusted", "credentials": ["<class names only>"]}],
 "admission": {"forbidden_triggers": ["pull_request_target"], "protected_environments": ["<names>"]}}
```
`admission` is optional and organization-owned. Event trust is never configurable: it is derived by the
platform (`runners.event_trust`).

## What the provider runs in its own CI (public tools, pinned release)
| Step | Command | Fails when |
|---|---|---|
| Profile is valid | `dev-platform infra check profile.json` | unknown keys, duplicate ids, bad enums, credentials on a non-trusted runner, unknown triggers |
| Public repositories never get persistent runners | `dev-platform infra check profile.json --repo-visibility public` | warning (select another profile for public repositories) |
| Consumer workflows respect the admission policy | `dev-platform infra check profile.json --workflows .github/workflows` or `dev-platform pr-check --infra-profile profile.json` | a PR-reachable job selects a non-public runner without a protected environment, or uses a forbidden trigger (`failed`); unresolvable workflows (`unavailable`) |
| Routing semantics are unchanged | the conformance kit `contracts/infra/v1` (profiles, routing, event-trust and pr-check cases) | any case differs |
| Event trust for a context | `dev-platform infra event-trust --event pull_request --head-repo a/b --base-repo a/b` | n/a (prints `trusted`/`untrusted`) |

## Consumer side
A consumer passes the profile with `dev-platform check --infra-profile profile.json --event-trust <trusted|untrusted>`;
routing then offers private runners only to trusted events and credentials only to trusted events, and refuses
silent downgrade. The platform never accepts trust from project configuration.

## Boundaries
- Credentials appear as class names only, never values; inventory, hostnames and secrets stay private.
- Enforcement is GitHub settings (runner groups, environments, fork approval); the platform informs (ADR 0005).
- Anything the checker cannot resolve is `incomplete` (blocks admission), never silently passed.
