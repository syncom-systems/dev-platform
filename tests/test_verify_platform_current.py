"""tools/verify_platform_current.py: platform acceptance as a CURRENT decision (discovery is not optional)."""

import hashlib
import importlib.util
import json
import unittest
from datetime import UTC, datetime

from tests import test_authorization as TA
from tests.gh_repo import Repo
from tests.helpers import ROOT
from tests.test_verify_release import build_candidate, fake_gh


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = load("verify_platform_current", ROOT / "tools" / "verify_platform_current.py")
A = load("verify_app_release_for_platform", ROOT / "tools" / "verify_app_release.py")
V = TA.V
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


class Current(unittest.TestCase):
    def setUp(self):
        self.arc, self.sha = build_candidate(self, "1.0.0")
        self.repo = Repo()
        self.repo.commit({"README.md": b"x"}, author="bot", committer="bot")
        self.exp = {"version": "1.0.0", "source_revision": "c" * 40, "archive_sha256": self.sha,
                    "ref": "refs/tags/v1.0.0"}  # fmt: skip
        self.att = fake_gh(self.sha, "1.0.0")

    def gh(self, argv):
        return self.repo(argv) if argv[:2] == ["gh", "api"] else self.att(argv)

    def record(self, name="auth-1", **over):
        rec = TA.record(self.sha, name=name, **over)
        rec["decided_by"]["identity_assertion"]["login"] = TA.OWNER
        self.repo.sign(f"authorizations/{name}.json", json.dumps(rec, indent=2).encode(),
                       author=TA.OWNER, committer=TA.OWNER)  # fmt: skip

    def run_c(self, **kw):
        return C.current_acceptance(V, A, self.arc, self.exp, TA.POLICY, gh=self.gh, now=NOW, **kw)

    def state(self, **kw):
        return self.run_c(**kw)["current_decision"]["state"]

    def test_acceptance_in_the_evidence_repository_is_current_without_supplying_anything(self):
        self.record()
        doc = self.run_c()
        self.assertEqual(doc["current_decision"]["state"], "accepted")
        self.assertEqual(doc["currency"]["status"], "current")
        self.assertEqual(doc["currency"]["evidence"]["head_commit"], self.repo.commits[-1]["sha"])

    def test_nothing_in_the_repository_is_verified_unaccepted(self):
        self.assertEqual(self.state(), "verified-unaccepted")

    def test_revocation_published_after_the_supplied_acceptance_ends_it(self):
        self.record()
        self.record("rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        self.assertEqual(self.state(), "verified-unaccepted")

    def test_historical_acceptance_is_not_current_acceptance(self):
        self.record()
        self.record("rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        supplied = [self.write("auth-1")]
        out = self.run_c(historical=True, supplied=supplied)
        self.assertEqual(out["current_decision"]["state"], "historical-acceptance")
        self.assertEqual(out["currency"]["status"], "historical")

    def write(self, name):
        from tests.helpers import tmpdir

        d = tmpdir(self)
        f = d / f"{name}.json"
        f.write_bytes(self.repo.commits[-2]["tree"][f"authorizations/{name}.json"])
        return f

    def test_unreachable_evidence_repository_fails_closed(self):
        self.record()
        self.repo.fail = lambda ep: True
        self.assertEqual(self.state(), "failed")

    def test_deleted_record_fails_closed(self):
        self.record()
        self.record("rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        self.repo.delete("authorizations/rev.json", author="intruder", committer="intruder")
        self.assertEqual(self.state(), "failed")

    def test_pins_are_enforced(self):
        with self.assertRaises(SystemExit):
            C._load(ROOT / "tools" / "verify_release.py", "0" * 64, "platform verifier")
        C._load(ROOT / "tools" / "verify_release.py",
                hashlib.sha256((ROOT / "tools" / "verify_release.py").read_bytes()).hexdigest(), "platform verifier")  # fmt: skip


if __name__ == "__main__":
    unittest.main()
