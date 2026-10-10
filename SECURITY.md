# Security policy

Report vulnerabilities privately via GitHub security advisories on this repository. Do not open
public issues for suspected vulnerabilities.

Scope notes: the launcher verifies a pinned digest before executing a release; override variables are
refused in protected contexts; the platform executes commands configured by the consumer repository
with the invoking user's privileges. See [architecture](docs/architecture.md#trust-boundaries).
