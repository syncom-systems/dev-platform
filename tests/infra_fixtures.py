"""Synthetic infrastructure configuration for tests: an invented organization, never real inventory."""

import json
from pathlib import Path

from dev_platform import infra_release
from dev_platform.infra_release import canonical

OWNER = "example-org"
VERSION = "2026.01.1"
TRUSTED = {
    "id": "linux-trusted",
    "labels": ["self-hosted", "linux", "example-trusted"],
    "os": "linux",
    "arch": "x86_64",
    "isolation": "ephemeral",
    "trust": "trusted",
    "credentials": ["deploy", "signing"],
    "capabilities": ["docker"],
    "cache": "read-write",
}
PUBLIC = {
    "id": "linux-public",
    "labels": ["ubuntu-24.04"],
    "os": "linux",
    "arch": "x86_64",
    "isolation": "ephemeral",
    "trust": "public",
    "credentials": [],
    "capabilities": [],
    "cache": "none",
}
ADMISSION = {"forbidden_triggers": ["pull_request_target"], "protected_environments": ["release"]}


def profile(*runners, admission=ADMISSION) -> dict:
    doc = {"schema": "dev-platform.infra/v1", "runners": [dict(r) for r in runners]}
    if admission:
        doc["admission"] = dict(admission)
    return doc


def release_files(version=VERSION, owner=OWNER, repos=None, fmt=None) -> dict[str, bytes]:
    repos = repos or {"app": profile(TRUSTED, PUBLIC), "tool": profile(PUBLIC)}
    files = {f"profiles/{n}.json": canonical(p) for n, p in repos.items()}
    manifest = infra_release.make_manifest(version, owner, list(repos))
    if fmt is not None:  # a legacy-layout release: the owner lives in org.json
        manifest = {k: v for k, v in manifest.items() if k != "owner"} | {"schema": fmt}
        files["org.json"] = canonical({"org": owner, "schema_version": 1})
    files["manifest.json"] = canonical(manifest)
    return files


def policy(**over) -> dict:
    doc = {
        "schema_version": 1,
        "policy_id": "example-authorization",
        "revision": 1,
        "minimum_release": VERSION,
        "revoked_releases": [],
        "repositories_enabled": ["app", "tool"],
        "withdrawn": {"runner_classes": [], "credentials": []},
        "repository_withdrawn": {},
    }
    doc.update(over)
    return doc


def write_policy(root: Path, **over) -> dict:
    doc = policy(**over)
    p = Path(root) / "authorization" / "current.v1.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2) + "\n")
    return doc


def config_repo(root: Path, versions=(VERSION,), **policy_over) -> dict[str, str]:
    """A configuration repository with the given releases and a current policy. Returns version -> wire digest."""
    out = {}
    for v in versions:
        out[v] = infra_release.wire(infra_release.build(root, v, release_files(v)))
    write_policy(root, **policy_over)
    return out


def request(
    version=VERSION, digest=None, repo=f"{OWNER}/app", trust="trusted", profile_out="/dev/null", **over
):
    doc = {
        "schema_version": "dev-platform.infra-resolve-request/v1",
        "repo": repo,
        "event_trust": trust,
        "contract": "dev-platform.infra/v1",
        "requested": {"version": version, "digest": digest},
        "profile_out": profile_out,
    }
    doc.update(over)
    return doc
