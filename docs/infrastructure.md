# Infrastructure configuration (optional)

Decision: [ADR 0023](adr/0023-infrastructure-capabilities-in-the-public-platform.md). Contract details:
[infra integration](infra-integration.md). What moved from the private repository: [consolidation](infra-consolidation.md).

Everything here is optional and nothing is activated by installing the CLI or by a capability being available. Commands
read, validate and preview; the few that write create reviewable files in the directory you name, and never commit,
push, enable a workflow, register a runner, bind a credential or change a GitHub setting. Activation is always a
separate change you make through your own review (committing a workflow, registering a runner, changing a setting).

## GitHub-hosted CI only (no infrastructure repository)
A project that has pinned a platform release (`dev-platform.toml` and `dev-platform.release-pins.json`,
[consumer integration](consumer-integration.md)) needs nothing else for GitHub-hosted CI:
```sh
dev-platform workflow                         # print the proposed workflow (stdout only)
dev-platform workflow --runs-on macos-15      # another GitHub-hosted image
dev-platform workflow --output proposed.yml   # or write a new file; an existing file is never replaced
```
The proposal calls the reusable `consumer-pilot.yml` at the project's pinned release on a GitHub-hosted runner with a
read-only token and calls no provider, so it is safe for pull requests from forks. It becomes active only when you
commit it under `.github/workflows/`. Without an `[infra]` pin the engine offers hosted runners only (`ubuntu-*`,
`macos-*`); there is nothing to configure.

Validated GitHub-hosted runner classes (`examples/infra/github-hosted/config/infra.v1.json`):

| id | label | os | arch | provisionable |
|---|---|---|---|---|
| `github-ubuntu-24.04` | `ubuntu-24.04` | linux | x86_64 | yes |
| `github-ubuntu-24.04-arm` | `ubuntu-24.04-arm` | linux | arm64 | no toolchain sources yet |
| `github-macos-15` | `macos-15` | macos | arm64 | yes |

## An organization's configuration repository
An organization that wants its own runners, caches or credentials keeps a configuration repository (usually
private). The public CLI provides the tools; the values are the organization's.
```sh
dev-platform infra init --owner my-org --repo app --repo site                       # GitHub-hosted only
dev-platform infra init --owner my-org --repo app --template self-hosted --force    # plus one declared runner class
dev-platform infra validate .                       # config, releases and policy (read-only)
dev-platform infra profile --repo app               # preview the dev-platform.infra/v1 profile of one repository
dev-platform infra validate . --workflows ../app/.github/workflows --repo app   # admission, unknown runner groups
dev-platform infra release build 2026.10.1          # freeze into an immutable release (CalVer)
dev-platform infra release verify --root . --base-index <the protected branch's releases/index.v1.json>
```
Layout:
```
config/infra.v1.json            dev-platform.infra-config/v1: the declared configuration (schemas/infra-config-v1.schema.json)
authorization/current.v1.json   the current authorization policy (narrows, never grants)
releases/index.v1.json          release identities (append-only)
releases/<YYYY.MM.N>/           immutable releases: manifest, infra-config.json, profiles/<repository>.json
```
`dev-platform.infra-config/v1` declares runners (`placement` github-hosted or self-hosted, labels, os, arch,
isolation, `trust` = which events a runner may serve, credential classes, capabilities, cache mode), runner groups
(repositories, whether public repositories are allowed), caches (modes per event trust; untrusted is always `none`),
credential references (class, provider, scope, binding; never values), repositories (visibility, assigned runners,
cache, desired settings) and the admission policy. Validation fails closed: unknown keys, an undeclared runner group,
a runner group that does not admit a repository, a credential class without a reference, a persistent runner for
untrusted events or a public repository, a self-hosted runner carrying a lone GitHub-hosted label, a shared cache for a
public repository and secret-shaped values are all errors. `validate` lists what configuration cannot establish:
**a declared runner is not thereby registered, available or secure**; GitHub runner groups, protected environments,
job permissions, credentials and host isolation enforce access.

## Consumers of an organization's configuration
The consumer pins the exact release and its release-tree digest:
```toml
[infra]
provider = "my-org-infra"
config_release = "2026.10.1"
config_digest = "sha256:<release-tree digest from the release index>"
config_digest_kind = "release-tree"
```
Untrusted events (fork pull requests) never consult a provider: hosted runners only. In a trusted job the operator
chooses the provider explicitly; nothing finds or imports one automatically:
```sh
dev-platform infra store fetch --project . --source my-org/infra   # exactly the pinned release + current policy (gh)
dev-platform infra store import 2026.10.1 --digest sha256:... --from ../infra --with-policy   # from a local checkout
dev-platform infra store sync --source my-org/infra                # refresh the policy (forward only)
dev-platform infra store list
dev-platform infra doctor --project .                              # identities and the decision only
dev-platform check --stage full --event-trust trusted \
  --infra-resolver "dev-platform infra resolve --root $RUNNER_TEMP/dev-platform/infra"   # the job-local store
```
The store (`<data root>/infra`: `DEV_PLATFORM_HOME`, a job-local `$RUNNER_TEMP/dev-platform` in CI, else
`~/.local/share/dev-platform`) holds releases side by side, read-only and write-once. `brew upgrade` never touches it,
and a newer CLI resolves every older release unchanged. Rolling back is pinning the previous release and digest; the
current policy still applies, so a rollback can never reinstate something withdrawn or revoked since.

## Observing infrastructure (read-only)
```sh
dev-platform infra discover --owner my-org --repo app --repo site > snapshot.json   # gh api GET only
dev-platform infra audit snapshot.json                     # generic findings (public runner groups, ungrouped runners, ...)
dev-platform infra drift snapshot.json --config config/infra.v1.json   # desired versus observed
```
Discovery never requests secrets, writes nothing and records what it may not read as an error, which audit and drift
report as `unknown`, never as compliant. Each difference names who may act on it (`infra` or `repository`) and a
finding names what a remediation needs; applying one is a separate, authorized change. There is deliberately no
`apply` command.
