"""The independent application-release verifier (tools/verify_app_release.py, ADR 0019).

GitHub is faked at the `gh api` boundary; the verifier and the provider registry under test are the real ones.
Every must-be-rejected case asserts that the outcome is NOT `approved`.
"""

import copy
import hashlib
import importlib.util
import json
import unittest
from datetime import UTC, datetime, timedelta

from dev_platform import provenance, records
from tests.gh_repo import Repo
from tests.helpers import ROOT, tmpdir
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
        self.gh = Repo()
        self.gh.commit({"README.md": b"evidence"}, author="bot", committer="bot")
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


class CurrentState(Case):
    """Operational decisions need the CURRENT authorization state; historical inspection never claims it."""

    REVOKED = {"decision": "revoked", "decided_at": "2026-10-11T10:00:00Z"}

    def revoke(self, **sign):
        return self.signed(approval(self.rel, name="rev", **self.REVOKED), **sign)

    def test_historical_approval_then_independent_revocation_absent_from_the_bundle(self):
        ok = self.good_auth()  # the only record the old evidence bundle holds
        self.revoke()  # published afterwards, directly to the evidence repository
        hist = self.run_v([ok], purpose="historical")
        self.assertEqual(self.state(hist), "historical-approval")  # authentic once, never `approved`
        self.assertEqual(hist["currency"]["status"], "historical")
        self.assertIn("NOT a current authorization", hist["approval"]["reasons"][0])
        self.assertTrue(
            any("later revocations are not looked for" in x for x in hist["coverage"]["not_evaluated"])
        )
        cur = self.run_v([ok])
        self.assertEqual(self.state(cur), "unapproved")
        self.assertEqual(cur["currency"]["status"], "current")
        names = {v["file"]: v["status"] for v in cur["approval"]["authorization_evidence"]}
        self.assertEqual(
            names, {"appr-1.json": "authentic", "rev.json": "authentic"}
        )  # revocation was judged

    def test_the_default_is_operational(self):
        self.assertEqual(self.run_v([self.good_auth()])["currency"]["purpose"], "operational")

    def test_historical_never_yields_approved(self):
        self.assertEqual(
            self.state(self.run_v([self.good_auth()], purpose="historical")), "historical-approval"
        )
        self.assertEqual(self.state(self.run_v([], purpose="historical")), "unapproved")

    def test_unknown_purpose_is_refused(self):
        with self.assertRaises(ValueError):
            self.run_v([], purpose="whenever")

    def test_current_state_is_identified_and_expires(self):
        doc = self.run_v([self.good_auth()])
        cur = doc["currency"]
        self.assertEqual(cur["max_age_seconds"], A.DEFAULT_MAX_AGE)
        self.assertEqual(cur["observed_at"], NOW.isoformat())
        self.assertEqual(cur["valid_until"], (NOW + timedelta(seconds=A.DEFAULT_MAX_AGE)).isoformat())
        ev = cur["evidence"]
        self.assertEqual(ev["head_commit"], self.gh.commits[-1]["sha"])
        self.assertEqual(ev["records"], ["appr-1.json"])
        self.assertEqual(ev["removed"], [])
        self.policy["freshness"] = {"max_age_seconds": 60}
        self.assertEqual(self.run_v([self.good_auth()])["currency"]["max_age_seconds"], 60)

    def test_freshness_policy_is_bounded(self):
        for bad in ({"max_age_seconds": 0}, {"max_age_seconds": 3601}, {"max_age_seconds": "5"}, {}, []):
            self.policy["freshness"] = bad
            self.assertTrue(any("freshness" in x for x in A.policy_problems(self.policy)), bad)
        self.policy["freshness"] = {"max_age_seconds": 3600}
        self.assertFalse(any("freshness" in x for x in A.policy_problems(self.policy)))

    def test_unreachable_evidence_repository_fails_closed(self):
        ok = self.good_auth()
        self.gh.fail = lambda ep: True
        doc = self.run_v([ok])
        self.assertEqual(self.state(doc), "failed")
        self.assertIn("authorization-currency", self.failed(doc))
        self.assertEqual(doc["currency"]["status"], "unverifiable")
        self.assertIsNone(doc["currency"]["valid_until"])

    def test_listing_outage_fails_closed(self):
        ok = self.good_auth()
        self.gh.fail = lambda ep: "/contents/authorizations?ref=" in ep
        self.assertEqual(self.state(self.run_v([ok])), "failed")

    def test_history_outage_fails_closed(self):
        ok = self.good_auth()
        self.gh.fail = lambda ep: "&per_page=100&page=" in ep
        self.assertEqual(self.state(self.run_v([ok])), "failed")

    def test_unreadable_record_fails_closed(self):
        ok = self.good_auth()
        self.revoke()
        self.gh.fail = lambda ep: "/contents/authorizations/rev.json" in ep
        self.assertEqual(self.state(self.run_v([ok])), "failed")

    def test_a_revocation_that_cannot_be_authenticated_does_not_leave_the_approval_standing(self):
        ok = self.good_auth()
        self.revoke()
        # the commit history of the revocation is unreachable: it looks "not authentic", but it is unknown
        self.gh.fail = lambda ep: "&path=authorizations/rev.json" in ep
        doc = self.run_v([ok])
        self.assertEqual(self.state(doc), "failed")
        self.assertIn("authorization-currency", self.failed(doc))

    def test_unresolvable_ref_fails_closed(self):
        ok = self.good_auth()
        self.policy["authorization"]["evidence_ref"] = "no-such-branch"
        self.assertEqual(self.state(self.run_v([ok])), "failed")

    def test_revocation_deleted_from_the_evidence_history_is_not_silently_absent(self):
        ok = self.good_auth()
        self.revoke()
        self.gh.delete("authorizations/rev.json", author="intruder", committer="intruder")
        doc = self.run_v([ok])
        self.assertEqual(self.state(doc), "failed")
        self.assertIn("deleted from the evidence history", " ".join(c["detail"] for c in doc["checks"]))
        self.assertEqual(doc["currency"]["status"], "unverifiable")

    def test_deleted_approval_is_also_flagged(self):
        self.good_auth()
        self.gh.delete("authorizations/appr-1.json", author=APPROVER, committer=APPROVER)
        self.assertEqual(self.state(self.run_v([])), "failed")

    def test_revocation_by_someone_who_may_not_revoke_does_not_revoke(self):
        ok = self.good_auth()
        stranger = approval(self.rel, name="rev", login=OTHER, **self.REVOKED)
        self.signed(stranger, author=OTHER, committer=OTHER)
        doc = self.run_v([ok])
        self.assertEqual(self.state(doc), "approved")
        self.assertTrue(any("not an approver" in x for v in doc["approval"]["authorization_evidence"]
                            for x in v["problems"]))  # fmt: skip

    def test_publication_during_the_read_is_picked_up_by_a_second_read(self):
        ok = self.good_auth()
        fired = []

        def publish_once(ep):
            if "/contents/authorizations?ref=" in ep and not fired:
                fired.append(ep)
                self.revoke()

        self.gh.hooks.append(publish_once)
        doc = self.run_v([ok])
        self.assertEqual(self.state(doc), "unapproved")  # the revocation published mid-read was not missed
        self.assertEqual(doc["currency"]["evidence"]["head_commit"], self.gh.commits[-1]["sha"])

    def test_a_ref_that_never_stops_moving_fails_closed(self):
        ok = self.good_auth()
        n = []

        def keep_publishing(ep):
            if "/contents/authorizations?ref=" in ep:
                n.append(1)
                self.gh.commit({f"notes/{len(n)}.txt": b"x"}, author="bot", committer="bot")

        self.gh.hooks.append(keep_publishing)
        doc = self.run_v([ok])
        self.assertEqual(self.state(doc), "failed")
        self.assertIn("moved while it was being read", " ".join(c["detail"] for c in doc["checks"]))

    def test_history_too_long_to_audit_fails_closed(self):
        ok = self.good_auth()
        for i in range(500):
            self.gh.commit({"authorizations/notes.txt": str(i).encode()}, author="bot", committer="bot")
        self.assertEqual(self.state(self.run_v([ok])), "failed")

    def test_empty_authorizations_directory_is_a_complete_answer_not_an_outage(self):
        doc = self.run_v([])
        self.assertEqual(self.state(doc), "unapproved")
        self.assertEqual(doc["currency"]["status"], "current")
        self.assertEqual(doc["currency"]["evidence"]["records"], [])

    def test_provider_evidence_is_pinned_to_the_commit_that_was_read(self):
        ok = self.good_auth()
        ev = self.run_v([ok])["approval"]["authorization_evidence"][0]["evidence"]
        self.assertEqual(ev["ref"], self.gh.commits[-1]["sha"])

    def test_supplied_and_discovered_copies_are_judged_once(self):
        doc = self.run_v([self.good_auth()])
        self.assertEqual(len(doc["approval"]["authorization_evidence"]), 1)

    def test_discovery_can_find_an_approval_the_caller_did_not_supply(self):
        self.good_auth()
        self.assertEqual(self.state(self.run_v([])), "approved")

    def test_a_later_approval_supersedes_a_revocation(self):
        ok = self.good_auth()
        self.revoke()
        self.signed(approval(self.rel, name="again", decided_at="2026-10-11T12:00:00Z"))
        self.assertEqual(self.state(self.run_v([ok])), "approved")


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
        edited = json.dumps({**doc, "basis": {"kind": "review", "reference": "edited"}}).encode()
        p.write_bytes(edited)
        out = self.run_v([p])
        # the edited local copy is judged and refused; the genuine committed record is found by discovery
        self.assertTrue(any("modified after signing" in x for v in out["approval"]["authorization_evidence"]
                            for x in v["problems"]))  # fmt: skip
        self.assertEqual(self.state(out), "approved")
        # edited IN the repository by an unsigned commit: nothing authentic remains
        self.gh.commit(
            {f"authorizations/{doc['id']}.json": edited}, verified=False, author=APPROVER, committer=APPROVER
        )
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
            self.gh.wipe()

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
            self.gh.wipe()

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


