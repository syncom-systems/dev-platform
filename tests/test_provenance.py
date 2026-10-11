"""Application-release assembly and rollback selection: only approved, fully linked, immutable
releases are selectable; every broken link names itself."""

import copy
import unittest

from dev_platform import provenance, records
from dev_platform.errors import ConfigError
from tests.helpers import tmpdir

SHA = lambda c: c * 64


def result(rev="a" * 40, tree=SHA("1"), ident=SHA("2"), **over):
    doc = {
        "schema": "dev-platform.result/v1",
        "platform": {"mode": "pinned", "running_version": "0.1.0", "pinned_version": "0.1.0", "digest": tree},
        "revision": rev,
        "stage": "full",
        "executed": True,
        "environment": {
            "release": {"version": "0.1.0", "tree_digest": tree},
            "profile": "python",
            "identity_digest": ident,
            "assurance": "certifiable",
            "conformant": True,
        },
        "certification": {"certified": True, "blockers": []},
    }
    doc.update(over)
    return doc


def make_release(version, res, artifact="b"):
    return provenance.assemble(
        res,
        name="app",
        version=version,
        source_uri="https://example.invalid/app",
        artifacts=[{"name": "app.tar", "sha256": SHA(artifact)}],
        resolution=SHA("c"),
    )


def approval(rel, id="auth-1", at="2026-10-10T12:00:00Z", decision="approved", **over):
    d = {
        "schema": "dev-platform.authorization/v1",
        "id": id,
        "subject": {"kind": "application-release", "digest": records.canonical_digest(rel)},
        "decision": decision,
        "decided_by": {
            "id": "qa",
            "role": "release-approver",
            "identity_assertion": {"provider": "github-signed-commit", "reference": "qa@example.invalid"},
        },
        "basis": {"kind": "ticket", "reference": "R-1"},
        "decided_at": at,
        "retention": {"class": "regulated", "until": None},
    }
    d.update(over)
    return d


class AssembleTest(unittest.TestCase):
    def test_assembles_a_valid_linked_record(self):
        res = result()
        rel = make_release("1.0.0", res)
        self.assertEqual(records.validate_app_release(rel), [])
        self.assertEqual(rel["source"]["revision"], "a" * 40)
        self.assertEqual(rel["platform"]["toolchain_identity_digest"], SHA("2"))
        self.assertEqual(rel["evidence"][0]["sha256"], records.canonical_digest(res))

    def test_refuses_anything_not_certified(self):
        bad = {
            "uncertified": result(certification={"certified": False, "blockers": ["x"]}),
            "not full": result(stage="pre-merge"),
            "not executed": result(executed=False),
            "self-hosted": result(platform={"mode": "self"}),
            "no revision": result(rev=None),
        }
        for name, res in bad.items():
            with self.assertRaises(ConfigError, msg=name):
                make_release("1.0.0", res)
        weak = result()
        weak["environment"]["assurance"] = "diagnostic"
        with self.assertRaises(ConfigError):
            make_release("1.0.0", weak)

    def test_resolution_digest_covers_names_and_bytes(self):
        d = tmpdir(self)
        (d / "a.lock").write_text("x")
        (d / "b.lock").write_text("y")
        base = provenance.resolution_digest([d / "a.lock", d / "b.lock"], d)
        self.assertEqual(base, provenance.resolution_digest([d / "b.lock", d / "a.lock"], d))
        (d / "b.lock").write_text("z")
        self.assertNotEqual(base, provenance.resolution_digest([d / "a.lock", d / "b.lock"], d))


