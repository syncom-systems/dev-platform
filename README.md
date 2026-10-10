# dev-platform

A reusable, deterministic development control plane: explicit policy, reproducible execution,
interchangeable language and infrastructure adapters. Not a bag of CI scripts.

**Status: pre-release (0.1.0 foundation).** Contracts are proposed and have one end-to-end
demonstration; do not treat the platform as production-ready.

## Try it

Python 3.11+, no dependencies.

```sh
export PYTHONPATH=src                      # development checkout; consumers use pinned releases
python3 -m dev_platform detect --project fixtures/mixed-bazel
python3 -m dev_platform check --stage full # the platform verifies itself
python3 -m dev_platform explain --changed src/dev_platform/model.py
python3 -m unittest discover -s tests
```

Commands: `init`, `detect`, `doctor`, `explain`, `check`, `digest`, `release build|verify`, `validate`, `affected`.
Exit codes: 0 ok, 1 unsatisfied, 2 config/usage, 3 platform resolution/integrity.

## Documents

[Architecture](docs/architecture.md) · [Verification model](docs/verification-model.md) ·
[Distribution](docs/distribution.md) · [ADRs](docs/adr/README.md) ·
[Supply chain](docs/supply-chain.md) · [Provenance & governance](docs/provenance-and-governance.md) ·
[Release trust](docs/release-trust.md) · [Consumer compatibility](docs/consumer-compatibility.md) · [Investigation](docs/investigation.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)
