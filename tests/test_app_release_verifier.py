"""The independent application-release verifier (tools/verify_app_release.py, ADR 0019).

GitHub is faked at the `gh api` boundary; the verifier and the provider registry under test are the real ones.
Every must-be-rejected case asserts that the outcome is NOT `approved`.
"""

import copy
import hashlib
import importlib.util
import json
import unittest
from datetime import UTC, datetime

from dev_platform import provenance, records
from tests.helpers import ROOT, tmpdir
from tests.test_authorization import Github
from tests.test_provenance import SHA, result

spec = importlib.util.spec_from_file_location("verify_app_release", ROOT / "tools" / "verify_app_release.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
PV_PATH = ROOT / "tools" / "verify_release.py"
PV_SHA = hashlib.sha256(PV_PATH.read_bytes()).hexdigest()
V = A.load_platform_verifier(PV_PATH, PV_SHA)

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
REPO = "example/app"
APPROVER = "release-manager"
OTHER = "someone-else"
REV = "a" * 40
TREE = SHA("1")

POLICY = {
    "schema": "dev-platform.app-trust/v1",
    "authorization": {
        "providers": ["github-signed-commit"],
        "evidence_repo": REPO,
        "evidence_ref": "main",
        "approvers": [
            {
                "id": "rm",
                "provider": "github-signed-commit",
                "login": APPROVER,
                "roles": ["release-approver"],
                "may_approve": ["application-release"],
                "may_confer": ["application-release-approval"],
                "applications": ["app"],
            },
            {
                "id": "other-app",
                "provider": "github-signed-commit",
                "login": "other-app-owner",
                "roles": ["release-approver"],
                "may_approve": ["application-release"],
                "may_confer": ["application-release-approval"],
                "applications": ["different-app"],
            },
            {
                "id": "platform-owner",
                "provider": "github-signed-commit",
                "login": "platform-owner",
                "roles": ["owner"],
                "may_approve": ["platform-release"],
                "may_confer": ["platform-baseline"],
            },
        ],
    },
    "platform_releases": [{"version": "0.1.0", "tree_digest": TREE}],
}


def approval(rel, name="appr-1", login=APPROVER, **over):
    d = {
        "schema": "dev-platform.authorization/v1",
        "id": name,
        "subject": {"kind": "application-release", "digest": records.canonical_digest(rel)},
        "decision": "approved",
        "decided_by": {
            "id": "rm",
            "role": "release-approver",
            "identity_assertion": {
                "provider": "github-signed-commit",
                "login": login,
                "path": f"authorizations/{name}.json",
            },
        },
        "basis": {"kind": "review", "reference": "R-1"},
        "decided_at": "2026-10-10T10:00:00Z",
        "scope": {"confers": ["application-release-approval"]},
        "retention": {"class": "regulated", "until": None},
    }
    d.update(over)
    return d


class Case(unittest.TestCase):
    def setUp(self):
        self.d = tmpdir(self)
        self.gh = Github()
        self.res = result(rev=REV, tree=TREE)
        (self.d / "app.lock").write_text("pins\n")
        (self.d / "app.tar").write_bytes(b"artifact")
        self.rel = provenance.assemble(
            self.res,
            name="app",
            version="1.0.0",
            source_uri="https://example.invalid/app",
            artifacts=[{"name": "app.tar", "sha256": hashlib.sha256(b"artifact").hexdigest()}],
            resolution=provenance.resolution_digest([self.d / "app.lock"], self.d),
        )
        self.policy = copy.deepcopy(POLICY)

    def w(self, name, doc):
        p = self.d / name
        p.write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")
        return p

    def signed(self, doc, *, name=None, **sign):
        """Write the record and put a signed commit of exactly those bytes into the fake history."""
        name = name or doc["id"]
        p = self.w(f"{name}.json", doc)
        self.gh.sign(
            f"authorizations/{doc['id']}.json",
            p.read_bytes(),
            **({"author": APPROVER, "committer": APPROVER} | sign),
        )
        return p

    def run_v(self, auths=(), *, rel=None, results=None, mode="release", **kw):
        rel = rel if rel is not None else self.rel
        args = dict(
            mode=mode,
            source_revision=REV,
            locks=[self.d / "app.lock"],
            lock_root=self.d,
            artifacts={"app.tar": self.d / "app.tar"},
            results=[self.w("result.json", self.res)] if results is None else results,
            authorizations=list(auths),
            gh=self.gh,
            now=NOW,
        )
        args.update(kw)
        return A.verify(self.w("release.json", rel), self.policy, V, **args)

    def good_auth(self, **over):
        return self.signed(approval(self.rel, **over))

    def state(self, doc):
        return doc["approval"]["state"]

    def failed(self, doc):
        return {c["id"] for c in doc["checks"] if c["status"] == "failed"}


class Approved(Case):
    def test_exactly_bound_authenticated_authorized_approval(self):
        doc = self.run_v([self.good_auth()])
        self.assertEqual(self.state(doc), "approved", doc["checks"])
        self.assertEqual(doc["approval"]["confers"], ["application-release-approval"])
        self.assertEqual(doc["approval"]["approver"], "rm")
        self.assertEqual(doc["subject"]["release_sha256"], records.canonical_digest(self.rel))
        self.assertTrue(any("platform release acceptance" in x for x in doc["approval"]["not_conferred"]))
        self.assertEqual(
            doc["coverage"]["not_evaluated"], ["advisories (none supplied: absence is not safety)"]
        )

    def test_resolution_digest_matches_the_platform_implementation(self):
        self.assertEqual(
            A.resolution_digest([self.d / "app.lock"], self.d),
            provenance.resolution_digest([self.d / "app.lock"], self.d),
        )

    def test_canonical_digest_matches_the_platform_implementation(self):
        self.assertEqual(A.canonical_digest(self.rel), records.canonical_digest(self.rel))

    def test_select_mode_is_weaker_and_says_so(self):
        doc = self.run_v([self.good_auth()], mode="select", locks=[], artifacts={}, source_revision=None)
        self.assertEqual(self.state(doc), "approved")
        self.assertIn("source (operator pin of the revision)", doc["coverage"]["not_evaluated"])
        self.assertIn("artifacts (bytes)", doc["coverage"]["not_evaluated"])

    def test_wrong_platform_verifier_pin_is_refused(self):
        with self.assertRaises(SystemExit):
            A.load_platform_verifier(PV_PATH, "0" * 64)


class NoApproval(Case):
    def test_no_record(self):
        self.assertEqual(self.state(self.run_v([])), "unapproved")

    def test_never_committed_record(self):
        p = self.w("x.json", approval(self.rel))
        self.assertEqual(self.state(self.run_v([p])), "unapproved")

    def test_unsigned_commit(self):
        p = self.signed(approval(self.rel), verified=False)
        doc = self.run_v([p])
        self.assertEqual(self.state(doc), "unapproved")
        self.assertIn(
            "not a validly signed commit", doc["approval"]["authorization_evidence"][0]["problems"][0]
        )

    def test_squash_merge_makes_github_the_committer(self):
        self.assertEqual(
            self.state(self.run_v([self.signed(approval(self.rel), committer="web-flow")])), "unapproved"
        )

    def test_record_modified_after_signing(self):
        doc = approval(self.rel)
        p = self.signed(doc)
        p.write_text(json.dumps({**doc, "basis": {"kind": "review", "reference": "edited"}}))
        self.assertEqual(self.state(self.run_v([p])), "unapproved")

    def test_invented_and_authorship_providers(self):
        for prov in ("invented", "git-commit-author", "git-config"):
            doc = approval(self.rel, name=f"p-{prov}")
            doc["decided_by"]["identity_assertion"] = {
                "provider": prov,
                "login": APPROVER,
                "path": "authorizations/x.json",
            }
            self.assertEqual(self.state(self.run_v([self.w("p.json", doc)])), "unapproved", prov)

    def test_provider_not_enabled_by_the_policy(self):
        self.policy["authorization"]["providers"] = ["oidc"]
        self.assertEqual(self.state(self.run_v([self.good_auth()])), "unapproved")
        self.policy["authorization"]["providers"] = []
        self.assertNotEqual(self.state(self.run_v([self.good_auth()])), "approved")

    def test_authenticated_but_not_an_approver(self):
        doc = approval(self.rel, login=OTHER)
        p = self.signed(doc, author=OTHER, committer=OTHER)
        self.assertEqual(self.state(self.run_v([p])), "unapproved")

    def test_approver_for_a_different_application(self):
        doc = approval(self.rel, login="other-app-owner")
        p = self.signed(doc, author="other-app-owner", committer="other-app-owner")
        r = self.run_v([p])
        self.assertEqual(self.state(r), "unapproved")
        self.assertIn(
            "not authorized for application", r["approval"]["authorization_evidence"][0]["problems"][0]
        )

    def test_platform_owner_cannot_approve_an_application_release(self):
        doc = approval(self.rel, login="platform-owner")
        p = self.signed(doc, author="platform-owner", committer="platform-owner")
        self.assertEqual(self.state(self.run_v([p])), "unapproved")

    def test_scope_cannot_exceed_or_leave_the_conferrable_claim(self):
        for confers in (["platform-baseline"], ["application-release-approval", "certification"], []):
            p = self.signed(approval(self.rel, scope={"confers": confers}))
            self.assertEqual(self.state(self.run_v([p])), "unapproved", confers)
            self.gh.history.clear()

    def test_approver_may_confer_less_than_asked(self):
        self.policy["authorization"]["approvers"][0]["may_confer"] = []
        self.assertEqual(self.state(self.run_v([self.good_auth()])), "unapproved")

    def test_approval_of_a_different_release_does_not_bind(self):
        other = copy.deepcopy(self.rel)
        other["application"]["version"] = "1.0.1"
        self.assertEqual(self.state(self.run_v([self.signed(approval(other))])), "unapproved")

    def test_release_record_changed_after_approval(self):
        p = self.good_auth()
        changed = copy.deepcopy(self.rel)
        changed["application"]["version"] = "1.0.0+rebuilt"
        self.assertEqual(self.state(self.run_v([p], rel=changed)), "unapproved")
        changed = copy.deepcopy(self.rel)
        changed["artifacts"][0]["sha256"] = SHA("9")
        self.assertNotEqual(self.state(self.run_v([p], rel=changed)), "approved")

    def test_wrong_subject_kind(self):
        doc = approval(self.rel)
        doc["subject"]["kind"] = "platform-release"
        self.assertEqual(self.state(self.run_v([self.signed(doc)])), "unapproved")

    def test_future_expired_not_yet_valid(self):
        for over in (
            {"decided_at": "2026-10-13T00:00:00Z"},
            {"validity": {"not_after": "2026-10-11T00:00:00Z"}},
            {"validity": {"not_before": "2026-10-13T00:00:00Z"}},
        ):
            p = self.signed(approval(self.rel, **over))
            self.assertEqual(self.state(self.run_v([p])), "unapproved", over)
            self.gh.history.clear()

    def test_rejected_decision(self):
        self.assertEqual(self.state(self.run_v([self.good_auth(decision="rejected")])), "unapproved")


class Revocation(Case):
    def test_authentic_revocation_removes_approval(self):
        a = self.good_auth()
        rv = self.signed(
            approval(
                self.rel,
                name="rev",
                decision="revoked",
                decided_at="2026-10-11T10:00:00Z",
                supersedes=["appr-1"],
            )
        )
        doc = self.run_v([a, rv])
        self.assertEqual(self.state(doc), "unapproved")

    def test_revocation_without_supersedes_still_wins_by_time(self):
        a = self.good_auth()
        rv = self.signed(
            approval(self.rel, name="rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        )
        self.assertEqual(self.state(self.run_v([a, rv])), "unapproved")

    def test_unauthorized_revocation_is_ignored(self):
        a = self.good_auth()
        rv = self.signed(
            approval(
                self.rel,
                name="rev",
                login=OTHER,
                decision="revoked",
                decided_at="2026-10-11T10:00:00Z",
                supersedes=["appr-1"],
            ),
            author=OTHER,
            committer=OTHER,
        )
        doc = self.run_v([a, rv])
        self.assertEqual(self.state(doc), "approved")
        self.assertEqual(doc["approval"]["authorization_evidence"][1]["status"], "ignored")

    def test_unsigned_supersession_is_ignored(self):
        a = self.good_auth()
        rv = self.signed(
            approval(
                self.rel,
                name="rev",
                decision="rejected",
                decided_at="2026-10-11T10:00:00Z",
                supersedes=["appr-1"],
            ),
            verified=False,
        )
        self.assertEqual(self.state(self.run_v([a, rv])), "approved")

    def test_re_approval_after_revocation(self):
        a = self.good_auth()
        rv = self.signed(
            approval(self.rel, name="rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        )
        again = self.signed(
            approval(self.rel, name="again", decided_at="2026-10-11T11:00:00Z", supersedes=["rev"])
        )
        self.assertEqual(self.state(self.run_v([a, rv, again])), "approved")

    def test_equal_timestamps_fail_closed(self):
        a = self.good_auth()
        rv = self.signed(
            approval(self.rel, name="rev", decision="revoked", decided_at="2026-10-10T10:00:00Z")
        )
        self.assertEqual(self.state(self.run_v([a, rv])), "unapproved")

    def test_revocation_of_another_release_does_not_revoke_this_one(self):
        other = copy.deepcopy(self.rel)
        other["application"]["version"] = "2.0.0"
        a = self.good_auth()
        rv = self.signed(
            approval(
                other,
                name="rev",
                decision="revoked",
                decided_at="2026-10-11T10:00:00Z",
                supersedes=["appr-1"],
            )
        )
        self.assertEqual(self.state(self.run_v([a, rv])), "approved")

    def test_removing_the_approver_from_the_policy_ends_the_approval(self):
        a = self.good_auth()
        self.policy["authorization"]["approvers"] = self.policy["authorization"]["approvers"][1:]
        self.assertEqual(self.state(self.run_v([a])), "unapproved")


class Binding(Case):
    """Authentic approval, but the evidence does not match: never approved."""

    def check(self, check_id, **kw):
        doc = self.run_v([self.good_auth()], **kw)
        self.assertEqual(self.state(doc), "failed", doc["checks"])
        self.assertIn(check_id, self.failed(doc))
        return doc

    def test_wrong_source_revision_pin(self):
        self.check("source-revision", source_revision="b" * 40)

    def test_missing_source_pin(self):
        self.check("source-revision", source_revision=None)

    def test_dependency_state_changed(self):
        (self.d / "app.lock").write_text("different pins\n")
        self.check("dependency-resolution")

    def test_lock_not_supplied(self):
        self.check("dependency-resolution", locks=[])

    def test_artifact_bytes_differ(self):
        (self.d / "app.tar").write_bytes(b"tampered")
        self.check("artifact-digests")

    def test_artifact_not_supplied_or_extra(self):
        self.check("artifact-digests", artifacts={})
        (self.d / "extra").write_bytes(b"x")
        self.check("artifact-digests", artifacts={"app.tar": self.d / "app.tar", "extra": self.d / "extra"})

    def test_missing_evidence(self):
        self.check("verification-evidence", results=[])

    def test_manipulated_result_does_not_match_its_digest(self):
        forged = copy.deepcopy(self.res)
        forged["revision"] = "b" * 40
        self.check("verification-evidence", results=[self.w("forged.json", forged)])

    def test_stale_evidence_for_another_revision(self):
        stale = result(rev="b" * 40, tree=TREE)
        rel = copy.deepcopy(self.rel)
        rel["evidence"] = [{"kind": "result", "sha256": records.canonical_digest(stale)}]
        a = self.signed(approval(rel))
        doc = self.run_v([a], rel=rel, results=[self.w("stale.json", stale)])
        self.assertEqual(self.state(doc), "failed")
        self.assertIn("verification-evidence", self.failed(doc))

    def test_uncertified_or_non_full_evidence(self):
        for name, res in {
            "uncertified": result(rev=REV, tree=TREE, certification={"certified": False, "blockers": ["x"]}),
            "pre-merge": result(rev=REV, tree=TREE, stage="pre-merge"),
            "not-executed": result(rev=REV, tree=TREE, executed=False),
            "self-hosted": result(rev=REV, tree=TREE, platform={"mode": "self"}),
        }.items():
            rel = copy.deepcopy(self.rel)
            rel["evidence"] = [{"kind": "result", "sha256": records.canonical_digest(res)}]
            a = self.signed(approval(rel, name=f"a-{name}"))
            doc = self.run_v([a], rel=rel, results=[self.w(f"{name}.json", res)])
            self.assertEqual(self.state(doc), "failed", name)

    def test_unknown_evidence_kind_cannot_be_verified(self):
        rel = copy.deepcopy(self.rel)
        rel["evidence"].append({"kind": "attestation", "sha256": SHA("7")})
        a = self.signed(approval(rel))
        doc = self.run_v([a], rel=rel)
        self.assertEqual(self.state(doc), "failed")

    def test_toolchain_identity_differs_from_evidence(self):
        rel = copy.deepcopy(self.rel)
        rel["platform"]["toolchain_identity_digest"] = SHA("8")
        a = self.signed(approval(rel))
        self.assertEqual(self.state(self.run_v([a], rel=rel)), "failed")

    def test_platform_release_not_allowed_by_application_policy(self):
        self.policy["platform_releases"] = [{"version": "0.1.0", "tree_digest": SHA("5")}]
        self.check("platform-release")

    def test_platform_release_acceptance_is_not_a_substitute_for_the_policy(self):
        self.policy["platform_releases"] = [{"version": "9.9.9", "tree_digest": TREE}]
        self.check("platform-release")

    def test_malformed_release_record(self):
        bad = copy.deepcopy(self.rel)
        bad["dependencies"]["resolution_digest"] = "xyz"
        doc = self.run_v([], rel=bad)
        self.assertEqual(self.state(doc), "failed")
        self.assertIn("release-record", self.failed(doc))

    def test_policy_without_platform_releases(self):
        del self.policy["platform_releases"]
        self.check("application-policy")


class Advisories(Case):
    def adv(self, component, versions=None, ranges=None):
        a = {"component": component}
        a.update({"versions": versions} if versions else {"ranges": ranges})
        return self.w(
            "adv.json",
            {
                "schema": "dev-platform.advisory/v1",
                "id": "ADV-1",
                "summary": "s",
                "severity": "high",
                "affected": [a],
            },
        )

    def test_advisory_on_the_platform_release_blocks(self):
        doc = self.run_v([self.good_auth()], advisories=[self.adv("dev-platform", ranges=["<0.2.0"])])
        self.assertEqual(self.state(doc), "failed")
        self.assertIn("advisories", self.failed(doc))

    def test_advisory_on_the_application_blocks(self):
        doc = self.run_v([self.good_auth()], advisories=[self.adv("app", versions=["1.0.0"])])
        self.assertEqual(self.state(doc), "failed")

    def test_unrelated_advisory_does_not_block(self):
        doc = self.run_v([self.good_auth()], advisories=[self.adv("dev-platform", ranges=[">=0.2.0"])])
        self.assertEqual(self.state(doc), "approved")
        self.assertNotIn(
            "advisories (none supplied: absence is not safety)", doc["coverage"]["not_evaluated"]
        )

    def test_component_advisory_from_the_platform_sbom(self):
        sbom = self.w("sbom.json", {"components": [{"name": "ruff", "version": "0.1.0"}]})
        doc = self.run_v(
            [self.good_auth()], advisories=[self.adv("ruff", ranges=["<0.2"])], platform_sbom=sbom
        )
        self.assertEqual(self.state(doc), "failed")

    def test_unreadable_advisory_fails_closed(self):
        bad = self.w("bad.json", {"schema": "nope"})
        self.assertEqual(self.state(self.run_v([self.good_auth()], advisories=[bad])), "failed")

    def test_sbom_must_match_the_policy_pin_when_pinned(self):
        self.policy["platform_releases"][0]["sbom_sha256"] = SHA("4")
        sbom = self.w("sbom.json", {"components": []})
        doc = self.run_v([self.good_auth()], advisories=[self.adv("x", versions=["1"])], platform_sbom=sbom)
        self.assertEqual(self.state(doc), "failed")


if __name__ == "__main__":
    unittest.main()
