"""Releases verified under `dev-platform.trust/v1` (before 0.12.0): the frozen verifier and policy of v0.11.0.

Current code still reads such releases (the application-release verifier's platform requirement, the current-
acceptance wrapper, the lifecycle), so those paths are tested against the verifier those releases were judged by,
taken from the release tag (a full clone, as in CI). Also the fakes for platform approval records and their signed
commits, which the application-release tests share.
"""

import base64
import json
import re
import subprocess
import types
import unittest
from datetime import UTC, datetime

from tests.helpers import ROOT

TAG = "v0.11.0"
OWNER = "owner-login"
OTHER = "someone-else"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
REPO = "syncom-systems/dev-platform"


def _show(path: str) -> bytes | None:
    p = subprocess.run(["git", "-C", str(ROOT), "show", f"{TAG}:{path}"], capture_output=True)
    return p.stdout if p.returncode == 0 else None


_SRC, _POL = _show("tools/verify_release.py"), _show("trust/policy.json")
AVAILABLE = _SRC is not None and _POL is not None
needs_tag = unittest.skipUnless(AVAILABLE, f"needs the {TAG} tag (a full clone)")

V1 = None
POLICY = None
if _SRC is not None and _POL is not None:
    V1 = types.ModuleType("verify_release_trust_v1")
    exec(compile(_SRC, f"{TAG}:tools/verify_release.py", "exec"), V1.__dict__)
    _base = {k: v for k, v in json.loads(_POL).items() if k != "continuity"}
    POLICY = {
        **_base,
        "require_environment_evidence": False,
        "authorization": {
            "providers": ["github-signed-commit"],
            "evidence_repo": REPO,
            "evidence_ref": "main",
            "approvers": [
                {
                    "id": "owner",
                    "provider": "github-signed-commit",
                    "login": OWNER,
                    "roles": ["owner"],
                    "may_approve": ["platform-release"],
                    "may_confer": ["platform-baseline"],
                }
            ],
        },
    }


def record(sha, name="auth-1", **over):
    """A platform approval record (dev-platform.authorization/v1) by OWNER via github-signed-commit."""
    d = {
        "schema": "dev-platform.authorization/v1",
        "id": name,
        "subject": {"kind": "platform-release", "digest": sha},
        "decision": "approved",
        "decided_by": {
            "id": "owner",
            "role": "owner",
            "identity_assertion": {
                "provider": "github-signed-commit",
                "login": OWNER,
                "path": f"authorizations/{name}.json",
            },
        },
        "basis": {"kind": "review", "reference": "packet"},
        "decided_at": "2026-10-10T10:00:00Z",
        "scope": {"confers": ["platform-baseline"]},
        "retention": {"class": "permanent", "until": None},
    }
    d.update(over)
    return d


class Github:
    """Fake `gh api` for commits and file contents. history[path] = commits, newest first."""

    def __init__(self):
        self.history: dict[str, list[dict]] = {}

    def sign(self, path, raw, *, verified=True, author=OWNER, committer=OWNER, content=None, sha=None):
        c = {
            "sha": sha or f"{len(self.history.get(path, [])) + 1:040x}",
            "commit": {"verification": {"verified": verified, "reason": "valid" if verified else "unsigned"}},
            "author": {"login": author},
            "committer": {"login": committer},
            "_content": raw if content is None else content,
        }
        self.history.setdefault(path, []).insert(0, c)

    def __call__(self, argv):
        assert argv[:2] == ["gh", "api"], argv
        ep = argv[2]
        m = re.search(r"/commits\?sha=([^&]+)&path=([^&]+)", ep)
        if m:
            assert m.group(1) == "main"
            commits = [
                {k: v for k, v in c.items() if k != "_content"} for c in self.history.get(m.group(2), [])
            ]
            return 0, json.dumps(commits), ""
        m = re.search(r"/contents/([^?]+)\?ref=(\w+)", ep)
        if m:
            for c in self.history.get(m.group(1), []):
                if c["sha"] == m.group(2):
                    return 0, json.dumps({"content": base64.b64encode(c["_content"]).decode()}), ""
        return 1, "", "not found"
