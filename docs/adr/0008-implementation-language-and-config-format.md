# ADR 0008: Implementation language and configuration format

Status: Proposed

- **Python 3.11+, standard library only.** The launcher must run on a bare machine, the logic is
  glue and data transformation, and zero dependencies keep the supply chain and the pinned tree
  trivial. Revisit if startup cost (re-exec) or a need for a static binary appears.
- **TOML** for consumer configuration (`tomllib` is in the standard library; comments allowed).
  Machine outputs (results, infra profile, facts) are JSON with a `schema` field.
- Validation is hand-written and strict (unknown keys are errors); the JSON Schemas under
  `schemas/` are published mirrors for editors and other tooling, with tests guarding drift.
