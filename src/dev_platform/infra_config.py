"""Organization infrastructure configuration `dev-platform.infra-config/v1` (ADR 0023).

The declared configuration an organization keeps in its own (usually private) repository, from which the
per-repository `dev-platform.infra/v1` profiles are projected and frozen into configuration releases
(`infra_release`). The public platform owns the schema, the validation and the projection; the organization
owns the values. Nothing here contacts GitHub, registers a runner, binds a credential or changes a setting:
a declaration is not a registration, and declaring a runner does not make it available or secure. Access is
enforced by GitHub runner groups, protected environments, job permissions, credentials and host isolation.

    {"schema": "dev-platform.infra-config/v1", "owner": "<GitHub owner>",
     "runners": [{"id", "placement": "github-hosted|self-hosted", "runner_group"?, "labels", "os", "arch",
                  "isolation", "trust", "credentials"?, "capabilities"?, "cache"?, "description"?}],
     "runner_groups"?: [{"name", "repositories", "allows_public_repositories", "restricted_to_workflows"?}],
     "caches"?: [{"id", "endpoint"?, "credential_ref"?, "modes": {"trusted": mode, "untrusted": "none"}}],
     "credential_refs"?: [{"id", "class", "provider", "scope"?, "binding": "unbound|bound"}],
     "repositories": [{"name", "visibility", "runners", "cache"?, "desired"?}],
     "admission"?: {"forbidden_triggers"?, "protected_environments"?}}

Validation fails closed: unknown keys, unknown references (runner groups, caches, credential classes,
runners) and anything secret-shaped are errors. Event trust is never configurable (the engine derives it);
`trust` declares only which events a runner may serve (`public`: also untrusted events). The projection is a
plain mapping onto the existing contract: routing, admission and event trust stay `runners` and `prcheck`.
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path

from dev_platform.infra_release import OWNER_RE, REPO_NAME_RE, canonical, make_manifest
from dev_platform.prcheck import HOSTED_LABELS
from dev_platform.runners import CACHE_MODES, INFRA_SCHEMA, TRIGGERS, validate_profile

SCHEMA = "dev-platform.infra-config/v1"
PLACEMENTS = ("github-hosted", "self-hosted")
VISIBILITIES = ("public", "private", "internal")
FORK_PR_APPROVAL = (
    "first_time_contributors_new_to_github",
    "first_time_contributors",
    "all_external_contributors",
)
_TOP = {
    "schema",
    "owner",
    "runners",
    "runner_groups",
    "caches",
    "credential_refs",
    "repositories",
    "admission",
}
_RUNNER = {
    "id",
    "placement",
    "runner_group",
    "labels",
    "os",
    "arch",
    "isolation",
    "trust",
    "credentials",
    "capabilities",
    "cache",
    "description",
}
_GROUP = {"name", "repositories", "allows_public_repositories", "restricted_to_workflows"}
_CACHE = {"id", "endpoint", "credential_ref", "modes"}
_CRED = {"id", "class", "provider", "scope", "binding"}
_REPO = {"name", "visibility", "runners", "cache", "desired"}
_DESIRED = {
    "default_token": ("read", "write"),
    "fork_pr_approval": FORK_PR_APPROVAL,
    "runner_registration": ("none", "org-group"),
}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
# Value shapes that must never appear in configuration: secrets are referenced by id, never stored.
SECRET_SHAPES = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_|-----BEGIN [A-Z ]*PRIVATE KEY|AKIA[0-9A-Z]{16}|xox[baprs]-"
    r"|://[^/\s:@]+:[^/\s@]+@)"
)
_SECRET_KEYS = {"value", "secret", "token", "password", "private_key"}

# Validated public examples of GitHub-hosted runner classes (GitHub's standard image labels). Any
# `ubuntu-*` or `macos-*` image label validates; these are the ones the templates offer.
GITHUB_HOSTED = (
    {"id": "github-ubuntu-24.04", "labels": ["ubuntu-24.04"], "os": "linux", "arch": "x86_64"},
    {"id": "github-ubuntu-24.04-arm", "labels": ["ubuntu-24.04-arm"], "os": "linux", "arch": "arm64"},
    {"id": "github-macos-15", "labels": ["macos-15"], "os": "macos", "arch": "arm64"},
)


def hosted_runner(entry: dict) -> dict:
    return {
        **entry,
        "placement": "github-hosted",
        "isolation": "ephemeral",
        "trust": "public",
        "credentials": [],
        "capabilities": [],
        "cache": "none",
    }


def looks_hosted(labels: list[str]) -> bool:
    """The label set `prcheck` treats as a GitHub-hosted image (and therefore admits for pull requests)."""
    return (
        "self-hosted" not in labels
        and len(labels) == 1
        and any(fnmatch.fnmatch(labels[0], g) for g in HOSTED_LABELS)
    )


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _keys(obj, allowed: set[str], required: set[str], where: str, errs: list[str]) -> bool:
    if not isinstance(obj, dict):
        errs.append(f"{where}: must be an object")
        return False
    if extra := set(obj) - allowed:
        errs.append(f"{where}: unknown keys {sorted(extra)}")
    if missing := required - set(obj):
        errs.append(f"{where}: missing {sorted(missing)}")
    return not missing


def _names(v, where: str, errs: list[str]) -> list[str]:
    if not (isinstance(v, list) and all(isinstance(x, str) and _ID.fullmatch(x) for x in v)) or len(
        set(v)
    ) != len(v):
        errs.append(f"{where}: unique names")
        return []
    return v


def _unique(items: list, key: str, where: str, errs: list[str]) -> dict:
    out = {}
    for i, it in enumerate(items):
        k = it.get(key) if isinstance(it, dict) else None
        if not isinstance(k, str) or not _ID.fullmatch(k):
            errs.append(f"{where}[{i}].{key}: name of letters, digits, '.', '_' or '-'")
        elif k in out:
            errs.append(f"{where}: duplicate {key} {k!r}")
        else:
            out[k] = it
    return out


def _list(cfg: dict, key: str, errs: list[str]) -> list:
    v = cfg.get(key, [])
    if not isinstance(v, list):
        errs.append(f"{key}: must be a list")
        return []
    return v


def problems(cfg: object) -> list[str]:
    """Every problem with a configuration (empty: valid)."""
    errs: list[str] = []
    if not isinstance(cfg, dict) or cfg.get("schema") != SCHEMA:
        return [f"configuration must be an object with schema {SCHEMA!r}"]
    if extra := set(cfg) - _TOP:
        errs.append(f"unknown keys {sorted(extra)}")
    if not isinstance(cfg.get("owner"), str) or not OWNER_RE.fullmatch(cfg["owner"]):
        errs.append("owner: the GitHub owner (organization or user) the configuration serves")
    for s in _strings(cfg):
        if SECRET_SHAPES.search(s):
            errs.append("a value looks like an embedded secret: store a credential_ref, never the value")
            break
    for k in ("runners", "repositories"):
        if k not in cfg:
            errs.append(f"{k}: required")
    raw = {
        k: _list(cfg, k, errs)
        for k in ("runners", "runner_groups", "caches", "credential_refs", "repositories")
    }
    runners = _unique(raw["runners"], "id", "runners", errs)
    groups = _unique(raw["runner_groups"], "name", "runner_groups", errs)
    caches = _unique(raw["caches"], "id", "caches", errs)
    creds = _unique(raw["credential_refs"], "id", "credential_refs", errs)
    repos = _unique(raw["repositories"], "name", "repositories", errs)

    classes = set()
    for cid, c in creds.items():
        w = f"credential_ref {cid!r}"
        if not _keys(c, _CRED, {"id", "class", "provider", "binding"}, w, errs):
            continue
        if _SECRET_KEYS & set(c):
            errs.append(f"{w}: holds references only, never values")
        if not (isinstance(c["class"], str) and _ID.fullmatch(c["class"])):
            errs.append(f"{w}.class: a credential class name")
        else:
            classes.add(c["class"])
        if not (isinstance(c["provider"], str) and c["provider"]):
            errs.append(f"{w}.provider: where the secret lives (for example github-environment-secret)")
        if c["binding"] not in ("unbound", "bound"):
            errs.append(f"{w}.binding: unbound or bound")
        if "scope" in c and not isinstance(c["scope"], str):
            errs.append(f"{w}.scope: string")

    for rid, r in runners.items():
        w = f"runner {rid!r}"
        if not _keys(r, _RUNNER, {"id", "placement", "labels", "os", "arch", "isolation", "trust"}, w, errs):
            continue
        place = r["placement"]
        if place not in PLACEMENTS:
            errs.append(f"{w}.placement: one of {list(PLACEMENTS)}")
            continue
        labels = r["labels"] if isinstance(r["labels"], list) else []
        creds_of = r.get("credentials", [])
        if place == "github-hosted":
            if "runner_group" in r:
                errs.append(f"{w}: a github-hosted runner has no runner_group")
            if not looks_hosted(labels) or not any(
                fnmatch.fnmatch(labels[0], g) for g in ("ubuntu-*", "macos-*")
            ):
                errs.append(
                    f"{w}: a github-hosted runner is exactly one standard image label (ubuntu-*, macos-*)"
                )
            if r["isolation"] != "ephemeral":
                errs.append(f"{w}: github-hosted runners are ephemeral")
        else:
            g = r.get("runner_group")
            if not isinstance(g, str) or g not in groups:
                errs.append(f"{w}: a self-hosted runner names a declared runner_group (unknown: {g!r})")
            if labels and looks_hosted(labels):
                errs.append(
                    f"{w}: a self-hosted runner must not carry a lone GitHub-hosted image label {labels}"
                )
            if r["trust"] == "public" and r["isolation"] != "ephemeral":
                errs.append(f"{w}: a persistent runner must never serve untrusted events (trust public)")
        for k in ("labels", "credentials", "capabilities"):
            v = r.get(k, [])
            if not (isinstance(v, list) and all(isinstance(x, str) and x for x in v)):
                errs.append(f"{w}.{k}: a list of non-empty strings")
        if isinstance(creds_of, list):
            for c in creds_of:
                if isinstance(c, str) and c not in classes:
                    errs.append(f"{w}: credential class {c!r} has no credential_ref")
        if "description" in r and not isinstance(r["description"], str):
            errs.append(f"{w}.description: string")

    for gname, g in groups.items():
        w = f"runner group {gname!r}"
        if not _keys(g, _GROUP, {"name", "repositories", "allows_public_repositories"}, w, errs):
            continue
        for name in _names(g["repositories"], f"{w}.repositories", errs):
            if name not in repos:
                errs.append(f"{w}: unknown repository {name!r}")
        for k in ("allows_public_repositories", "restricted_to_workflows"):
            if k in g and not isinstance(g[k], bool):
                errs.append(f"{w}.{k}: true or false")

    for cid, c in caches.items():
        w = f"cache {cid!r}"
        if not _keys(c, _CACHE, {"id", "modes"}, w, errs):
            continue
        modes = c["modes"]
        if (
            not isinstance(modes, dict)
            or set(modes) != {"trusted", "untrusted"}
            or not all(m in CACHE_MODES for m in modes.values())
        ):
            errs.append(f"{w}.modes: {{trusted, untrusted}}, each one of {list(CACHE_MODES)}")
        elif modes["untrusted"] != "none":
            errs.append(f"{w}: untrusted events must not reach a shared cache (modes.untrusted = none)")
        ref = c.get("credential_ref")
        if ref is not None and ref not in creds:
            errs.append(f"{w}: unknown credential_ref {ref!r}")
        if "endpoint" in c and not isinstance(c["endpoint"], str):
            errs.append(f"{w}.endpoint: string")

    for name, repo in repos.items():
        w = f"repository {name!r}"
        if not _keys(repo, _REPO, {"name", "visibility", "runners"}, w, errs):
            continue
        if not REPO_NAME_RE.fullmatch(name):
            errs.append(f"{w}: not a repository name")
        vis = repo["visibility"]
        if vis not in VISIBILITIES:
            errs.append(f"{w}.visibility: one of {list(VISIBILITIES)}")
        self_hosted = False
        for rid in _names(repo["runners"], f"{w}.runners", errs):
            r = runners.get(rid)
            if r is None:
                errs.append(f"{w}: unknown runner {rid!r}")
                continue
            if r.get("placement") != "self-hosted":
                continue
            self_hosted = True
            g = groups.get(r.get("runner_group"))
            if g is None:
                continue
            if name not in g.get("repositories", []):
                errs.append(f"{w}: runner {rid!r} is in runner group {g['name']!r}, which does not admit it")
            if vis == "public":
                if r.get("isolation") != "ephemeral":
                    errs.append(f"{w}: a public repository must not use the persistent runner {rid!r}")
                if g.get("allows_public_repositories") is not True:
                    errs.append(f"{w}: runner group {g['name']!r} does not allow public repositories")
        desired = repo.get("desired", {})
        if _keys(desired, set(_DESIRED), set(), f"{w}.desired", errs):
            for k, allowed in _DESIRED.items():
                if k in desired and desired[k] not in allowed:
                    errs.append(f"{w}.desired.{k}: one of {list(allowed)}")
            if (
                vis == "public"
                and self_hosted
                and desired.get("fork_pr_approval") != "all_external_contributors"
            ):
                errs.append(
                    f"{w}: public with self-hosted runners must desire "
                    "fork_pr_approval=all_external_contributors"
                )
        cache = repo.get("cache")
        if cache is not None:
            if cache not in caches:
                errs.append(f"{w}: unknown cache {cache!r}")
            elif vis == "public":
                errs.append(f"{w}: a public repository must not use a shared cache")

    adm = cfg.get("admission", {})
    if _keys(adm, {"forbidden_triggers", "protected_environments"}, set(), "admission", errs):
        triggers = adm.get("forbidden_triggers", [])
        if not isinstance(triggers, list):
            errs.append("admission.forbidden_triggers: list of triggers")
        else:
            errs += [
                f"admission.forbidden_triggers: unknown trigger {t!r}" for t in triggers if t not in TRIGGERS
            ]
    if errs:
        return errs
    # Every runner, assigned or not, and every projected profile must satisfy the contract (the single source
    # of truth for its rules).
    every = {"schema": INFRA_SCHEMA, "runners": [_profile_runner(r) for r in cfg["runners"]]}
    errs += [f"runners: {p}" for p in validate_profile(every)]
    for name in repos:
        errs += [f"profile for {name!r}: {p}" for p in validate_profile(profile_for(cfg, name))]
    return errs


def notes(cfg: dict) -> list[str]:
    """What validation cannot establish: declarations that need evidence from the infrastructure itself."""
    out = []
    for r in cfg.get("runners", []):
        if r.get("placement") == "self-hosted":
            out.append(
                f"runner {r['id']!r}: declared, not verified: registration, runner-group membership and "
                "isolation "
                "are established only by the infrastructure (dev-platform infra discover, then drift)"
            )
    for c in cfg.get("credential_refs", []):
        if c.get("binding") == "unbound":
            out.append(f"credential_ref {c['id']!r}: unbound: no job can receive it until it is bound")
    return out


def _profile_runner(r: dict) -> dict:
    out = {k: r[k] for k in ("id", "labels", "os", "arch", "isolation", "trust")}
    out["credentials"] = list(r.get("credentials", []))
    out["capabilities"] = sorted(r.get("capabilities", []))
    if "cache" in r:
        out["cache"] = r["cache"]
    return out


def profile_for(cfg: dict, repository: str) -> dict:
    """The `dev-platform.infra/v1` profile of one repository: its assigned runners in declaration order."""
    repo = next(r for r in cfg["repositories"] if r["name"] == repository)
    assigned = set(repo["runners"])
    doc = {
        "schema": INFRA_SCHEMA,
        "runners": [_profile_runner(r) for r in cfg["runners"] if r["id"] in assigned],
    }
    adm = cfg.get("admission")
    if adm:
        doc["admission"] = {
            k: list(adm[k]) for k in ("forbidden_triggers", "protected_environments") if k in adm
        }
    return doc


def release_files(cfg: dict, version: str) -> dict[str, bytes]:
    """The content of a configuration release: the manifest, the declared configuration and every profile."""
    names = [r["name"] for r in cfg["repositories"]]
    files = {f"profiles/{n}.json": canonical(profile_for(cfg, n)) for n in names}
    files["infra-config.json"] = canonical(cfg)
    files["manifest.json"] = canonical(make_manifest(version, cfg["owner"], names))
    return files


def template(kind: str, owner: str, repositories: list[str]) -> dict:
    """A starting configuration. `github-hosted`: hosted runners only (no infrastructure of your own).
    `self-hosted`: additionally one declared self-hosted runner class in a runner group, to be edited."""
    repos = repositories or ["my-repository"]
    hosted = [hosted_runner(dict(h)) for h in GITHUB_HOSTED]
    cfg = {
        "schema": SCHEMA,
        "owner": owner,
        "runners": hosted,
        "repositories": [
            {
                "name": n,
                "visibility": "private",
                "runners": [h["id"] for h in hosted],
                "desired": {"default_token": "read"},
            }
            for n in repos
        ],
        "admission": {"forbidden_triggers": ["pull_request_target"], "protected_environments": []},
    }
    if kind == "self-hosted":
        cfg["runners"].append(
            {
                "id": "linux-build",
                "description": "edit: your own runner class; declaring it does not register or secure it",
                "placement": "self-hosted",
                "runner_group": "trusted-builds",
                "labels": ["self-hosted", "linux", "x64", "build"],
                "os": "linux",
                "arch": "x86_64",
                "isolation": "ephemeral",
                "trust": "trusted",
                "credentials": [],
                "capabilities": [],
                "cache": "none",
            }
        )
        cfg["runner_groups"] = [
            {
                "name": "trusted-builds",
                "repositories": list(repos),
                "allows_public_repositories": False,
                "restricted_to_workflows": True,
            }
        ]
        for r in cfg["repositories"]:
            r["runners"].append("linux-build")
            r["desired"]["runner_registration"] = "org-group"
        cfg["admission"]["protected_environments"] = ["release"]
    elif kind != "github-hosted":
        raise ValueError(f"unknown template {kind!r}")
    return cfg


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text())


__all__ = ["GITHUB_HOSTED", "SCHEMA", "notes", "problems", "profile_for", "release_files", "template"]
