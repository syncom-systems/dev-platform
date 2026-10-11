"""Release planning over GitHub milestones, issues and pull requests (pure functions over a snapshot).

Planning state is not verification and not authority. Nothing here consumes or produces trust: milestone
completeness only yields `implementation-complete` in the lifecycle; notes and manifests are descriptive.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .errors import ConfigError

CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)
DISCLAIMER = (
    "Planning data only. A closed milestone, merged pull requests, labels and a green release workflow are "
    "not verification evidence and not owner authorization."
)


def load_policy(path: Path) -> dict:
    doc = json.loads(Path(path).read_text())
    if doc.get("schema") != "dev-platform.release-policy/v1":
        raise ConfigError([f"{path}: not a dev-platform.release-policy/v1 document"])
    if doc.get("assurance") not in doc.get("profiles", {}):
        raise ConfigError([f"{path}: assurance {doc.get('assurance')!r} is not a defined profile"])
    return doc


def _gh(args: list[str]):
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True)
    if r.returncode:
        raise ConfigError([f"gh api {' '.join(args)}: {r.stderr.strip()[:200]}"])
    return json.loads(r.stdout or "null")


def fetch_snapshot(repo: str, title: str) -> dict:
    """Milestone + its issues/PRs via the GitHub API (read-only)."""
    ms = _gh([f"repos/{repo}/milestones?state=all&per_page=100"])
    found = [m for m in ms if m["title"] == title]
    if not found:
        raise ConfigError([f"no milestone {title!r} in {repo}"])
    m = found[0]
    items = _gh(["--paginate", f"repos/{repo}/issues?milestone={m['number']}&state=all&per_page=100"])
    return {"repo": repo, "milestone": _ms(m), "items": [_item(i) for i in items], "external": {}}


def fetch_unassigned(repo: str) -> dict:
    ms = _gh([f"repos/{repo}/milestones?state=all&per_page=100"])
    items = _gh(["--paginate", f"repos/{repo}/issues?state=all&milestone=none&per_page=100"])
    linked = _gh(["--paginate", f"repos/{repo}/issues?state=all&milestone=*&per_page=100"])
    return {
        "repo": repo,
        "milestones": [_ms(m) for m in ms],
        "items": [_item(i) for i in items + linked],
    }


def _ms(m: dict) -> dict:
    return {
        "number": m["number"],
        "title": m["title"],
        "state": m["state"],
        "description": m.get("description") or "",
        "due_on": m.get("due_on"),
    }


def _item(i: dict) -> dict:
    pr = i.get("pull_request")
    return {
        "number": i["number"],
        "title": i["title"],
        "state": i["state"],
        "is_pr": bool(pr),
        "merged": bool(pr and pr.get("merged_at")),
        "body": i.get("body") or "",
        "labels": [lb["name"] for lb in i.get("labels", [])],
        "milestone": (i.get("milestone") or {}).get("title"),
    }


def _sections(description: str) -> set[str]:
    return {m.group(1).strip().lower() for m in re.finditer(r"^#{2,3}\s+(.+?)\s*$", description, re.M)}


def readiness(snapshot: dict, policy: dict) -> dict:
    """Is the milestone's planned scope complete? Yes means `implementation-complete` and nothing else."""
    profile = policy["profiles"][policy["assurance"]]
    blockers: list[dict] = []
    warnings: list[dict] = []
    ms = snapshot["milestone"]
    have = _sections(ms["description"])
    for sec in policy["milestone"]["required_sections"]:
        if sec.lower() not in have:
            blockers.append({"code": "milestone-section-missing", "detail": sec})
    items = snapshot["items"]
    issues = [i for i in items if not i["is_pr"]]
    prs = [i for i in items if i["is_pr"]]
    if not issues:
        blockers.append({"code": "milestone-empty", "detail": "no issues carry this milestone"})
    for i in issues:
        if i["state"] == "open":
            blockers.append({"code": "open-issue", "detail": f"#{i['number']} {i['title']}"})
    for p in prs:
        if p["state"] == "open":
            blockers.append({"code": "open-pull-request", "detail": f"#{p['number']} {p['title']}"})
    closing = {int(n) for p in prs if p["merged"] for n in CLOSING.findall(p["body"])}
    for i in issues:
        if i["state"] == "closed" and i["number"] not in closing:
            entry = {"code": "closed-issue-without-merged-pr", "detail": f"#{i['number']} {i['title']}"}
            (blockers if profile["require_issue_trace"] else warnings).append(entry)
    external = snapshot.get("external") or {}
    for need in profile["requires_external"]:
        att = external.get(need)
        if not (isinstance(att, dict) and att.get("ok") is True and att.get("reference")):
            blockers.append({"code": "external-attestation-missing", "detail": need})
    return {
        "milestone": ms["title"],
        "profile": policy["assurance"],
        "ready": not blockers,
        "implies": "implementation-complete" if not blockers else None,
        "blockers": blockers,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }


