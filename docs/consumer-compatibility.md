# Consumer compatibility (adoption contract evidence)

`tests/test_compat.py` runs synthetic consumers against real releases that are built, packed and
installed with the operator code paths (`release build|pack|install`). No production consumer is
involved. Host tools are emulated only where a real one would make the suite non-hermetic (fake
`bazel`/`cargo` on `PATH`, a python-emulated `rustc` probe); the platform code under test is real.

| Consumer | Profile | Demonstrated |
|---|---|---|
| Python | `python` (closure digest of the interpreter file) | pinned run, `closure-verified`, certified at `full` on a clean git tree; `python-weak` admits but cannot certify |
| Rust, Bazel-only | `rust-bazel` | `bazel_only` init never proposes Cargo; Bazel adapter runs; tools `bazel-locked` (pinned toolchain archive sha256 in `MODULE.bazel` and in the resolved lock; Bazelisk-verified binary digest) |
| Mixed Python+Rust, Bazel | `mixed-bazel` | three Bazel-managed toolchains reconciled, no host tool consulted |
| Rust, Cargo | `rust-cargo` | cargo adapter; the same project with `bazel_only = true` is rejected (exit 2) |

Scenarios: side-by-side releases; upgrade and **rollback of the platform pin** (explicit edit; old
release byte-identical); tampering with an installed release (exit 3, other pins unaffected);
version mismatch (not installed, digest of another release, unknown profile); installer refusing a
wrong-digest or corrupt archive and leaving the store untouched; declaration drift (Bazel version,
toolchain digest, digest missing from the resolved graph, removed Bazelisk pin) all blocking
admission with `assurance = diagnostic`; a toolchain upgrade being a new release the consumer adopts
in two explicit steps (pin, then its own declaration).

Not covered: real Bazel/Cargo execution, Bazel repository-rule resolution beyond declared inputs,
Windows, and application-release rollback (milestone M4).
