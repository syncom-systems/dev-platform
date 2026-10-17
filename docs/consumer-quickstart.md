# Consumer quickstart (what the pilot actually does)

On a development machine, `brew install syncom-systems/dev-platform/dev-platform` and `dev-platform setup` do steps 2
and 3 from the project's committed pins ([homebrew.md](homebrew.md)). For the consumer-owned pins, the non-disruptive CI run and the verifiable evidence bundle see
[consumer-integration.md](consumer-integration.md).

These steps are exactly what `tools/pilot.py` runs against a real public consumer
([pilot results](../pilot/consumers.json), workflow `pilot`). Nothing is installed outside the store you name.

1. **Choose a release and pin it out of band.** From the release's published identity record take the archive
   sha256, tree digest, and the pins of `tools/verify_release.py`, `trust/policy.json` and
   `tools/install_release.py` (`releases/<version>/identity.json`). Re-derive them yourself.
2. **Install with the trusted installer** (verifies provenance, SBOM and build-environment attestations first):
   ```
   python3 install_release.py --version 0.2.0 --store ./store --verifier-sha256 <pin> --policy policy.json \
     --policy-sha256 <pin> --archive-sha256 <pin> --tree-sha256 <consumer pin> [--allow-unaccepted]
   ```
   An unaccepted release is refused unless you pass `--allow-unaccepted`; accepted-ness is never inferred.
3. **Realize the toolchain profile** the release ships for your project (for Rust/Cargo: `rust-cargo-1.99` for
   current dependency sets, `rust-cargo` for rustc 1.85) with `tools/setup_env.py <profile>`, then put its
   directories on `PATH`. Tool identity is verified, not trusted.
4. **Write the pin**: `dev-platform init --platform-version <v> --sha256 <tree digest> --profile <profile>`.
   `init` derives starter checks from build-system markers and a real `tests/` layout, never from stray files.
5. **Check**: `dev-platform doctor`, then `dev-platform check --stage full --result result.json`. Admission,
   certification and blockers are in the result. Certification means the checks passed under verified tool
   identity on a stated platform; it is not hermetic and not owner acceptance.
6. **Bazel consumers: prove the Rust toolchain** (`rust-bazel*` profiles; Bazel only, Cargo is never run):
   `dev-platform toolchain prove-bazel-rust --project . --out proof.json` rebuilds with a fresh action-environment nonce while
   decoy `rustc`/`cargo`/`rustup` sit first on `PATH`, then shows from Bazel's own action graph that every Rustc action names
   a rustc provided through an external repository (never a host path), resolving outside host Rust locations, reporting
   exactly the version `MODULE.bazel` declares. It fails if a decoy was executed. Limit: repository rules run at fetch time
   with Bazel's environment; the action-path proof covers where the toolchain came from.
7. **Upgrading** is an explicit edit of the pin in a reviewed change. A toolchain change is a new release.

Host tools your checks need that are not in the toolchain profile (a terminal multiplexer, `qemu`, ...) are
declared in `dev-platform.toml`:
```toml
[[host]]
name = "tmux"
argv = ["tmux", "-V"]
pattern = "tmux (\\S+)"      # capture group 1 is the version
version = "3"                 # optional: exact, or a dotted prefix
```
They are observed (never content-verified), recorded in the environment evidence with a limitation, change the
identity digest, and gate conformance: a missing or mismatching declared tool is reported as such instead of an
obscure test failure. They never raise assurance and never imply hermeticity.

Known friction (from the flight pilot): the consumer's dependency set may need a newer toolchain profile than
an older release ships (a new release is required).
