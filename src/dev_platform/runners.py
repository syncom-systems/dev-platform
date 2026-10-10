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


def load_profile(path: Path | None) -> list[dict]:
    """Return offered runners: the private profile first, then public hosted."""
    offered: list[dict] = []
    if path is not None:
        try:
            doc = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigError([f"infra profile {path}: {e}"]) from None
        if doc.get("schema") != INFRA_SCHEMA:
            raise ConfigError([f"infra profile: schema must be {INFRA_SCHEMA!r}"])
        for r in doc.get("runners", []):
            missing = {"id", "labels", "os", "arch", "isolation", "trust"} - set(r)
            if missing or r["trust"] not in ("public", "trusted"):
                raise ConfigError([f"infra profile runner {r.get('id')!r}: invalid ({sorted(missing)})"])
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
