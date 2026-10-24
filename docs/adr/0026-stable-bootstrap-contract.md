# 0026 Stable bootstrap contract

Status: Proposed (owner directive, 2026-10-24: installing a project's pinned release must not depend on an unrelated,
previously installed CLI understanding that release's evolving configuration schema).

## Context
Until 0.14.0 the CLI that ran `dev-platform setup` (or any command in a project) did two jobs. It verified the
pinned release against the project's tree digest and ran it from a private snapshot (ADR 0014, 0022): the trust
boundary. It also validated the release's record and toolchain manifest with its *own* bundled schema before running
anything (`resolve._load_release`), and `setup` read the manifest itself to decide on profiles, host support and the
Bazel configuration. A release that used a newer manifest feature (0.13.0 added `bazel` sections, `rust-components`
sources and `bound_to`; 0.14.0 added `extra_target_triples`) was therefore rejected by an older CLI as `invalid
release`, after the release had been installed and verified: the CLI's age decided what a project could use.

## Decision
1. **The bootstrap is the verifier and the launcher, nothing more.** It reads the project's pins, takes the trusted
   installer, verifier and policy from the public repository at the pinned revision (equal to the pinned digests),
   lets the pinned installer verify the archive, source revision, provenance, SBOM, build-environment attestations,
   admission and tree digest, installs into the write-once store, and runs the release from a private snapshot whose
   digest equals the pin. It does not validate the release record or any toolchain manifest, and
   `tests/test_bootstrap_boundary.py` fails if the launcher path gains such a call. Verification before execution is
   unchanged and is not replaced by a digest check followed by execution: nothing of a release runs before the
   installer's verification and the snapshot's digest comparison have passed.
2. **The release validates and prepares itself.** Everything that interprets the manifest (profile present, host
   sources, Bazel configuration, provisioning, verification) is `dev_platform.prepare`, run by the release as
   `dev-platform toolchain prepare --project P --profile X --dest D` and answering with one JSON record.
3. **Contract.** A release declares the bootstrap contract it implements in
   `src/dev_platform/bootstrap-contract.json` (`{"contract": 1}`; inside the pinned tree). The launcher reads the
   declaration from the verified snapshot. Contract 1 is the `toolchain prepare` command. Releases 0.8.0 to 0.14.0
   predate it: the launcher drives them with the same `prepare` function, over the manifest read, not validated, from
   their snapshot (a frozen adapter; their commands are unchanged). A release at 0.15.0 or later without a
   declaration, with a malformed one, or with a contract the launcher does not implement is refused before anything
   of it runs, naming the remedy.
4. **Release gate.** `tools/release.py ready` blocks unless the candidate declares a contract that
   `trust/bootstrap-compat.json` says every supported bootstrap CLI (>= `first_cli`) implements, and the built release,
   installed in a clean store and pinned by a project, is verified and run by the launcher, which asks it to
   `prepare` (`bootstrap_gate`). A toolchain-schema change alone cannot fail it. Raising the contract is an explicit
   edit of the compat file in a reviewed change, which requires a published bootstrap that implements the new contract
   and a documented migration.
5. **Transition.** CLIs up to 0.14.0 are published, immutable and still validate with their bundled schema. They are
   not changed. The supported way out is one upgrade of the CLI (`brew upgrade dev-platform`, or the trusted installer
   for the CLI release), after which no release's schema can strand a CLI. Project setup never upgrades Homebrew.

## Consequences
- Pins, the store, installed releases, toolchains and caches are untouched by the change; a corrupted store entry is
  still refused and left in place.
- The contract is the only thing a future release must keep or migrate. The frozen adapter is removed when no supported
  project pins a release older than 0.15.0.
- Limitation: a CLI of 0.14.0 or older cannot read a release record or manifest it does not know and says so; this
  cannot be fixed retroactively.
