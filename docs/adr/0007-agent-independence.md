# ADR 0007: Agent independence

Status: Ratified

- The CLI, schemas and results are the contract. Nothing requires Claude Code, Codex or any agent.
- Agent integrations (hooks, skills, Claude Code plugins) are thin adapters that call
  `dev-platform explain|check --json` and render the result. Planned under `integrations/`; none
  exist yet.
- Instructions in an agent file are never an enforcement mechanism. Enforcement lives in
  `dev-platform check`, git hooks and required CI status checks.
