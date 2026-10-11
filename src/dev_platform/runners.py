"""Logical runner requirements -> physical runners.

The public platform ships only the hosted profile. A private profile
(`dev-platform.infra/v1`, supplied by dev-platform-infra or any other provider)
can add self-hosted runners. Routing is fail-closed and trust is an input from
the CI event, never from project configuration.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from dev_platform.config import RunnerSpec
from dev_platform.errors import ConfigError

INFRA_SCHEMA = "dev-platform.infra/v1"

HOSTED = (
    {
        "id": "github-ubuntu",
        "kind": "hosted",
        "labels": ["ubuntu-24.04"],
        "os": "linux",
        "arch": "x86_64",
        "isolation": "ephemeral",
        "trust": "public",
        "credentials": [],
    },
    {
        "id": "github-macos",
        "kind": "hosted",
        "labels": ["macos-latest"],
        "os": "macos",
        "arch": "arm64",
        "isolation": "ephemeral",
        "trust": "public",
        "credentials": [],
    },
)


@dataclass(frozen=True)
class Route:
    ok: bool
    runner_id: str | None
    labels: tuple[str, ...]
    reason: str


_ADMISSION_KEYS = {"forbidden_triggers", "protected_environments"}
TRIGGERS = {
    "push",
    "schedule",
    "workflow_dispatch",
    "pull_request",
    "pull_request_target",
    "workflow_run",
    "release",
}


def event_trust(
    event: str,
    *,
    head_repo: str | None = None,
    base_repo: str | None = None,
    protected_ref: bool = False,
    same_repo_pr_opt_in: bool = False,
    triggering_event_trust: str | None = None,
) -> str:
    """Normative derivation of event trust from CI context (never from project config, never from a profile).
    Every pull_request_target is untrusted whatever a policy says about permitting the trigger. Unknown or
    ambiguous input is untrusted."""
    if event == "pull_request_target":
        return "untrusted"
    if event == "pull_request":
        same = bool(head_repo) and head_repo == base_repo
        return "trusted" if same and same_repo_pr_opt_in else "untrusted"
    if event == "workflow_run":
        return "trusted" if triggering_event_trust == "trusted" else "untrusted"
    if event in ("push", "schedule", "workflow_dispatch", "release"):
        return "trusted" if protected_ref else "untrusted"
    return "untrusted"


_RUNNER_KEYS = {"id", "labels", "os", "arch", "isolation", "trust", "credentials"}


def validate_profile(doc: object) -> list[str]:
    """Contract check for dev-platform.infra/v1 (mirrors schemas/infra-profile-v1.schema.json; additionally
    runner ids are unique). Anything unrecognised is an error: a provider's typo must not silently route."""
    if not isinstance(doc, dict) or set(doc) - {"schema", "runners", "admission"}:
        return ["profile must be an object with only 'schema', 'runners' and 'admission'"]
    if doc.get("schema") != INFRA_SCHEMA:
        return [f"schema must be {INFRA_SCHEMA!r}"]
    runners = doc.get("runners")
    if not isinstance(runners, list):
        return ["runners must be a list"]
    errs, seen = [], set()
    adm = doc.get("admission", {})
    if not isinstance(adm, dict) or set(adm) - _ADMISSION_KEYS:
        errs.append(f"admission: object with only {sorted(_ADMISSION_KEYS)}")
    else:
        for k, v in adm.items():
            if not (
                isinstance(v, list) and all(isinstance(x, str) and x for x in v) and len(set(v)) == len(v)
            ):
                errs.append(f"admission.{k}: unique non-empty strings")
        for t in adm.get("forbidden_triggers", []) if isinstance(adm.get("forbidden_triggers"), list) else []:
            if t not in TRIGGERS:
                errs.append(f"admission.forbidden_triggers: unknown trigger {t!r}")
    enums = {"os": ("linux", "macos"), "arch": ("x86_64", "arm64"), "isolation": ("ephemeral", "persistent"),
             "trust": ("public", "trusted")}  # fmt: skip
    for i, r in enumerate(runners):
        w = f"runners[{i}]"
        if not isinstance(r, dict):
            errs.append(f"{w}: must be an object")
            continue
        if extra := set(r) - _RUNNER_KEYS:
            errs.append(f"{w}: unknown keys {sorted(extra)}")
        if missing := {"id", "labels", "os", "arch", "isolation", "trust"} - set(r):
            errs.append(f"{w}: missing {sorted(missing)}")
        rid = r.get("id")
        if not isinstance(rid, str) or not rid:
            errs.append(f"{w}.id: non-empty string")
        elif rid in seen:
            errs.append(f"{w}.id: duplicate {rid!r}")
        else:
            seen.add(rid)
        labels = r.get("labels")
        if not (isinstance(labels, list) and labels and all(isinstance(x, str) and x for x in labels)):
            errs.append(f"{w}.labels: non-empty list of non-empty strings")
        for k, allowed in enums.items():
            if k in r and r[k] not in allowed:
                errs.append(f"{w}.{k}: one of {list(allowed)}")
        creds = r.get("credentials", [])
        if not (isinstance(creds, list) and all(isinstance(x, str) and x for x in creds)) or len(
            set(creds)
        ) != len(creds):
            errs.append(f"{w}.credentials: unique non-empty strings")
        elif creds and r.get("trust") != "trusted":
            errs.append(f"{w}: a runner offering credentials must have trust 'trusted'")
    return errs


def load_profile(path: Path | None) -> list[dict]:
    """Return offered runners: the private profile first, then public hosted."""
    offered: list[dict] = []
    if path is not None:
        try:
            doc = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigError([f"infra profile {path}: {e}"]) from None
        problems = validate_profile(doc)
        if problems:
            raise ConfigError([f"infra profile {path}: {p}" for p in problems])
        for r in doc.get("runners", []):
            offered.append({"kind": "self-hosted", "credentials": [], **r})
    return offered + [dict(h) for h in HOSTED]


def _fits(spec: RunnerSpec, r: dict) -> bool:
    return (
        spec.os in ("any", r["os"])
        and spec.arch in ("any", r["arch"])
        and (spec.isolation == "any" or r["isolation"] == spec.isolation)
        and set(spec.credentials) <= set(r.get("credentials", []))
    )


def route(spec: RunnerSpec, offered: list[dict], event_trust: str) -> Route:
    """event_trust is 'trusted' (e.g. push to protected branch) or 'untrusted' (e.g. fork PR)."""
    if event_trust not in ("trusted", "untrusted"):
        raise ConfigError([f"event_trust must be trusted|untrusted, got {event_trust!r}"])
    if spec.credentials and event_trust != "trusted":
        return Route(False, None, (), "credentials are never available to untrusted events")
    usable = [r for r in offered if event_trust == "trusted" or r["trust"] == "public"]
    for r in usable:
        if r["kind"] == "hosted" and spec.fallback == "none":
            continue
        if not _fits(spec, r):
            continue
        return Route(True, r["id"], tuple(r["labels"]), f"{r['kind']} runner satisfies requirement")
    return Route(False, None, (), "no offered runner satisfies the requirement (no silent downgrade)")
