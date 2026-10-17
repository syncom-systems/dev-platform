"""Observed infrastructure: read-only discovery, audit findings and desired-versus-observed drift (ADR 0023).

`discover` reads GitHub with the caller's identity through `gh api --method GET` only (`_get` refuses anything
else), never requests a secret or a secret name, and writes nothing: the snapshot goes to stdout. A value the
caller may not read is recorded as an error and later reported as `unknown`, never as compliant.

`audit` and `drift` are offline functions of a snapshot (and, for drift, a `dev-platform.infra-config/v1`).
They report; they never repair. Every finding and difference says who may act on it (`scope`: `infra` for what
the organization's infrastructure owner manages, `repository` for a repository's own settings) and what a
remediation would need, so that applying one is a separate, authorized change.
"""

from __future__ import annotations

import json
import re
import subprocess

SNAPSHOT = "dev-platform.infra-snapshot/v1"
SEVERITIES = ("critical", "high", "medium", "info")
_PATH = re.compile(r"^/(orgs|repos)/[A-Za-z0-9._/-]+(\?[A-Za-z0-9=&_.-]+)?$")
_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _get(path: str, runner=subprocess.run):
    """One read-only GitHub API call: GET only, a fixed path shape, no request body."""
    if not _PATH.fullmatch(path) or ".." in path:
        raise ValueError(f"refusing API path {path!r}")
    p = runner(["gh", "api", "--method", "GET", path], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        return {"_error": ((p.stderr or p.stdout or "").strip().splitlines() or ["gh failed"])[0][:200]}
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {"_error": "not JSON"}


def _runner(r: dict) -> dict:
    return {
        "name": r.get("name"),
        "os": r.get("os"),
        "status": r.get("status"),
        "labels": sorted(x.get("name") for x in r.get("labels", [])),
    }


def _err(doc) -> str | None:
    return doc.get("_error") if isinstance(doc, dict) else None


def discover(owner: str, repos: list[str], runner=subprocess.run) -> dict:
    if not _OWNER.fullmatch(owner) or not all(_NAME.fullmatch(r) for r in repos):
        raise ValueError("owner and repository names only")
    get = lambda path: _get(path, runner)  # noqa: E731
    snap: dict = {"schema": SNAPSHOT, "owner": owner, "runner_groups": [], "repos": {}, "errors": []}
    groups = get(f"/orgs/{owner}/actions/runner-groups")
    if _err(groups):
        snap["runner_groups"] = None
        snap["errors"].append(f"runner groups: {_err(groups)}")
    else:
        for g in groups.get("runner_groups", []):
            gid = g["id"]
            members = get(f"/orgs/{owner}/actions/runner-groups/{gid}/runners")
            entry = {
                "name": g.get("name"),
                "visibility": g.get("visibility"),
                "allows_public_repositories": g.get("allows_public_repositories"),
                "restricted_to_workflows": g.get("restricted_to_workflows"),
                "runners": None if _err(members) else [_runner(r) for r in members.get("runners", [])],
            }
            if g.get("visibility") == "selected":
                rs = get(f"/orgs/{owner}/actions/runner-groups/{gid}/repositories")
                entry["repositories"] = (
                    None if _err(rs) else sorted(r["name"] for r in rs.get("repositories", []))
                )
            snap["runner_groups"].append(entry)
    for repo in repos:
        base = f"/repos/{owner}/{repo}"
        meta = get(base)
        runners = get(f"{base}/actions/runners")
        perms = get(f"{base}/actions/permissions/workflow")
        rulesets = get(f"{base}/rulesets")
        fork = get(f"{base}/actions/permissions/fork-pr-contributor-approval")
        snap["repos"][repo] = {
            "private": None if _err(meta) else meta.get("private"),
            "repo_level_runners": None if _err(runners) else [_runner(r) for r in runners.get("runners", [])],
            "default_workflow_permissions": None
            if _err(perms)
            else perms.get("default_workflow_permissions"),
            "rulesets": None
            if _err(rulesets) or not isinstance(rulesets, list)
            else [{"name": r.get("name"), "enforcement": r.get("enforcement")} for r in rulesets],
            "fork_pr_approval": None if _err(fork) else fork.get("approval_policy"),
        }
        for what, doc in (
            ("repository", meta),
            ("runners", runners),
            ("workflow permissions", perms),
            ("rulesets", rulesets),
            ("fork-pr approval", fork),
        ):
            if _err(doc):
                snap["errors"].append(f"{repo}: {what}: {_err(doc)}")
    return snap


def _finding(fid, sev, msg, action, reversible, requires, scope, repo=None, runner=None) -> dict:
    return {
        "id": fid,
        "severity": sev,
        "repo": repo,
        "runner": runner,
        "message": msg,
        "scope": scope,
        "remediation": {"action": action, "reversible": reversible, "requires": requires},
    }


def audit(snap: dict) -> list[dict]:
    """Generic findings over a snapshot (no configuration needed)."""
    out: list[dict] = []
    groups = snap.get("runner_groups") or []
    grouped = {r["name"] for g in groups for r in (g.get("runners") or [])}
    for g in groups:
        if not g.get("runners"):
            continue
        if g.get("allows_public_repositories"):
            out.append(
                _finding(
                    "GRP-PUBLIC",
                    "critical",
                    f"runner group {g['name']!r} has runners and allows public repositories",
                    "disable allows_public_repositories on the group",
                    True,
                    "organization admin",
                    "infra",
                )
            )
        if g.get("visibility") == "all":
            out.append(
                _finding(
                    "GRP-ALL",
                    "high",
                    f"runner group {g['name']!r} has runners and is visible to all repositories",
                    "restrict the group to selected repositories",
                    True,
                    "organization admin",
                    "infra",
                )
            )
        if not g.get("restricted_to_workflows"):
            out.append(
                _finding(
                    "GRP-NO-WORKFLOW-RESTRICTION",
                    "info",
                    f"runner group {g['name']!r} does not restrict which workflows may use it",
                    "set selected workflows on the group",
                    True,
                    "organization admin",
                    "infra",
                )
            )
    for repo, r in sorted((snap.get("repos") or {}).items()):
        public = r.get("private") is False
        for rn in r.get("repo_level_runners") or []:
            if rn["name"] not in grouped:
                out.append(
                    _finding(
                        "RUN-UNGROUPED",
                        "medium",
                        "runner registered at repository level: runner-group restrictions do not apply",
                        "re-register it in a restricted organization runner group",
                        False,
                        "runner host access",
                        "infra",
                        repo,
                        rn["name"],
                    )
                )
            if public and "ephemeral" not in rn.get("labels", []):
                out.append(
                    _finding(
                        "PUBLIC-PERSISTENT",
                        "critical",
                        "a public repository can send jobs to a "
                        "repository-level runner that is not known to be ephemeral",
                        "replace it with an ephemeral isolated runner, or deregister it",
                        False,
                        "runner host access",
                        "infra",
                        repo,
                        rn["name"],
                    )
                )
                if r.get("fork_pr_approval") != "all_external_contributors":
                    out.append(
                        _finding(
                            "PUBLIC-FORK-APPROVAL",
                            "high",
                            f"fork pull request approval is "
                            f"{r.get('fork_pr_approval')!r} with a self-hosted runner attached",
                            "require approval for all external contributors",
                            True,
                            "repository admin",
                            "repository",
                            repo,
                            rn["name"],
                        )
                    )
            if not public and r.get("rulesets") == []:
                out.append(
                    _finding(
                        "PRIVATE-UNPROTECTED",
                        "medium",
                        "a self-hosted runner serves a repository without a ruleset",
                        "add a ruleset for the default branch",
                        True,
                        "repository admin",
                        "repository",
                        repo,
                        rn["name"],
                    )
                )
    order = {s: i for i, s in enumerate(SEVERITIES)}
    return sorted(out, key=lambda f: (order[f["severity"]], f["id"], f["repo"] or "", f["runner"] or ""))


def drift(cfg: dict, snap: dict) -> list[dict]:
    """Desired (configuration) vs observed (snapshot). Missing observations are `unknown`, never `ok`."""
    out: list[dict] = []

    def add(scope, field, want, got, repo=None, group=None):
        out.append(
            {
                "repo": repo,
                "runner_group": group,
                "field": field,
                "desired": want,
                "observed": got,
                "scope": scope,
                "status": "unknown" if got is None else "drift",
            }
        )

    groups = snap.get("runner_groups")
    observed_groups = {g["name"]: g for g in groups or []}
    for g in cfg.get("runner_groups", []):
        if groups is None:
            add("infra", "runner_group", "present", None, group=g["name"])
            continue
        o = observed_groups.get(g["name"])
        if o is None:
            add("infra", "runner_group", "present", "absent", group=g["name"])
            continue
        if o.get("allows_public_repositories") is not g["allows_public_repositories"]:
            add(
                "infra",
                "allows_public_repositories",
                g["allows_public_repositories"],
                o.get("allows_public_repositories"),
                group=g["name"],
            )
        if (
            "restricted_to_workflows" in g
            and o.get("restricted_to_workflows") is not g["restricted_to_workflows"]
        ):
            add(
                "infra",
                "restricted_to_workflows",
                g["restricted_to_workflows"],
                o.get("restricted_to_workflows"),
                group=g["name"],
            )
        want = sorted(g["repositories"])
        got = (
            o.get("repositories")
            if o.get("visibility") == "selected"
            else ("all" if o.get("visibility") else None)
        )
        if got != want:
            add("infra", "repositories", want, got, group=g["name"])
        members = o.get("runners")
        for r in (r for r in cfg["runners"] if r.get("runner_group") == g["name"]):
            if members is None:
                add("infra", f"runner {r['id']}", "registered with its labels", None, group=g["name"])
            elif not any(set(r["labels"]) - {"self-hosted"} <= set(m["labels"]) for m in members):
                add(
                    "infra",
                    f"runner {r['id']}",
                    "registered with its labels",
                    "no runner in the group has them",
                    group=g["name"],
                )
    for r in cfg.get("repositories", []):
        obs = (snap.get("repos") or {}).get(r["name"])
        if obs is None:
            add("infra", "snapshot", "present", None, repo=r["name"])
            continue
        private = obs.get("private")
        want_private = r["visibility"] != "public"
        if private is not want_private:
            add(
                "repository",
                "visibility",
                r["visibility"],
                None if private is None else ("private" if private else "public"),
                repo=r["name"],
            )
        d = r.get("desired", {})
        if "default_token" in d and obs.get("default_workflow_permissions") != d["default_token"]:
            add(
                "repository",
                "default_token",
                d["default_token"],
                obs.get("default_workflow_permissions"),
                repo=r["name"],
            )
        if "fork_pr_approval" in d and obs.get("fork_pr_approval") != d["fork_pr_approval"]:
            add(
                "repository",
                "fork_pr_approval",
                d["fork_pr_approval"],
                obs.get("fork_pr_approval"),
                repo=r["name"],
            )
        if d.get("runner_registration") in ("none", "org-group"):
            rl = obs.get("repo_level_runners")
            if rl is None:
                add("infra", "runner_registration", d["runner_registration"], None, repo=r["name"])
            elif rl:
                add(
                    "infra",
                    "runner_registration",
                    d["runner_registration"],
                    "repository-level: " + ",".join(x["name"] for x in rl),
                    repo=r["name"],
                )
    return out


__all__ = ["audit", "discover", "drift"]
