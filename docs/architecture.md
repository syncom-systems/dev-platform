# Architecture

## Components

| Component | Where | Role |
|---|---|---|
| Launcher | `resolve.py`, `cli.py` | Reads the consumer pin, verifies the release, re-executes into it |
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
user, exactly as its Makefile would), and a compromised store directory prior to digest check
(TOCTOU between verification and re-exec; mitigated by store permissions, see Limitations).

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
| 4.H self-application | - | `dev-platform.toml`, `ci.yml` | CI runs `dev-platform check --stage full` |

## Limitations and open questions

- Integrity is a digest the consumer trusts; producer authenticity is future work (ADR 0009).
- Verification-to-re-exec is not atomic; the store must not be writable by untrusted users.
- The `python` adapter is `unittest` discovery only; pytest/ruff/pyright are `exec` checks for now.
- No cross-run evidence persistence service: `--previous` consumes a result file the caller stores.
- Open: bootstrapping rule for releasing the platform itself; whether `periodic` needs a scheduler
  contract; how Bazel graph queries plug in as an impact provider (see investigation).
