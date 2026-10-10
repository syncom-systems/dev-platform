#!/usr/bin/env python3
"""Independent validation of an owner authorization record (dev-platform.authorization/v1).

Imports nothing from `dev_platform`. A record is *valid* only when all of these hold:

  1. it is well formed, `approved`, for subject kind `platform-release` and exactly the archive sha256
     the operator passes in (--archive-sha256);
  2. its identity assertion is provider `github-signed-commit` and names the owner login;
  3. the owner login equals the login the operator pinned out-of-band (--owner-login), never one read
     from the record or the release;
  4. the latest commit that touched the record's path (--repo, --path, default branch) is a GitHub-
     verified signed commit whose author AND committer are that login (a squash or rebase merge makes
     GitHub the committer, which does not prove the owner signed it, and is refused);
  5. the file at that commit is byte-identical to the record supplied.

This checks that the record came from the pinned owner account's signing key. It is not a second
approval: it proves who decided, not that the decision was wise. It does not touch the release.

Exit status: 0 valid, 1 invalid, 2 usage.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

SCHEMA = "dev-platform.authorization/v1"
PROVIDER = "github-signed-commit"
SHA = re.compile(r"^[0-9a-f]{64}$")
Api = Callable[[str], object]


def gh_api(endpoint: str) -> object:
    r = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:200] or "gh api failed")
    return json.loads(r.stdout)


def shape_problems(doc: dict, archive_sha: str) -> list[str]:
    p = []
    if doc.get("schema") != SCHEMA:
        return [f"schema must be {SCHEMA!r}"]
    for k in ("id", "subject", "decision", "decided_by", "basis", "decided_at", "retention"):
        if k not in doc:
            p.append(f"missing {k}")
    sub = doc.get("subject") or {}
    if sub.get("kind") != "platform-release":
        p.append("subject.kind must be platform-release")
    if not SHA.match(str(sub.get("digest"))):
        p.append("subject.digest must be 64 hex")
    elif sub["digest"] != archive_sha:
        p.append("subject.digest is not the archive sha256 under review")
    if doc.get("decision") != "approved":
        p.append(f"decision is {doc.get('decision')!r}, not approved")
    ia = (doc.get("decided_by") or {}).get("identity_assertion") or {}
    if ia.get("provider") != PROVIDER:
        p.append(f"identity_assertion.provider must be {PROVIDER!r}")
    if not ia.get("login"):
        p.append("identity_assertion.login required")
    return p


def validate(
    record_path: Path, archive_sha: str, owner_login: str, repo: str, path: str, api: Api
) -> list[str]:
    raw = Path(record_path).read_bytes()
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        return [f"record is not JSON: {e}"]
    problems = shape_problems(doc, archive_sha)
    ia = (doc.get("decided_by") or {}).get("identity_assertion") or {}
    if ia.get("login") and ia["login"].lower() != owner_login.lower():
        problems.append("record names a different login than the pinned owner login")
    if problems:
        return problems
    try:
        commits = api(f"repos/{repo}/commits?path={path}&per_page=1")
        if not isinstance(commits, list) or not commits:
            return [f"no commit touches {path} on the default branch"]
        c = commits[0]
        v = c.get("commit", {}).get("verification", {})
        if not (v.get("verified") is True and v.get("reason") == "valid"):
            problems.append(f"latest commit on {path} is not a valid signed commit ({v.get('reason')})")
        for role in ("author", "committer"):
            login = (c.get(role) or {}).get("login") or ""
            if login.lower() != owner_login.lower():
                problems.append(f"{role} of {c.get('sha', '?')[:12]} is {login!r}, not the pinned owner")
        blob = api(f"repos/{repo}/contents/{path}?ref={c['sha']}")
        content = base64.b64decode(blob["content"]) if isinstance(blob, dict) and "content" in blob else b""
        if hashlib.sha256(content).hexdigest() != hashlib.sha256(raw).hexdigest():
            problems.append("record differs from the file in the signed commit")
    except (RuntimeError, KeyError, ValueError) as e:
        problems.append(f"cannot validate against GitHub: {e}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--record", type=Path, required=True)
    ap.add_argument("--archive-sha256", required=True)
    ap.add_argument("--owner-login", required=True, help="GitHub login pinned out-of-band by the operator")
    ap.add_argument("--repo", default="syncom-systems/dev-platform")
    ap.add_argument("--path", required=True, help="repository path the record is committed at")
    a = ap.parse_args(argv)
    if not SHA.match(a.archive_sha256):
        print("archive sha256 must be 64 hex", file=sys.stderr)
        return 2
    problems = validate(a.record, a.archive_sha256, a.owner_login, a.repo, a.path, gh_api)
    print(json.dumps({"valid": not problems, "problems": problems}, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