class RollbackTest(unittest.TestCase):
    def setUp(self):
        self.r1, self.r2, self.r3 = result(rev="1" * 40), result(rev="2" * 40), result(rev="3" * 40)
        self.rel1 = make_release("1.0.0", self.r1, "1")
        self.rel2 = make_release("1.1.0", self.r2, "2")
        self.rel3 = make_release("1.2.0", self.r3, "3")
        self.results = {records.canonical_digest(r): r for r in (self.r1, self.r2, self.r3)}
        self.auths = [
            approval(self.rel1, "a1", "2026-10-01T00:00:00Z"),
            approval(self.rel2, "a2", "2026-10-05T00:00:00Z"),
            approval(self.rel3, "a3", "2026-10-09T00:00:00Z"),
        ]

    def select(self, rels=None, results=None, auths=None, **kw):
        return provenance.select_rollback(
            "app",
            "1.2.0",
            rels or [self.rel1, self.rel2, self.rel3],
            results if results is not None else self.results,
            auths if auths is not None else self.auths,
            **kw,
        )

    def why(self, out, version):
        return " ".join(next(r for r in out["rejected"] if r["version"] == version)["reasons"])

    def test_selects_most_recently_approved_earlier_release_and_never_the_current(self):
        out = self.select()
        self.assertEqual([e["version"] for e in out["eligible"]], ["1.1.0", "1.0.0"])
        self.assertEqual(out["eligible"][0]["authorization"], "a2")
        self.assertEqual(out["rejected"], [])

    def test_other_applications_are_ignored(self):
        other = copy.deepcopy(self.rel1)
        other["application"]["name"] = "other"
        self.assertEqual(len(self.select([other, self.rel2])["eligible"]), 1)

    def test_unapproved_revoked_superseded_and_misbound_approvals_are_ineligible(self):
        revoked = approval(self.rel2, "a2r", "2026-10-06T00:00:00Z", "revoked", supersedes=["a2"])
        out = self.select(auths=[self.auths[0], self.auths[1], revoked])
        self.assertIn("no effective approval", self.why(out, "1.1.0"))
        out = self.select(auths=[self.auths[1]])
        self.assertIn("no effective approval", self.why(out, "1.0.0"))
        tampered = copy.deepcopy(self.rel1)
        tampered["artifacts"][0]["sha256"] = SHA("f")  # an approved record cannot be altered later
        out = self.select(rels=[tampered], auths=[self.auths[0]])
        self.assertIn("no effective approval bound to this exact release", self.why(out, "1.0.0"))
        git_id = approval(self.rel1, "g")
        git_id["decided_by"]["identity_assertion"]["provider"] = "git-commit-author"
        self.assertIn(
            "no effective approval", self.why(self.select(rels=[self.rel1], auths=[git_id]), "1.0.0")
        )

    def test_missing_or_altered_evidence_is_ineligible(self):
        out = self.select(results={})
        self.assertIn("not available", self.why(out, "1.1.0"))
        forged = copy.deepcopy(self.r2)
        forged["revision"] = "9" * 40
        out = self.select(results={records.canonical_digest(self.r2): forged})
        self.assertIn("does not match its digest", self.why(out, "1.1.0"))

    def test_evidence_must_still_support_the_release_claims(self):
        bad = result(rev="2" * 40, ident=SHA("9"))  # different toolchain identity than the release recorded
        rel = copy.deepcopy(self.rel2)
        rel["evidence"] = [{"kind": "result", "sha256": records.canonical_digest(bad)}]
        out = self.select(rels=[rel], results={records.canonical_digest(bad): bad}, auths=[approval(rel)])
        self.assertIn("toolchain identity differs", self.why(out, "1.1.0"))
        unc = result(rev="2" * 40, certification={"certified": False, "blockers": ["x"]})
        rel2 = copy.deepcopy(self.rel2)
        rel2["evidence"] = [{"kind": "result", "sha256": records.canonical_digest(unc)}]
        out = self.select(rels=[rel2], results={records.canonical_digest(unc): unc}, auths=[approval(rel2)])
        self.assertIn("not certified", self.why(out, "1.1.0"))

    def test_platform_release_affected_by_an_advisory_is_ineligible(self):
        adv = {
            "schema": records.ADVISORY,
            "id": "ADV-1",
            "summary": "s",
            "severity": "high",
            "affected": [{"component": "dev-platform", "versions": ["0.1.0"]}],
        }
        out = self.select(advisories=[adv], platform_releases={"0.1.0": {"sbom_doc": {"components": []}}})
        self.assertEqual(out["eligible"], [])
        self.assertIn("ADV-1", self.why(out, "1.1.0"))

    def test_nothing_eligible_when_nothing_is_approved(self):
        self.assertEqual(self.select(auths=[])["eligible"], [])


if __name__ == "__main__":
    unittest.main()
