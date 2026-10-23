# dev-platform

A reusable, deterministic development control plane: explicit policy, reproducible execution,
interchangeable language and infrastructure adapters. Not a bag of CI scripts.

**Status: pre-production.** From 0.12.0 a release that passes every check is published as `verified` and installs
without extra flags; releases up to 0.11.0 are verified-unaccepted candidates and need `--allow-unaccepted`
([ADR 0024](docs/adr/0024-single-owner-release-authority.md)). Many contracts are still proposed. Do not treat the
platform as production-ready.

## Install (macOS, Linux)

```sh
brew install syncom-systems/dev-platform/dev-platform
gh auth login                                             # once: release attestations are verified with gh
cd my-project && dev-platform setup    # the project's pinned release, verified; its toolchains; doctor
```

The CLI is a launcher; each project's committed pins select its release. No private infrastructure is needed. Runbook
(install, upgrade, rollback, diagnosis, CI, optional private infrastructure): [installation](docs/installation.md).

## Try it

Python 3.11+, no dependencies.

```sh
export PYTHONPATH=src                      # development checkout; consumers use pinned releases
python3 -m dev_platform detect --project fixtures/mixed-bazel
python3 -m dev_platform check --stage full # the platform verifies itself
python3 -m dev_platform explain --changed src/dev_platform/model.py
python3 -m unittest discover -s tests
```

Commands: `init`, `setup`, `detect`, `doctor`, `explain`, `check`, `workflow`, `digest`, `release build|verify`, `validate`,
`affected`, and the optional `infra ...` ([infrastructure](docs/infrastructure.md): nothing is activated by installing).
Exit codes: 0 ok, 1 unsatisfied, 2 config/usage, 3 platform resolution/integrity.

## Documents

[Architecture](docs/architecture.md) · [Verification model](docs/verification-model.md) ·
[Installation](docs/installation.md) · [Bazel Rust/Python baseline](docs/rust-python-baseline.md) · [Distribution](docs/distribution.md) · [Homebrew and setup](docs/homebrew.md) · [ADRs](docs/adr/README.md) ·
[Supply chain](docs/supply-chain.md) · [Provenance & governance](docs/provenance-and-governance.md) ·
[Release trust](docs/release-trust.md) · [Infrastructure](docs/infrastructure.md) · [Consumer compatibility](docs/consumer-compatibility.md) · [Investigation](docs/investigation.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)
