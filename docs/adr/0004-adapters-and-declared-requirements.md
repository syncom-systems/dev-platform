# ADR 0004: Adapters; discovered facts versus declared requirements

Status: Ratified

## Decision
- `detect` reports **facts** (languages by file extension, build-system marker files). Facts never
  create obligations or an assurance level. Obligations and `assurance` come only from
  `dev-platform.toml`. `doctor` warns when a detected language is not declared.
- An **adapter** is a pure function from a check definition to a command. Built-ins: `bazel`,
  `python` (unittest), `cargo`, `exec`. There is no plugin runtime; one is justified only when an
  adapter must live outside this repository.
- `project.bazel_only = true` makes the `cargo` adapter and direct `cargo` invocation a
  *configuration error*, and `init` never proposes Cargo for a Bazel workspace.
- Adapter outcomes are normalized to `passed | failed | unavailable`. A missing tool is
  `unavailable` (obligation unsatisfied), never a pass.
