"""tools/verify_platform_current.py: platform acceptance as a CURRENT decision (discovery is not optional).

Acceptance exists only for releases verified under trust/v1 (before 0.12.0), so those cases run the v0.11.0 verifier;
a trust/v2 release is `verified` with nothing to keep current (ADR 0024)."""

import hashlib
import importlib.util
import json
import unittest
from datetime import UTC, datetime

from tests import legacy_platform as TA
from tests.gh_repo import Repo
from tests.helpers import ROOT
from tests.test_verify_release import POLICY as V2_POLICY
from tests.test_verify_release import V as V2
from tests.test_verify_release import build_candidate, fake_gh


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


C = load("verify_platform_current", ROOT / "tools" / "verify_platform_current.py")
A = load("verify_app_release_for_platform", ROOT / "tools" / "verify_app_release.py")
V = TA.V1
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


class TrustV2(unittest.TestCase):
    def test_a_verified_release_is_the_decision_and_no_authorization_state_is_read(self):
        arc, sha = build_candidate(self, "1.0.0")
        exp = {
            "version": "1.0.0",
            "source_revision": "c" * 40,
            "archive_sha256": sha,
            "ref": "refs/tags/v1.0.0",
        }
        att = fake_gh(sha, "1.0.0")
        calls = []

        def gh(argv):
            calls.append(argv[:2])
            return att(argv)

        doc = C.current_acceptance(V2, A, arc, exp, V2_POLICY, gh=gh, now=NOW)
        self.assertEqual(doc["current_decision"]["state"], "verified")
        self.assertEqual(doc["currency"]["status"], "not-applicable")
        self.assertNotIn(["gh", "api"], calls)


@TA.needs_tag
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
        self.assertEqual(self.state(), "indeterminate")

    def test_deleted_record_fails_closed(self):
        self.record()
        self.record("rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        self.repo.delete("authorizations/rev.json", author="intruder", committer="intruder")
        self.assertEqual(self.state(), "indeterminate")

    def test_reasons_carry_stable_codes_and_unaccepted_differs_from_indeterminate(self):
        self.record()
        self.assertEqual(self.state(), "accepted")
        self.repo.fail = lambda ep: True
        doc = self.run_c()
        self.assertEqual([r["code"] for r in doc["currency"]["reasons"]], ["api-failure"])
        self.repo.fail = None
        self.record("rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        un = self.run_c()
        self.assertEqual(un["current_decision"]["state"], "verified-unaccepted")  # state read, not accepted
        self.assertEqual(un["currency"]["reasons"], [])

    def test_audit_state_is_cost_only_and_a_rewritten_history_is_noticed(self):
        from tests.helpers import tmpdir

        ad = tmpdir(self) / "audit"
        self.record()
        self.record("rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        self.assertEqual(self.state(audit_dir=ad), "verified-unaccepted")
        self.assertEqual(self.state(audit_dir=ad), self.state())
        self.repo.rewind(1)
        self.repo.commit({"x": b"y"}, author="bot", committer="bot")
        doc = self.run_c(audit_dir=ad)
        self.assertEqual(doc["current_decision"]["state"], "indeterminate")
        self.assertEqual([r["code"] for r in doc["currency"]["reasons"]], ["history-rewritten"])

    def test_a_platform_removal_cannot_be_acknowledged_away(self):
        self.record()
        self.record("rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        gone = self.repo.delete("authorizations/rev.json", author=TA.OWNER, committer=TA.OWNER)
        ack = json.loads(json.dumps(TA.POLICY))
        ack["authorization"]["acknowledged_removals"] = [{"path": "authorizations/rev.json", "commit": gone}]
        doc = C.current_acceptance(V, A, self.arc, self.exp, ack, gh=self.gh, now=NOW)
        self.assertEqual(doc["current_decision"]["state"], "indeterminate")  # restore the record instead
        self.assertEqual([r["code"] for r in doc["currency"]["reasons"]], ["record-removed"])

    def test_pins_are_enforced(self):
        with self.assertRaises(SystemExit):
            C._load(ROOT / "tools" / "verify_release.py", "0" * 64, "platform verifier")
        C._load(ROOT / "tools" / "verify_release.py",
                hashlib.sha256((ROOT / "tools" / "verify_release.py").read_bytes()).hexdigest(), "platform verifier")  # fmt: skip


if __name__ == "__main__":
    unittest.main()
