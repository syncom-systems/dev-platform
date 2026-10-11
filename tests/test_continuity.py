"""Predecessor continuity (issue #4): evidence, never authority."""

import copy
import json
import unittest
from pathlib import Path

from tests.helpers import ROOT, tmpdir
from tests.test_verify_release import POLICY, REV, V, fake_gh

SHA = "a" * 64
PRED = {"version": "0.1.2", "archive_sha256": "b" * 64, "tree_digest": "c" * 64}
EXP = {"version": "0.2.0", "source_revision": REV, "archive_sha256": SHA, "ref": "refs/tags/v0.2.0"}
POL = {**POLICY, "continuity": {"predecessor": PRED}}


def record(**over):
    d = {
        "schema": "dev-platform.continuity/v1",
        "subject": {"version": "0.2.0", "archive_sha256": SHA, "source_revision": REV},
        "predecessor": {**PRED, "verification": {"state": "verified-unaccepted", "all_checks_passed": True}},
        "stage": {"name": "full", "exit": 0, "admission": "admitted", "revision": REV},
    }
    for k, v in over.items():
        d[k] = v
    return d


class Continuity(unittest.TestCase):
    def run_check(self, doc=None, policy=POL, gh=None, missing=False):
        rec = V.Record()
        path = None
        if not missing:
            path = tmpdir(self) / "c.json"
            path.write_text(doc if isinstance(doc, str) else json.dumps(doc if doc is not None else record()))
        V.check_continuity(rec, path, EXP, SHA, policy, gh or fake_gh(SHA, "0.2.0"))
        return {c["id"]: c["status"] for c in rec.checks}

    def test_good(self):
        r = self.run_check()
        self.assertEqual(r["continuity"], "passed")
        self.assertEqual(r["continuity-attestation-matches-policy"], "passed")

    def test_legacy_policy_without_the_key_is_unchanged(self):
        pol = {k: v for k, v in POL.items() if k != "continuity"}
        self.assertEqual(self.run_check(policy=pol, missing=True), {})

    def test_declared_first_release(self):
        pol = {**POL, "continuity": {"predecessor": None}}
        self.assertEqual(self.run_check(policy=pol, missing=True), {"continuity": "passed"})

    def test_record_required_when_predecessor_named(self):
        self.assertEqual(self.run_check(missing=True), {"continuity": "failed"})

    def test_rejections(self):
        def mut(f):
            d = copy.deepcopy(record())
            f(d)
            return d

        cases = {
            "unreadable": "not json",
            "wrong schema": mut(lambda d: d.update(schema="x")),
            "other archive": mut(lambda d: d["subject"].update(archive_sha256="e" * 64)),
            "other revision": mut(lambda d: d["subject"].update(source_revision="d" * 40)),
            "stage ran elsewhere": mut(lambda d: d["stage"].update(revision="d" * 40)),
            "other predecessor digest": mut(lambda d: d["predecessor"].update(archive_sha256="e" * 64)),
            "other predecessor tree": mut(lambda d: d["predecessor"].update(tree_digest="e" * 64)),
            "other predecessor version": mut(lambda d: d["predecessor"].update(version="0.1.0")),
            "predecessor unverified": mut(lambda d: d["predecessor"]["verification"].update(state="failed")),
            "predecessor checks failed": mut(
                lambda d: d["predecessor"]["verification"].update(all_checks_passed=False)
            ),
            "stage failed": mut(lambda d: d["stage"].update(exit=1)),
            "not admitted": mut(lambda d: d["stage"].update(admission="blocked")),
            "wrong stage": mut(lambda d: d["stage"].update(name="pre-commit")),
        }
        for name, doc in cases.items():
            with self.subTest(name):
                self.assertEqual(self.run_check(doc)["continuity"], "failed")

    def test_unattested_record_fails(self):
        r = self.run_check(gh=fake_gh(SHA, "0.2.0", code=1))
        self.assertEqual(r["continuity"], "passed")
        self.assertIn("failed", r.values())

    def test_continuity_never_confers_acceptance(self):
        # an accepted predecessor does not make N accepted: continuity has no effect on authorization
        doc = record()
        doc["predecessor"]["verification"]["state"] = "accepted"
        self.assertEqual(self.run_check(doc)["continuity"], "passed")
        src = Path(V.__file__).read_text()
        self.assertNotIn(
            "continuity", src[src.index("def effective_authorization") : src.index("def verify(")]
        )

    def test_shipped_policy_pins_the_real_predecessor(self):
        from tests.test_verify_release import SHIPPED_POLICY

        ident = json.loads((ROOT / "releases" / "0.1.2" / "identity.json").read_text())
        pred = SHIPPED_POLICY["continuity"]["predecessor"]
        self.assertEqual(pred["version"], "0.1.2")
        self.assertEqual(pred["archive_sha256"], ident["archive_sha256"])
        self.assertEqual(pred["tree_digest"], ident["tree_digest_pin"])

    def test_release_workflow_runs_and_verifies_continuity(self):
        wf = (ROOT / ".github" / "workflows" / "release.yml").read_text()
        self.assertIn("tools/run_continuity.py", wf)
        self.assertIn("--continuity", wf)
        # predecessor code runs in a job with no write or token permissions
        job = wf[wf.index("\n  continuity:") : wf.index("\n  attest-continuity:")]
        self.assertNotIn("id-token", job)
        self.assertNotIn(": write", job)


if __name__ == "__main__":
    unittest.main()
