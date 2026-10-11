"""The authorization trust boundary: nothing but an authenticated, authorized, bound, in-force approval
produces `accepted`, and no other path (installer, previous records, policy switches) can.

GitHub is faked at the `gh api` boundary; the verifier code under test is the real one.
"""

import base64
import json
import re
import unittest
from datetime import UTC, datetime

from tests.helpers import ROOT, tmpdir
from tests.test_install_release import IR
from tests.test_verify_release import POLICY as BASE_POLICY
from tests.test_verify_release import V, build_candidate, fake_gh

OWNER = "owner-login"
OTHER = "someone-else"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
REPO = "syncom-systems/dev-platform"

POLICY = {
    **BASE_POLICY,
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
            return (
                0,
                json.dumps(
                    [
                        {k: v for k, v in c.items() if k != "_content"}
                        for c in self.history.get(m.group(2), [])
                    ]
                ),
                "",
            )
        m = re.search(r"/contents/([^?]+)\?ref=(\w+)", ep)
        if m:
            for c in self.history.get(m.group(1), []):
                if c["sha"] == m.group(2):
                    return 0, json.dumps({"content": base64.b64encode(c["_content"]).decode()}), ""
        return 1, "", "not found"


class Boundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._keep = []

    def setUp(self):
        self.arc, self.sha = build_candidate(self, "1.0.0")
        self.gh = Github()
        self.exp = {
            "version": "1.0.0",
            "source_revision": "c" * 40,
            "archive_sha256": self.sha,
            "ref": "refs/tags/v1.0.0",
        }

    def put(self, doc, *, sign=True, **kw):
        """Write the record to disk; optionally register a signed commit for it."""
        d = tmpdir(self)
        name = doc["id"]
        f = d / f"{name}.json"
        raw = json.dumps(doc, indent=2).encode()
        f.write_bytes(raw)
        if sign:
            self.gh.sign(f"authorizations/{name}.json", raw, **kw)
        return f

    def verify(self, files, policy=POLICY, now=NOW, gh=None):
        att = fake_gh(self.sha, "1.0.0")

        def both(argv):
            return (gh or self.gh)(argv) if argv[:2] == ["gh", "api"] else att(argv)

        return V.verify(self.arc, self.exp, policy, gh=both, authorizations=files, now=now)

    def state(self, files, **kw):
        doc = self.verify(files, **kw)
        return doc["acceptance"]["state"], doc

    def assertNotAccepted(self, files, msg=None, **kw):
        st, doc = self.state(files, **kw)
        self.assertEqual(st, "verified-unaccepted", msg)
        return doc["acceptance"]["authorization_evidence"]

    # --- the one path to accepted -------------------------------------------------------------
    def test_authenticated_authorized_bound_approval_is_accepted(self):
        st, doc = self.state([self.put(record(self.sha))])
        self.assertEqual(st, "accepted")
        a = doc["acceptance"]
        self.assertEqual(a["confers"], ["platform-baseline"])
        self.assertTrue(any("certification" in x for x in a["not_conferred"]))
        self.assertTrue(any("migration" in x for x in a["not_conferred"]))

    # --- authenticity -------------------------------------------------------------------------
    def test_unsigned_record_is_not_accepted(self):
        ev = self.assertNotAccepted([self.put(record(self.sha), verified=False)])
        self.assertIn("not a validly signed", ev[0]["problems"][0])

    def test_record_never_committed_is_not_accepted(self):
        self.assertNotAccepted([self.put(record(self.sha), sign=False)])

    def test_invented_or_unsupported_providers_fail_closed(self):
        for prov in ("github-oidc", "acme-sso", "git-commit-author", "git-config", "", None):
            doc = record(self.sha)
            doc["decided_by"]["identity_assertion"] = {"provider": prov, "reference": OWNER, "login": OWNER}
            ev = self.assertNotAccepted([self.put(doc)], prov)
            self.assertIn("not supported", ev[0]["problems"][0], prov)

    def test_provider_in_registry_but_disabled_by_policy(self):
        pol = {**POLICY, "authorization": {**POLICY["authorization"], "providers": []}}
        self.assertNotAccepted([self.put(record(self.sha))], policy=pol)

    def test_committer_web_flow_or_other_author_is_refused(self):
        for kw in ({"committer": "web-flow"}, {"author": OTHER}, {"author": None}):
            self.setUp()
            self.assertNotAccepted([self.put(record(self.sha), **kw)], str(kw))

    def test_any_unsigned_or_foreign_commit_in_the_history_taints_the_record(self):
        doc = record(self.sha)
        f = self.put(doc, verified=False, author=OTHER, committer=OTHER)
        self.gh.sign("authorizations/auth-1.json", f.read_bytes())  # later, valid commit by the owner
        self.assertNotAccepted([f])

    def test_modified_after_signing(self):
        doc = record(self.sha)
        f = self.put(doc)
        edited = dict(doc, scope={"confers": ["platform-baseline"]}, basis={"kind": "x", "reference": "y"})
        f.write_text(json.dumps(edited))
        ev = self.assertNotAccepted([f])
        self.assertIn("modified after signing", ev[0]["problems"][0])

    def test_unreadable_or_malformed_record(self):
        d = tmpdir(self)
        f = d / "x.json"
        f.write_text("{not json")
        self.assertNotAccepted([f])
        f.write_text("[]")
        self.assertNotAccepted([f])
        self.assertNotAccepted([d / "missing.json"])

    def test_github_unavailable_fails_closed(self):
        f = self.put(record(self.sha))
        self.assertNotAccepted([f], gh=lambda argv: (1, "", "network down"))

    # --- authority ----------------------------------------------------------------------------
    def test_valid_signature_from_unauthorized_identity(self):
        doc = record(self.sha)
        doc["decided_by"]["identity_assertion"]["login"] = OTHER
        ev = self.assertNotAccepted([self.put(doc, author=OTHER, committer=OTHER)])
        self.assertIn("not an approver", ev[0]["problems"][0])

    def test_identity_in_record_must_match_the_signer(self):
        doc = record(self.sha)  # claims OWNER, but a different account signed
        self.assertNotAccepted([self.put(doc, author=OTHER, committer=OTHER)])

    def test_approver_without_authority_over_platform_releases(self):
        appr = dict(POLICY["authorization"]["approvers"][0], may_approve=[])
        pol = {**POLICY, "authorization": {**POLICY["authorization"], "approvers": [appr]}}
        self.assertNotAccepted([self.put(record(self.sha))], policy=pol)

    def test_empty_approver_registry_accepts_nothing(self):
        pol = {**POLICY, "authorization": {**POLICY["authorization"], "approvers": []}}
        self.assertNotAccepted([self.put(record(self.sha))], policy=pol)

    def test_policy_without_authorization_section_accepts_nothing(self):
        pol = {k: v for k, v in POLICY.items() if k != "authorization"}
        self.assertNotAccepted([self.put(record(self.sha))], policy=pol)

    def test_policy_cannot_waive_authorization(self):
        pol = {**POLICY, "stable_requires_authorization": False}
        st, doc = self.state([], policy=pol)
        self.assertEqual(st, "failed")
        self.assertIn(
            "policy-requires-authorization", {c["id"] for c in doc["checks"] if c["status"] == "failed"}
        )
        st, _ = self.state([self.put(record(self.sha))], policy=pol)
        self.assertEqual(st, "failed")

    # --- binding ------------------------------------------------------------------------------
    def test_wrong_digest_wrong_kind(self):
        for name, over in {
            "other digest": {"subject": {"kind": "platform-release", "digest": "f" * 64}},
            "other kind": {"subject": {"kind": "application-release", "digest": self.sha}},
            "no digest": {"subject": {"kind": "platform-release"}},
        }.items():
            self.assertNotAccepted([self.put(record(self.sha, **over))], name)

    def test_approval_for_one_release_does_not_accept_another(self):
        _arc2, sha2 = build_candidate(self, "1.0.1")
        f = self.put(record(sha2))
        self.assertNotAccepted([f])

    # --- scope --------------------------------------------------------------------------------
    def test_missing_or_invalid_scope(self):
        base = record(self.sha)
        del base["scope"]
        self.assertNotAccepted([self.put(base)], "missing")
        for name, scope in {
            "empty": {"confers": []},
            "no confers": {},
            "not an object": "platform-baseline",
            "certification": {"confers": ["platform-baseline", "certification"]},
            "migration": {"confers": ["consumer-migration"]},
            "qualification": {"confers": ["qualification-extension"]},
            "string": {"confers": "platform-baseline"},
        }.items():
            self.setUp()
            ev = self.assertNotAccepted([self.put(record(self.sha, scope=scope))], name)
            self.assertIn("scope", ev[0]["problems"][0], name)

    def test_scope_cannot_exceed_the_approvers_authority(self):
        appr = dict(POLICY["authorization"]["approvers"][0], may_confer=[])
        pol = {**POLICY, "authorization": {**POLICY["authorization"], "approvers": [appr]}}
        self.assertNotAccepted([self.put(record(self.sha))], policy=pol)

    # --- validity, supersession, revocation -----------------------------------------------------
    def test_validity_window_and_future_dating(self):
        for name, over in {
            "future": {"decided_at": "2026-10-13T00:00:00Z"},
            "expired": {"validity": {"not_after": "2026-10-12T11:00:00Z"}},
            "not yet": {"validity": {"not_before": "2026-10-12T13:00:00Z"}},
            "bad timestamp": {"decided_at": "yesterday"},
        }.items():
            self.setUp()
            self.assertNotAccepted([self.put(record(self.sha, **over))], name)

    def test_revocation_by_an_authorized_approver(self):
        a = self.put(record(self.sha))
        r = self.put(record(self.sha, "rev-1", decision="revoked", decided_at="2026-10-10T11:00:00Z"))
        self.assertNotAccepted([a, r])
        self.assertEqual(self.state([a])[0], "accepted")

    def test_rejection_after_approval_blocks_and_approval_after_rejection_wins(self):
        a = self.put(record(self.sha))
        rej = self.put(record(self.sha, "rej-1", decision="rejected", decided_at="2026-10-10T11:00:00Z"))
        self.assertNotAccepted([a, rej])
        a2 = self.put(record(self.sha, "auth-2", decided_at="2026-10-10T11:30:00Z"))
        self.assertEqual(self.state([a, rej, a2])[0], "accepted")

    def test_superseded_approval_no_longer_counts(self):
        a = self.put(record(self.sha))
        rev = self.put(
            record(
                self.sha,
                "rev-1",
                decision="revoked",
                supersedes=["auth-1"],
                decided_at="2026-10-10T11:00:00Z",
            )
        )
        self.assertNotAccepted([a, rev])
        # supersession cannot be used to resurrect: a superseded revocation drops out, approval returns
        undo = self.put(record(self.sha, "undo", supersedes=["rev-1"], decided_at="2026-10-10T11:30:00Z"))
        self.assertEqual(self.state([a, rev, undo])[0], "accepted")

    def test_unauthenticated_revocation_has_no_effect_and_unauthenticated_approval_has_no_effect(self):
        a = self.put(record(self.sha))
        junk = self.put(
            record(self.sha, "rev-x", decision="revoked", decided_at="2026-10-10T11:00:00Z"), verified=False
        )
        st, doc = self.state([a, junk])
        self.assertEqual(st, "accepted")
        self.assertEqual(
            {v["id"]: v["status"] for v in doc["acceptance"]["authorization_evidence"]}["rev-x"], "ignored"
        )

    def test_unauthenticated_supersession_cannot_displace_a_real_approval(self):
        a = self.put(record(self.sha))
        junk = self.put(
            record(
                self.sha,
                "sup-x",
                decision="rejected",
                supersedes=["auth-1"],
                decided_at="2026-10-10T11:00:00Z",
            ),
            verified=False,
        )
        self.assertEqual(self.state([a, junk])[0], "accepted")

    def test_equal_timestamps_are_ambiguous_and_fail_closed(self):
        a = self.put(record(self.sha))
        b = self.put(record(self.sha, "rev-1", decision="revoked"))
        self.assertNotAccepted([a, b])

    # --- no bypass ----------------------------------------------------------------------------
    def test_prerelease_cannot_be_accepted(self):
        arc, sha = build_candidate(self, "1.0.0-rc.1")
        exp = {**self.exp, "version": "1.0.0-rc.1", "archive_sha256": sha, "ref": "refs/tags/v1.0.0-rc.1"}
        att = fake_gh(sha, "1.0.0-rc.1")
        doc = V.verify(arc, exp, POLICY, gh=lambda a: att(a), authorizations=[self.put(record(sha))], now=NOW)
        self.assertEqual(doc["acceptance"]["state"], "pre-release")

    def test_installer_does_not_admit_an_unauthenticated_record(self):
        store = tmpdir(self) / "store"
        f = self.put(record(self.sha), verified=False)
        att = fake_gh(self.sha, "1.0.0")
        gh = lambda argv: self.gh(argv) if argv[:2] == ["gh", "api"] else att(argv)
        verifier = IR.types.ModuleType("v")
        verifier.__dict__.update(V.__dict__)
        with self.assertRaises(IR.Refused):
            IR.install(self.arc, store, self.exp, verifier, POLICY, gh=gh, authorizations=[f])
        self.assertFalse(store.exists() and any(store.iterdir()))
        _d, rec = IR.install(
            self.arc, store, self.exp, verifier, POLICY, gh=gh, authorizations=[f], allow_unaccepted=True
        )
        self.assertEqual(rec["acceptance"]["state"], "verified-unaccepted")  # the flag admits, never accepts

    def test_installer_accepts_only_what_the_verifier_accepts(self):
        store = tmpdir(self) / "store"
        f = self.put(record(self.sha))
        att = fake_gh(self.sha, "1.0.0")
        gh = lambda argv: self.gh(argv) if argv[:2] == ["gh", "api"] else att(argv)
        verifier = IR.types.ModuleType("v")
        verifier.__dict__.update(V.__dict__)
        _d, rec = IR.install(self.arc, store, self.exp, verifier, POLICY, gh=gh, authorizations=[f])
        self.assertEqual(rec["acceptance"]["state"], "accepted")

    def test_a_previous_accepted_record_confers_nothing(self):
        store = tmpdir(self) / "store"
        att = fake_gh(self.sha, "1.0.0")
        verifier = IR.types.ModuleType("v")
        verifier.__dict__.update(V.__dict__)
        prev = {"subject": {"version": "0.9.0"}, "acceptance": {"state": "accepted"}, "policy_sha256": "x"}
        with self.assertRaises(IR.Refused):
            IR.install(self.arc, store, self.exp, verifier, POLICY, gh=att, previous_record=prev)

    def test_only_the_verifier_can_produce_accepted(self):
        pat = re.compile(
            r"""(state\s*=\s*['"]accepted['"]|['"]state['"]\s*:\s*['"]accepted['"]|state,\s*reasons\s*=\s*['"]accepted)"""
        )
        offenders = []
        for p in [*ROOT.glob("src/**/*.py"), *ROOT.glob("tools/*.py")]:
            if p.name != "verify_release.py" and pat.search(p.read_text()):
                offenders.append(str(p.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_workflow_cannot_publish_accepted(self):
        wf = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertNotIn("--authorization", wf)

    def test_real_policy_is_well_formed_and_invents_no_approver(self):
        pol = json.loads((ROOT / "trust" / "policy.json").read_text())
        a = pol["authorization"]
        self.assertEqual(a["providers"], ["github-signed-commit"])
        self.assertIs(pol["stable_requires_authorization"], True)
        for ap in a["approvers"]:
            self.assertEqual(ap["provider"], "github-signed-commit")
            self.assertTrue(set(ap["may_confer"]) <= V.CONFERABLE_CLAIMS)


if __name__ == "__main__":
    unittest.main()
