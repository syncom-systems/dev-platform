# 0021 Consumer-owned pins and infrastructure resolution

Status: Proposed (v0.8.0; implements issue #99 as proposed by the infrastructure repository's owner)

## Problem
The consumer pinned the platform release exactly (ADR 0002/0009), but the infrastructure configuration reached the engine
as an unpinned path (`--infra-profile`): a provider could silently supply a newer configuration, and nothing recorded what
was used. Untrusted CI must also run without access to private configuration.

## Decision
1. **Consumer declaration** in `dev-platform.toml`: `[infra] provider`, `config_release` (exact version), `config_digest`
   (`sha256:` + 64 hex). All three are required; there is no range and no "latest". No `[infra]` table: hosted runners only.
2. **The identity is the digest.** The provider's configuration release has a version label and a digest. The engine
   compares what a source resolves with the pin and refuses any difference (older, newer, other digest): `unavailable`.
3. **Sources.**
   - A *vendored profile file* (`--infra-profile`) committed in the consumer repository: usable only if its sha256 equals the
     pin. This is the path for untrusted CI: the profile is public data (runner labels, credential class names, never
     values) reviewed in the consumer's own pull request, so no private access is needed.
   - An *operator-supplied resolver* (`--infra-resolver` or `DEV_PLATFORM_INFRA_RESOLVER`, never read from project
     configuration): request JSON on stdin (`dev-platform.infra-resolve-request/v1`), result JSON on stdout
     (`dev-platform.infra-resolve-result/v1`: `decision` resolved|public-default|denied, `requested`, `resolved`,
     `authorization_policy {id, revision, digest}`, `effective_profile_digest`, `reasons`) and the profile at the path named
     in the request. Only for trusted events. The resolved identity must equal the pin, the request must be echoed, the
     profile digest must equal `effective_profile_digest`, and the profile must satisfy `dev-platform.infra/v1`.
4. **Event trust is the engine's.** Untrusted events never invoke a provider. A pin whose source is absent on a trusted event
   is `unavailable`, never silently hosted.
5. **Outcomes.** `resolved`, `hosted-only` (public default, untrusted event) or `unavailable` (blocks admission and
   certification, ADR 0006) or `unpinned` (a profile or resolver was supplied without a pin: not used, blocks
   certification). The result record carries `infra` with pinned, resolved, authorization policy and effective profile
   digest, never profile contents.
6. **Compatibility** between the public contract and the private profile is the contract itself: the profile must validate
   under `dev-platform.infra/v1` of the pinned platform release and the result's `contract` must name it. Providers run the
   same judgement in their own CI with `dev-platform infra check-resolution` and the cases in
   `contracts/infra/v1/resolution-cases.json` (stale, newer, mismatch, denied, unsupported, narrowed, missing).

## Consequences
- Breaking for 0.x: a profile without a pin no longer silently routes (it is `unpinned`); declare the pin.
- The private infrastructure repository is not modified from here; it adopts the documented contract on its own schedule.
- A narrowed effective profile (current authorization policy) is allowed under the same pinned release and is recorded.