class RequiredPlatformAcceptance(Case):
    """An application policy may require its Dev Platform release to be owner-ACCEPTED. That is an extra
    eligibility condition established by re-running the platform verifier; it never approves the application,
    and platform authority never carries over to application approval (or the reverse)."""

    PLATFORM_OWNER = "platform-owner"

    def setUp(self):
        from tests import test_authorization as TA
        from tests import test_verify_release as TV

        super().setUp()
        self.TA, self.TV = TA, TV
        self.arc, self.psha = TV.build_candidate(self, "1.0.0")
        self.pgh = Repo()
        self.pgh.commit({"README.md": b"platform evidence"}, author="bot", committer="bot")
        self.pexp = {"version": "1.0.0", "source_revision": "c" * 40, "archive_sha256": self.psha,
                     "ref": "refs/tags/v1.0.0"}  # fmt: skip
        self.ppolicy = TA.POLICY
        tree = self.platform_doc([])["subject"]["tree_digest"]
        v = "1.0.0"
        self.res = result(rev=REV, tree=tree)
        self.res["platform"].update(running_version=v, pinned_version=v)
        self.res["environment"]["release"]["version"] = v
        self.rel = provenance.assemble(
            self.res, name="app", version="1.0.0", source_uri="https://example.invalid/app",
            artifacts=[{"name": "app.tar", "sha256": hashlib.sha256(b"artifact").hexdigest()}],
            resolution=provenance.resolution_digest([self.d / "app.lock"], self.d))  # fmt: skip
        self.tree = tree
        self.policy["platform_releases"] = [{"version": v, "tree_digest": tree, "require_acceptance": True,
                                             "archive_sha256": self.psha, "source_revision": "c" * 40}]  # fmt: skip

    def platform_doc(self, files, *, gh=None):
        att = self.TV.fake_gh(self.psha, "1.0.0")

        def both(argv):
            return (gh or self.pgh)(argv) if argv[:2] == ["gh", "api"] else att(argv)

        return self.TV.V.verify(self.arc, self.pexp, self.ppolicy, gh=both, authorizations=files, now=NOW)

    def platform_record(self, **kw):
        rec = self.TA.record(self.psha)
        rec["decided_by"]["identity_assertion"]["login"] = self.TA.OWNER
        f = self.d / "platform-auth.json"
        raw = json.dumps(rec, indent=2).encode()
        f.write_bytes(raw)
        self.pgh.sign(
            "authorizations/auth-1.json", raw, **({"author": self.TA.OWNER, "committer": self.TA.OWNER} | kw)
        )
        return f

    def run_pa(self, pdoc, auths=None):
        auths = [self.good_auth()] if auths is None else auths
        return self.run_v(auths, platform_acceptance=pdoc)

    def test_accepted_platform_and_authentic_application_approval(self):
        pdoc = self.platform_doc([self.platform_record()])
        self.assertEqual(pdoc["acceptance"]["state"], "accepted")
        doc = self.run_pa(pdoc)
        self.assertEqual(self.state(doc), "approved", doc["checks"])
        self.assertEqual(doc["platform_acceptance"]["state"], "accepted")
        self.assertEqual(
            doc["approval"]["confers"], ["application-release-approval"]
        )  # not platform-baseline

    def test_unaccepted_platform_blocks_even_a_valid_application_approval(self):
        doc = self.run_pa(self.platform_doc([]))
        self.assertEqual(self.state(doc), "failed")
        self.assertIn("platform-acceptance", self.failed(doc))

    def test_no_platform_verification_at_all(self):
        doc = self.run_pa(None)
        self.assertEqual(self.state(doc), "failed")
        self.assertIn("platform-acceptance", self.failed(doc))

    def test_unsigned_platform_acceptance_does_not_count(self):
        doc = self.run_pa(self.platform_doc([self.platform_record(verified=False)]))
        self.assertIn("platform-acceptance", self.failed(doc))

    def test_acceptance_of_a_different_archive_does_not_count(self):
        pdoc = self.platform_doc([self.platform_record()])
        pdoc["subject"]["archive_sha256"] = "9" * 64
        self.assertIn("platform-acceptance", self.failed(self.run_pa(pdoc)))

    def test_application_approval_alone_does_not_accept_the_platform(self):
        # the application approver is not in the platform policy: their record cannot accept the platform
        rec = self.TA.record(self.psha)
        rec["decided_by"]["identity_assertion"]["login"] = APPROVER
        f = self.d / "x.json"
        raw = json.dumps(rec).encode()
        f.write_bytes(raw)
        self.pgh.sign("authorizations/auth-1.json", raw, author=APPROVER, committer=APPROVER)
        pdoc = self.platform_doc([f])
        self.assertEqual(pdoc["acceptance"]["state"], "verified-unaccepted")
        self.assertIn("platform-acceptance", self.failed(self.run_pa(pdoc)))

    def test_platform_acceptance_does_not_approve_the_application(self):
        pdoc = self.platform_doc([self.platform_record()])
        doc = self.run_pa(pdoc, auths=[])
        self.assertEqual(self.state(doc), "unapproved")
        # and the platform record, presented as an application approval, binds to the wrong subject
        doc = self.run_pa(pdoc, auths=[self.d / "platform-auth.json"])
        self.assertEqual(self.state(doc), "unapproved")

    # ---- the platform acceptance is a current decision too (read live, not from what was supplied)
    def current_platform(self, supplied=(), *, historical=False, fail=None):
        import types

        att = self.TV.fake_gh(self.psha, "1.0.0")
        self.pgh.fail = fail

        def both(argv):
            return self.pgh(argv) if argv[:2] == ["gh", "api"] else att(argv)

        ns = types.SimpleNamespace(platform_authorization=list(supplied), platform_archive=self.arc,
                                   platform_bundle=None, platform_sbom_bundle=None, platform_environment=None,
                                   platform_continuity=None, historical=historical)  # fmt: skip
        return A.platform_verification(
            V, self.policy["platform_releases"][0], self.psha, ns, self.ppolicy, both, now=NOW
        )

    def platform_revocation(self):
        rec = self.TA.record(self.psha, name="rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        rec["decided_by"]["identity_assertion"]["login"] = self.TA.OWNER
        raw = json.dumps(rec, indent=2).encode()
        self.pgh.sign("authorizations/rev.json", raw, author=self.TA.OWNER, committer=self.TA.OWNER)

    def test_platform_acceptance_in_the_evidence_repository_is_discovered(self):
        self.platform_record()
        pdoc, checks, cur = self.current_platform()  # nothing supplied
        self.assertEqual(pdoc["acceptance"]["state"], "accepted")
        self.assertEqual(checks, [("platform-authorization-currency", True, "")])
        self.assertEqual(cur["head_commit"], self.pgh.commits[-1]["sha"])

    def test_platform_revocation_absent_from_the_supplied_records_is_found(self):
        f = self.platform_record()
        self.platform_revocation()
        pdoc, checks, _ = self.current_platform([f])
        self.assertNotEqual(pdoc["acceptance"]["state"], "accepted")
        doc = self.run_v([self.good_auth()], platform_acceptance=pdoc, extra_checks=checks)
        self.assertEqual(self.state(doc), "failed")
        self.assertIn("platform-acceptance", self.failed(doc))

    def test_platform_historical_inspection_does_not_look_for_the_revocation(self):
        f = self.platform_record()
        self.platform_revocation()
        pdoc, checks, cur = self.current_platform([f], historical=True)
        self.assertEqual(pdoc["acceptance"]["state"], "accepted")  # as of the supplied records only
        self.assertEqual((checks, cur), ([], None))
        out = self.run_v([self.good_auth()], platform_acceptance=pdoc, purpose="historical")
        self.assertEqual(
            self.state(out), "historical-approval"
        )  # and the application result is not `approved`

    def test_platform_evidence_outage_fails_closed(self):
        f = self.platform_record()
        pdoc, checks, _ = self.current_platform([f], fail=lambda ep: True)
        self.assertFalse(checks[0][1])
        doc = self.run_v([self.good_auth()], platform_acceptance=pdoc, extra_checks=checks)
        self.assertEqual(self.state(doc), "failed")
        self.assertIn("platform-authorization-currency", self.failed(doc))

    def test_platform_record_deleted_from_history_fails_closed(self):
        f = self.platform_record()
        self.platform_revocation()
        self.pgh.delete("authorizations/rev.json", author="intruder", committer="intruder")
        _, checks, _ = self.current_platform([f])
        self.assertFalse(checks[0][1])
        self.assertIn("deleted", checks[0][2])

    def test_policy_requiring_acceptance_must_name_the_archive(self):
        pol = copy.deepcopy(self.policy)
        del pol["platform_releases"][0]["archive_sha256"]
        self.assertTrue(A.policy_problems(pol))
        pol["platform_releases"][0]["archive_sha256"] = self.psha
        pol["platform_releases"][0]["require_acceptance"] = False
        self.assertTrue(A.policy_problems(pol))
