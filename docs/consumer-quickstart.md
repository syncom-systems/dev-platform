# Consumer quickstart (what the pilot actually does)

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
6. **Upgrading** is an explicit edit of the pin in a reviewed change. A toolchain change is a new release.

Known friction (from the flight pilot): the consumer's dependency set may need a newer toolchain profile than
an older release ships (a new release is required); host tools a test needs (e.g. a terminal multiplexer) are
not yet declared in evidence (issue #60).
