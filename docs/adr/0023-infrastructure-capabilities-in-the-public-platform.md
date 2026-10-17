# ADR 0023: Generic infrastructure capabilities in the public platform; organization data stays private

Status: Proposed (0.10.0)

## Problem
The public platform defined the `dev-platform.infra/v1` contract, routing, admission (`pr-check`), event trust and the
consumer pin with resolver protocol (ADR 0018, 0021). Everything behind the resolver lived in a private infrastructure
repository with its own CLI and its own Homebrew distribution: immutable configuration releases, the current
authorization policy that narrows them, the provider side of resolution, a local store of selected releases, a
diagnostic, read-only discovery of runner and repository settings, and desired-versus-observed drift. Most of that is
not specific to one organization. Two CLIs and two installations for one product, and generic code only one
organization can use, are the wrong shape. The boundary must not move the other way either: no runner inventory,
endpoint, credential binding, authorization record or finding may become public.

## Decision
1. **One product, one CLI, one installation.** The generic capabilities move into the public package and the existing
   `dev-platform` CLI under `dev-platform infra ...`; the Homebrew formula is unchanged in shape (it installs the
   release tree and a launcher, nothing else). There is no second public CLI.
2. **Generic is public, organization data is private, consumer choices are the consumer's.**
   - Public: the infrastructure configuration schema `dev-platform.infra-config/v1` and its validation and projection
     onto per-repository `dev-platform.infra/v1` profiles; safe templates (GitHub-hosted Linux and macOS, a synthetic
     self-hosted example); immutable configuration releases (`infra_release`); the current authorization policy
     (`infra_authz`); the generic provider (`infra_provider`, `dev-platform infra resolve`); the local store of
     selected releases; `infra doctor`; read-only discovery, audit and drift; the conformance kit.
   - Private (any organization's own repository): its configuration *data*, its immutable releases, its current
     authorization policy, its observed state and findings, its operational procedures and handoffs.
   - Consumer: its workflows, requirements, and its exact platform and configuration pins.
3. **One policy engine.** Projection only maps declared runners onto the existing contract; routing is
   `runners.route`, admission is `prcheck`, event trust is `runners.event_trust`. Nothing in the new modules decides
   admission or trust a second way. An organization model richer than the public schema (for example trust tiers per
   ref) stays private and projects onto the same contract.
4. **Nothing is activated by installing or by a capability being available.** No command enables a workflow,
   registers a runner, binds a credential, changes a GitHub setting or installs a service. The sequence is
   initialize (writes reviewable files only when invoked, never over existing files without `--force`), validate,
   preview (profiles, a proposed workflow on stdout), and activation is a separate change through the
   organization's own procedures (a reviewed commit of a workflow, a runner registration, a settings change).
   There is deliberately no `apply`. Discovery uses `gh api` GETs only. Fetching a private release happens only on an
   explicit command naming the source and the exact selection.
5. **Identities stay separate and exact.**
   - Platform releases: SemVer, pinned by the consumer (unchanged).
   - Configuration releases: CalVer `YYYY.MM.N`, identity = version + **release-tree digest** (`sha256:` + the
     platform's `tree_digest` of `releases/<version>/`). A release must be plain data (no symlinks, special files,
     `__pycache__` or `*.pyc`), which makes the public and the previous private digest provably equal.
   - Current authorization policy: `policy_id` + `revision` + digest of its canonical JSON, mutable, outside every
     release.
   - A profile's own digest (`effective_profile_digest`, a **profile-file digest**) is a different value: it changes
     when the policy narrows a release, the release-tree digest never does.
6. **An explicit digest kind, backward compatible.** `[infra] config_digest_kind = "release-tree" | "profile-file"` is
   optional. Absent, a pin means exactly what it meant before (a vendored file's sha256, or whatever identity the
   provider resolves). `release-tree` refuses a vendored profile file (that is not the identity) and resolves only
   through a provider in a trusted context; `profile-file` additionally requires the resolved profile to be exactly
   the pinned bytes (so it cannot be narrowed, only denied). Older platform releases reject the new key (unknown keys
   are errors), so using it requires pinning a platform release that understands it: never a silent change.
7. **Authorization narrows, never grants; incomplete facts fail closed.** The policy format has exactly its keys
   (floor, revocations, enabled repositories, withdrawals); unknown keys are invalid. The effective profile is the
   release profile minus withdrawals; stale and revoked releases are denied. Without a valid policy the provider
   resolves nothing. The engine now refuses a `resolved` result without a complete `authorization_policy`
   `{id, revision, digest}` (every known provider already sends one; new conformance cases).
8. **Formats are only ever added.** `infra_release.FORMATS` lists every configuration-release format the platform
   resolves; existing releases are never rewritten to fit the public layout. Releases built by the previous private
   tooling (`dpinfra.config-release/v1`, owner in `org.json`) are resolved unchanged; new releases use
   `dev-platform.infra-config-release/v1` (owner in the manifest).
9. **The public platform needs nothing private** at install, build, release or run time. Tests use synthetic
   fixtures only and scan the published tree for secret shapes and internal host names; an organization's own CI
   runs its deny-list (its runner ids, endpoints, credential references) against the public tree.

## Consequences
- The private repository keeps only data and organization-specific rules; its generic code becomes redundant once it
  pins a platform release with these modules. Removing it is the private repository's own change (handoff in
  [infra consolidation](../infra-consolidation.md)); nothing here modifies it, and its existing releases, policy,
  pins and resolver keep working unchanged meanwhile (the public provider gives byte-identical results on them).
- `dev-platform infra` commands run the installed CLI's code (they are provider- and operator-side tools); a
  consumer's resolution is still judged by the engine of the consumer's pinned release.
- Not public: organization-specific enforcement rules that go beyond the public admission verdict (for example
  "never a privileged runner on a PR-reachable workflow, even with a protected environment") remain the
  organization's, applied on top of `pr-check --facts`.
- Limits: the public schema has no notion of per-ref trust tiers or capacity; a runner declared in configuration is
  not thereby registered, available or secure. GitHub runner groups, protected environments, job permissions,
  credentials and host isolation enforce access (ADR 0005).
