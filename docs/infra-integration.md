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
              "isolation": "ephemeral", "trust": "public|trusted", "credentials": ["<class names only>"],
              "capabilities": ["<optional, e.g. tmux, qemu-aarch64>"], "cache": "none|read-only|read-write"}],
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

## Capabilities, cache and diagnostics (additive, issue #20)
A runner may offer `capabilities` and a `cache` mode. A project requirement (`[runner.<name>]` in
`dev-platform.toml`) may ask for `capabilities = [...]` and `cache = "none|read-only|read-write"`; a runner
without the capability, or with another or unspecified cache mode, does not fit. A `public`-trust runner must
not have a `read-write` shared cache (profile validation). When nothing fits, the denial names every offered
runner and the first reason it did not fit (trust, os, arch, isolation, credentials, capability, cache): there is
no silent downgrade.

## Compatibility between the platform release and the provider's profile
The public contract a platform release speaks is the `dev-platform.infra/v1` code it ships (the engine runs the consumer's
pinned release, so the validator, routing and the resolution check are that release's). Compatibility is therefore decided
three ways, all fail-closed: the profile must validate under that release's `dev-platform.infra/v1`; a resolver result must
name `contract: dev-platform.infra/v1` (anything else is `unsupported contract`); and the resolved configuration must equal the
consumer's pin. A provider that adds a field or a new schema version is incompatible with older releases until the consumer
pins a platform release that understands it, and the pinned configuration digest changes with it. Releases:
`dev-platform.infra/v1` and capabilities/cache since 0.1.x; pin, resolver, `check-resolution` and per-job facts 0.8.0.

## Per-job facts for providers (issue #100)
`dev-platform pr-check --facts` (or `prcheck.check(files, profile, facts=True)`) adds `facts` to the output: per workflow file the
`triggers` and the `pr_reachable_triggers`, and per job its resolved `runs_on` label sets (or `unresolved` with the reason),
declared `environment`, reusable-workflow `uses` and a best-effort source `line`. They come from the same conservative reader that
decides admission, so a provider needs no private workflow scanner; shapes the reader cannot interpret stay `unresolved` and
`incomplete`. Facts never change the admission decision.

Two further per-job fields (issue #128, on main; first released in the release after 0.8.2):
- `non_public_label_sets`: the resolved `runs_on` label sets the supplied profile does not admit, by the same rule
  `check_workflow` applies to PR-reachable workflows (hosted labels, or a subset of a `trust: public` runner). `[]` means every
  resolved set is admitted; `null` means the job is unresolved and nothing is concluded. `null` must never be read as admitted.
  The protected-environment exemption is not applied here: compare `environment` against the profile's
  `admission.protected_environments` yourself.
- `runs_on_group` / `runs_on_labels`: for `runs-on: {group: ..., labels: ...}`, the values exactly as written (raw strings,
  never evaluated; an expression is returned verbatim). Such a job stays `unresolved` (`runs_on` and `non_public_label_sets` are
  `null`) and `incomplete`, because the profile has no runner-group concept to judge it by. A provider that can resolve the group
  against its own authorization evidence decides pass/fail itself; an unresolved group must not be treated as admitted.

## Consumer-owned pin of the configuration release (ADR 0021)
The consumer declares which configuration release it expects; the platform never takes a path on faith.
```toml
[infra]
provider = "acme-infra"
config_release = "1.4.0"            # exact; no ranges, no "latest"
config_digest = "sha256:<64 hex>"   # identity: `dev-platform infra digest profile.json` for a vendored profile
```
- **Untrusted CI (no private access):** commit the profile in the consumer repository and pass `--infra-profile`; it is used
  only if its sha256 equals `config_digest`. No provider is ever invoked for an untrusted event.
- **Trusted CI:** the operator may supply `--infra-resolver "<command>"`. It receives a
  `dev-platform.infra-resolve-request/v1` on stdin and returns a `dev-platform.infra-resolve-result/v1` on stdout with the
  profile written to `profile_out`. The resolved version and digest must equal the pin; otherwise `unavailable`.
- **Provider CI:** `dev-platform infra check-resolution --config-release V --config-digest D --result result.json
  --profile profile.json` judges a result exactly as the engine does; `contracts/infra/v1/resolution-cases.json` holds the
  cases (stale, newer, mismatch, denied, unsupported contract, missing profile, narrowed by a newer policy).
- The result record's `infra` block carries pinned, resolved, authorization policy and effective profile digest.

## Consumer side
A consumer passes the profile with `dev-platform check --infra-profile profile.json --event-trust <trusted|untrusted>`;
routing then offers private runners only to trusted events and credentials only to trusted events, and refuses
silent downgrade. The platform never accepts trust from project configuration.

## Boundaries
- Credentials appear as class names only, never values; inventory, hostnames and secrets stay private.
- Enforcement is GitHub settings (runner groups, environments, fork approval); the platform informs (ADR 0005).
- Anything the checker cannot resolve is `incomplete` (blocks admission), never silently passed.
