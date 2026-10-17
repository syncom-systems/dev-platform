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


def _get(path: str, runner=subprocess.run, items: str | None = None):
    """One read-only GitHub API call: GET only, a fixed path shape, no request body. A list endpoint (`items`:
    the key holding the list, or "" for a bare JSON array) is read page by page to the end and merged, so a
    snapshot is never silently truncated."""
    if not _PATH.fullmatch(path) or ".." in path:
        raise ValueError(f"refusing API path {path!r}")
    argv = ["gh", "api", "--method", "GET"]
    if items is not None:
        argv += ["--paginate", "--slurp"]
        path += ("&" if "?" in path else "?") + "per_page=100"
    p = runner([*argv, path], capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        return {"_error": ((p.stderr or p.stdout or "").strip().splitlines() or ["gh failed"])[0][:200]}
    try:
        doc = json.loads(p.stdout)
    except ValueError:
        return {"_error": "not JSON"}
    if items is None:
        return doc
    if not isinstance(doc, list):
        return {"_error": "pages are not a list"}
    if items == "":
        if not all(isinstance(page, list) for page in doc):
            return {"_error": "unexpected page shape"}
        return [x for page in doc for x in page]
    if not all(isinstance(page, dict) and isinstance(page.get(items), list) for page in doc):
        return {"_error": "unexpected page shape"}
    return {items: [x for page in doc for x in page[items]]}


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
    get = lambda path, items=None: _get(path, runner, items)  # noqa: E731
    snap: dict = {"schema": SNAPSHOT, "owner": owner, "runner_groups": [], "repos": {}, "errors": []}
    groups = get(f"/orgs/{owner}/actions/runner-groups", "runner_groups")
    if _err(groups):
        snap["runner_groups"] = None
        snap["errors"].append(f"runner groups: {_err(groups)}")
    else:
        for g in groups.get("runner_groups", []):
            gid = g["id"]
            members = get(f"/orgs/{owner}/actions/runner-groups/{gid}/runners", "runners")
            entry = {
                "name": g.get("name"),
                "visibility": g.get("visibility"),
                "allows_public_repositories": g.get("allows_public_repositories"),
                "restricted_to_workflows": g.get("restricted_to_workflows"),
                "runners": None if _err(members) else [_runner(r) for r in members.get("runners", [])],
            }
            if g.get("visibility") == "selected":
                rs = get(f"/orgs/{owner}/actions/runner-groups/{gid}/repositories", "repositories")
                entry["repositories"] = (
                    None if _err(rs) else sorted(r["name"] for r in rs.get("repositories", []))
                )
                if _err(rs):
                    snap["errors"].append(f"runner group {g.get('name')}: repositories: {_err(rs)}")
            if _err(members):
                snap["errors"].append(f"runner group {g.get('name')}: runners: {_err(members)}")
            snap["runner_groups"].append(entry)
    for repo in repos:
        base = f"/repos/{owner}/{repo}"
        meta = get(base)
        runners = get(f"{base}/actions/runners", "runners")
        perms = get(f"{base}/actions/permissions/workflow")
        rulesets = get(f"{base}/rulesets", "")
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
    """Generic findings over a snapshot (no configuration needed). What could not be read is a `UNKNOWN`
    finding of severity high, never an absence of findings: a caller without permission gets no clean
    audit."""
    out: list[dict] = []

    def unknown(what, repo=None):
        out.append(
            _finding(
                "UNKNOWN",
                "high",
                f"{what} could not be read: nothing is concluded about it",
                "rerun discovery with an identity that may read it",
                True,
                "read access",
                "infra",
                repo,
            )
        )

    groups = snap.get("runner_groups")
    if groups is None:
        unknown("runner groups")
        groups = []
    grouped = {r["name"] for g in groups for r in (g.get("runners") or [])}
    for g in groups:
        if g.get("runners") is None:
            unknown(f"the runners of runner group {g.get('name')!r}")
        elif not g["runners"]:
            continue  # an empty group cannot run anything
        if g.get("allows_public_repositories") is not False:
            out.append(
                _finding(
                    "GRP-PUBLIC",
                    "critical" if g.get("allows_public_repositories") else "high",
                    f"runner group {g['name']!r} may have runners and allows (or may allow) public "
                    "repositories",
                    "disable allows_public_repositories on the group",
                    True,
                    "organization admin",
                    "infra",
                )
            )
        if g.get("visibility") != "selected":
            out.append(
                _finding(
                    "GRP-ALL",
                    "high",
                    f"runner group {g['name']!r} may have runners and is not "
                    "restricted to selected repositories",
                    "restrict the group to selected repositories",
                    True,
                    "organization admin",
                    "infra",
                )
            )
        if g.get("restricted_to_workflows") is not True:
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
        if r.get("private") is None:
            unknown("the repository's visibility", repo)
        public = r.get("private") is not True  # unknown visibility is judged as public
        runners = r.get("repo_level_runners")
        if runners is None:
            unknown("the repository-level runners", repo)
            runners = []
        for rn in runners:
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
            if not public and not r.get("rulesets"):
                out.append(
                    _finding(
                        "PRIVATE-UNPROTECTED",
                        "medium",
                        "a self-hosted runner serves a repository "
                        "without a ruleset (or its rulesets could not be read)",
                        "add a ruleset for the default branch",
                        True,
                        "repository admin",
                        "repository",
                        repo,
                        rn["name"],
                    )
                )
    for e in snap.get("errors") or []:
        if not any(f["id"] == "UNKNOWN" for f in out):
            unknown(f"part of the snapshot ({e})")
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