def plan_assignments(snapshot: dict) -> list[dict]:
    """Open or merged PRs without a milestone inherit the milestone of the issue they close."""
    by_num = {i["number"]: i for i in snapshot["items"] if not i["is_pr"]}
    out = []
    for p in snapshot["items"]:
        if not p["is_pr"] or p["milestone"]:
            continue
        targets = {by_num[int(n)]["milestone"] for n in CLOSING.findall(p["body"]) if int(n) in by_num}
        targets.discard(None)
        if len(targets) == 1:
            out.append({"number": p["number"], "milestone": targets.pop()})
        elif len(targets) > 1:
            out.append(
                {"number": p["number"], "milestone": None, "problem": "closes issues in several milestones"}
            )
    return out


def apply_assignments(repo: str, plan: list[dict], milestones: list[dict]) -> int:
    num = {m["title"]: m["number"] for m in milestones}
    n = 0
    for a in plan:
        if a.get("milestone") in num:
            r = subprocess.run(
                [
                    "gh",
                    "api",
                    "-X",
                    "PATCH",
                    f"repos/{repo}/issues/{a['number']}",
                    "-F",
                    f"milestone={num[a['milestone']]}",
                ],
                capture_output=True,
            )
            n += r.returncode == 0
    return n


def release_notes(snapshot: dict, version: str, verification: dict | None = None) -> str:
    merged = sorted((i for i in snapshot["items"] if i["is_pr"] and i["merged"]), key=lambda i: i["number"])
    closed = sorted(
        (i for i in snapshot["items"] if not i["is_pr"] and i["state"] == "closed"), key=lambda i: i["number"]
    )
    lines = [f"# dev-platform {version}: changes", "", f"_{DISCLAIMER}_", ""]
    lines += ["## Merged work", *[f"- {p['title']} (#{p['number']})" for p in merged], ""] if merged else []
    lines += ["## Closed issues", *[f"- {i['title']} (#{i['number']})" for i in closed], ""] if closed else []
    acc = ((verification or {}).get("acceptance") or {}).get("state")
    lines += [
        "## Evidence",
        f"Acceptance state per the verification record: {acc or 'no record supplied'}.",
        "These notes describe changes. The release's verification record and any authorization decision "
        "are the evidence; they are not replaced by this text.",
    ]
    return "\n".join(lines) + "\n"


def release_manifest(
    version: str,
    snapshot: dict,
    readiness_doc: dict,
    lifecycle_doc: dict,
    identity: dict | None,
    verification: dict | None,
    qualification: list[dict],
) -> dict:
    """Index linking planning scope to the artifact and its evidence. Descriptive; carries no authority."""
    acc = (verification or {}).get("acceptance") or {}
    return {
        "schema": "dev-platform.release-plan/v1",
        "version": version,
        "milestone": snapshot["milestone"]["title"],
        "scope": {
            "issues": sorted(i["number"] for i in snapshot["items"] if not i["is_pr"]),
            "pull_requests": sorted(i["number"] for i in snapshot["items"] if i["is_pr"]),
        },
        "readiness": {"ready": readiness_doc["ready"], "blockers": len(readiness_doc["blockers"])},
        "lifecycle": lifecycle_doc,
        "artifact": {
            k: (identity or {}).get(k)
            for k in ("archive_sha256", "tree_digest_pin", "source_revision", "git_tag")
        },
        "verification": {
            "acceptance_state": acc.get("state"),
            "authorization": acc.get("authorization"),
            "confers": acc.get("confers", []),
            "not_conferred": acc.get("not_conferred", []),
        },
        "qualification": qualification,
        "authority": "none: derived index; the verification record and authorization are the evidence",
    }
