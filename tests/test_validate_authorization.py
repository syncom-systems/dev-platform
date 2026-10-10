"""tools/validate_authorization.py against a fake GitHub API."""

import base64
import importlib.util
import json
import unittest

from tests.helpers import ROOT, tmpdir

spec = importlib.util.spec_from_file_location("va", ROOT / "tools" / "validate_authorization.py")
VA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(VA)

SHA = "f3ef0e50e23efc063e45041d6608ad87a7ea6150280529cd5bb969d168464dc2"
PATH = "authorizations/platform-release-0.1.0.json"


def record(**over):
    d = {
        "schema": VA.SCHEMA,
        "id": "auth-1",
        "subject": {"kind": "platform-release", "digest": SHA},
        "decision": "approved",
        "decided_by": {
            "id": "owner",
            "role": "owner",
            "identity_assertion": {"provider": VA.PROVIDER, "login": "owner-login", "reference": "x"},
        },
        "basis": {"kind": "review", "reference": "packet"},
        "decided_at": "2026-10-11T10:00:00Z",
        "retention": {"class": "permanent", "until": None},
    }
    d.update(over)
    return d


def fake_api(raw: bytes, *, verified=True, author="owner-login", committer="owner-login", content=None):
    def api(ep):
        if "/commits?" in ep:
            return [
                {
                    "sha": "a" * 40,
                    "commit": {
                        "verification": {"verified": verified, "reason": "valid" if verified else "unsigned"}
                    },
                    "author": {"login": author},
                    "committer": {"login": committer},
                }
            ]
        return {"content": base64.b64encode(raw if content is None else content).decode()}

    return api


class ValidateAuthorization(unittest.TestCase):
    def run_case(self, rec, api_kw=None, owner="owner-login", sha=SHA):
        raw = json.dumps(rec).encode()
        p = tmpdir(self) / "r.json"
        p.write_bytes(raw)
        return VA.validate(p, sha, owner, "o/r", PATH, fake_api(raw, **(api_kw or {})))

    def test_valid(self):
        self.assertEqual(self.run_case(record()), [])

    def test_wrong_archive(self):
        self.assertTrue(self.run_case(record(), sha="0" * 64))

    def test_not_approved(self):
        self.assertTrue(self.run_case(record(decision="rejected")))

    def test_wrong_kind(self):
        self.assertTrue(self.run_case(record(subject={"kind": "change", "digest": SHA})))

    def test_git_author_provider_refused(self):
        r = record()
        r["decided_by"]["identity_assertion"]["provider"] = "git-commit-author"
        self.assertTrue(self.run_case(r))

    def test_login_not_the_pinned_owner(self):
        self.assertTrue(self.run_case(record(), owner="someone-else"))

    def test_unsigned_commit(self):
        self.assertTrue(self.run_case(record(), {"verified": False}))

    def test_web_flow_committer_refused(self):
        self.assertTrue(self.run_case(record(), {"committer": "web-flow"}))

    def test_other_author(self):
        self.assertTrue(self.run_case(record(), {"author": "mallory"}))

    def test_file_differs_from_signed_commit(self):
        self.assertTrue(self.run_case(record(), {"content": b"{}"}))

    def test_template_is_invalid(self):
        t = json.loads((ROOT / "releases/0.1.0/authorization.template.json").read_text())
        self.assertTrue(VA.shape_problems(t, SHA))


if __name__ == "__main__":
    unittest.main()
