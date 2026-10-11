# 0018 One admission policy contract; the PR checker evaluates, it does not decide

Status: Proposed. Reconciles issues #20 (infra/v1 refinements) and #48 (generic PR checker). Additive within
`dev-platform.infra/v1`; no new contract.

## Problem
Two proposals each carried part of a policy: #20 made `pull_request_target` always untrusted, #48 proposed a
second contract (`dev-platform.pr-policy/v1`) that could forbid the trigger and list allowed runners. Two
contracts would let the generic checker and the provider disagree, and would let the public checker invent
organization-specific trust decisions.

## Decision
`dev-platform.infra/v1` remains the single coupling. Responsibilities are split by who owns the fact:

| Fact | Owner | Where |
|---|---|---|
| Event trust derivation (every `pull_request_target` untrusted; fork PR untrusted; unknown untrusted) | platform, normative, not configurable | `runners.event_trust`, conformance cases |
| Which runners exist, their trust class, labels, credentials | organization | `runners` (existing) |
| Which runner labels a PR-reachable workflow may select | derived: public-trust runner labels plus GitHub-hosted labels (`ubuntu-*`, `macos-*`, `windows-*`) | no extra data |
| Which triggers the organization forbids, which environments protect non-public runners | organization | optional `admission` section |
| Detecting breaches, incompleteness and heuristic indicators | platform (generic, static) | `dev-platform pr-check` |

Rules:
- A profile can never change event trust: `admission` accepts only `forbidden_triggers` and
  `protected_environments`; any other key is a contract error.
- `pull_request_target` is therefore *untrusted by derivation* (routing refuses credentials and non-public
  runners for it) independent of policy. Whether a repository may *use* the trigger is organization policy:
  listed in `forbidden_triggers` it is a violation; unlisted it is only a risk indicator.
- The public default (no profile) is hosted runners only; it forbids no trigger and invents no environment
  names. A non-public runner reached from a PR-reachable workflow is a violation under the default too, since no
  runner outside the hosted classes is public.
- Outputs stay separate (#48): `policy_violations` -> `failed`; `incomplete` -> `unavailable` (blocks, ADR
  0006); `risk_indicators` never change admission. No findings is not a proof of safety. The YAML reader is a
  deliberate subset: anything it cannot interpret (anchors, merge keys, expression `runs-on`, external
  reusable workflows, non-literal matrices) is `incomplete`, never silently passed. A matrix `include` is
  checked as a superset.
- The checker reads text only and never executes or checks out PR content. GitHub settings (runner groups,
  environments, fork-approval) remain the enforcement; the checker informs (ADR 0005).
- #48's separate `pr-policy/v1` is not created. Organization-specific content stays in the private provider's
  profile; the conformance kit (`contracts/infra/v1`) pins event trust and admission cases.
