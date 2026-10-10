# Architecture

## Components

| Component | Where | Role |
|---|---|---|
| Launcher | `resolve.py`, `cli.py`, `digest.py` | Snapshots and verifies the pinned release, runs it from the verified copy |
| Release + toolchains | `release.py`, `toolchain.py`, [release schema](../schemas/release-v1.schema.json) | Immutable environment: code + toolchain profiles + SBOM; verifies the live environment against a profile |
| Records | `records.py`, `schemas/` | App-release, authorization and advisory contracts; `affected` queries |
| Config contract | `config.py`, [schema](../schemas/config-v1.schema.json) | Strict, versioned project policy (`dev-platform.toml`) |
| Detection | `detect.py` | Discovered facts only |
| Verification model | `model.py`, `impact.py`, `engine.py` | Stages, obligations, selection, evidence state machine, results |
| Adapters | `adapters.py` | Check definition -> deterministic command (`bazel`, `python`, `cargo`, `exec`) |
| Runner routing | `runners.py` | Logical requirement + event trust + infra profile -> runner |
| Result record | `engine.py`, [schema](../schemas/result-v1.schema.json) | Versioned JSON evidence (`dev-platform.result/v1`) |

Everything is a deterministic function of: configuration, change set, previous evidence, platform
digest, and (for execution) the adapters' tool output. Results contain no timestamps or host data.

## Trust boundaries

1. **Consumer repository <-> platform release.** The consumer pins version + digest; the launcher
   refuses anything else. Overrides are local-only and cannot reach protected runs or certification
   ([ADR 0003](adr/0003-version-selection-and-overrides.md)).
2. **Public platform <-> private infrastructure.** One data contract, `dev-platform.infra/v1`,
   flowing private -> public ([ADR 0001](adr/0001-public-core-private-infrastructure.md)).
3. **Untrusted code <-> trusted runners.** Enforced by GitHub permissions and runner configuration;
   the platform's routing only refuses to *ask* for a trusted runner on an untrusted event
   ([ADR 0005](adr/0005-logical-runners-and-trust-routing.md)).
4. **Agent <-> platform.** Agents call the CLI; they hold no authority the CLI does not
   ([ADR 0007](adr/0007-agent-independence.md)).

Not defended: a malicious *consumer* repository (its configured `exec` argv runs as the invoking
user, exactly as its Makefile would) and a same-user attacker modifying the running snapshot. The
verification-to-execution race is closed by running from a verified private copy
([release-trust.md](release-trust.md)).

## Release = environment

A release pins code *and* toolchain profiles ([ADR 0010](adr/0010-unified-platform-and-toolchain-releases.md)).
Every result records `environment` (release identity, profile, per-tool expected/observed/identity,
`identity_digest`). A non-conformant environment blocks admission and certification. Application
releases reference these identities ([provenance](provenance-and-governance.md)); the platform as a
dependency is tracked via SBOM, advisories and `affected` ([supply chain](supply-chain.md)).

## Installation, versioning, execution

Releases are immutable directories in a store; consumers pin `version` + `sha256`; the launcher
verifies and re-execs ([distribution](distribution.md)). Execution is
`resolve -> load config -> select (impact) -> route -> run adapters -> advance evidence -> record`.

## Configuration layers (kept separate)

| Layer | Owner | Lives in |
|---|---|---|
| Project policy: checks, obligations, impact, declared assurance, logical runner needs | consumer | `dev-platform.toml` |
| Installation: which release, where the store is | consumer pin + machine env | pin in config; `DEV_PLATFORM_STORE` env |
| Runner infrastructure | infrastructure provider | `dev-platform.infra/v1` profile (never in project config) |

## Evidence

A run emits `dev-platform.result/v1`: platform provenance, change set, per-check selection reasons,
outcome and evidence state, unsatisfied obligations, regressions, admission, certification. A later
run may consume it with `--previous` to carry evidence ([model](verification-model.md)).

## Requirement traceability

| Mission requirement | Decision | Implementation | Verification |
|---|---|---|---|
| 2.1 public/private | ADR 0001 | `runners.load_profile`, schema | `test_runners`, e2e needs no private repo |
| 2.2/2.3 immutable, pinned, overrides | ADR 0002/0003 | `resolve.py`, `digest.py` | `test_resolve`, `test_cli_e2e` |
| 2.4 language/build independence | ADR 0004 | `detect.py`, `adapters.py`, `config.py` | `test_detect`, `test_config` (bazel_only) |
| 2.5 verification semantics | ADR 0006 | `model.py`, `impact.py`, `engine.py` | `test_model`, `test_impact`, `test_engine` |
| 2.6 runners | ADR 0005 | `runners.py` | `test_runners`, `test_engine` |
| 2.7 agent independence | ADR 0007 | CLI + JSON only | e2e runs with no agent |
| 4.H self-application | - | `dev-platform.toml`, `ci.yml` | CI runs `dev-platform check --stage full` (self mode: verified, never certified) |
| Rev.2 #1 unified releases | ADR 0010 | `release.py`, `toolchain.py` | `test_release`, `test_toolchain`, e2e profile tests |
| Rev.2 #2 supply chain | ADR 0011 | SBOM, `records.releases_affected` | `test_records`, e2e `affected` |
| Rev.2 #3/#4 provenance, governance | ADR 0012/0013 | `records.py`, schemas | `test_records` |
| Rev.2 #5 release security | ADR 0014 | `digest.snapshot`, `resolve.py` | `test_resolve` (race, self not certifiable) |

## Limitations and open questions

- Producer authenticity (attestations) is designed and the release workflow is written but has never run; no release exists ([release-trust](release-trust.md)).
- Tool identity is mostly `version-only`; binary digests and Bazel lock-file reconciliation are planned (ADR 0010).
- The `python` adapter is `unittest` discovery only; pytest/ruff/pyright are `exec` checks for now.
- No cross-run evidence persistence service: `--previous` consumes a result file the caller stores.
- Open: bootstrapping rule for releasing the platform itself; whether `periodic` needs a scheduler
  contract; how Bazel graph queries plug in as an impact provider (see investigation).
