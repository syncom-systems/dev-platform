"""Release authority after ADR 0024, and the identity providers that remain for application approvals.

A platform release has no approval record: the verifier's state is `verified` (or `pre-release`, `failed`) from the
technical checks alone, whatever records are handed to it, and nothing else in the platform produces it. The
`github-signed-commit` provider is still the authentication library for application-release approvals (ADR 0019),
so its failure modes are tested directly. GitHub is faked at the `gh api` boundary; the code under test is real.
"""

import contextlib
import io
import json
import re
import unittest

from tests.helpers import ROOT, tmpdir
from tests.legacy_platform import NOW, OTHER, OWNER, REPO, Github, record
from tests.test_install_release import IR
from tests.test_verify_release import POLICY, V, build_candidate, fake_gh

__all__ = ["NOW", "OTHER", "OWNER", "REPO", "Github", "record"]  # shared with other tests
AUTH_POLICY = {"providers": ["github-signed-commit"], "evidence_repo": REPO, "evidence_ref": "main"}


class SignedCommitProvider(unittest.TestCase):
    """Authenticity only: who made the record. Authority is the caller's policy, not this function's."""

    def setUp(self):
        self.gh = Github()

    def put(self, doc, *, sign=True, **kw):
        raw = json.dumps(doc, indent=2).encode()
        if sign:
            self.gh.sign(doc["decided_by"]["identity_assertion"]["path"], raw, **kw)
        return raw

    def auth(self, doc, raw, gh=None):
        return V.PROVIDERS["github-signed-commit"](doc, raw, AUTH_POLICY, gh or self.gh)

    def refused(self, doc, raw, contains, gh=None):
        with self.assertRaises(ValueError) as cm:
            self.auth(doc, raw, gh)
        self.assertIn(contains, str(cm.exception))

    def test_signed_by_the_asserted_login(self):
        doc = record("a" * 64)
        login, ev = self.auth(doc, self.put(doc))
        self.assertEqual(login, OWNER)
        self.assertEqual((ev["repo"], ev["ref"], ev["path"]), (REPO, "main", "authorizations/auth-1.json"))

    def test_unsigned_or_never_committed(self):
        doc = record("a" * 64)
        self.refused(doc, self.put(doc, verified=False), "not a validly signed")
        self.gh = Github()
        self.refused(doc, self.put(doc, sign=False), "no commit")

    def test_committer_web_flow_or_another_author(self):
        for kw in ({"committer": "web-flow"}, {"author": OTHER}, {"author": None}):
            self.gh = Github()
            doc = record("a" * 64)
            with self.assertRaises(ValueError, msg=str(kw)):
                self.auth(doc, self.put(doc, **kw))

    def test_any_unsigned_or_foreign_commit_in_the_history_taints_the_record(self):
        doc = record("a" * 64)
        raw = self.put(doc, verified=False, author=OTHER, committer=OTHER)
        self.gh.sign("authorizations/auth-1.json", raw)  # later, a valid commit by the owner
        self.refused(doc, raw, "not a validly signed")

    def test_modified_after_signing(self):
        doc = record("a" * 64)
        self.put(doc)
        edited = json.dumps(dict(doc, basis={"kind": "x", "reference": "y"})).encode()
        self.refused(doc, edited, "modified after signing")

    def test_identity_in_record_must_match_the_signer(self):
        doc = record("a" * 64)  # claims OWNER, but a different account signed
        self.refused(doc, self.put(doc, author=OTHER, committer=OTHER), "is not")

    def test_path_and_login_are_required(self):
        doc = record("a" * 64)
        doc["decided_by"]["identity_assertion"]["path"] = "elsewhere/x.json"
        self.refused(doc, b"{}", "authorizations/<name>.json")
        doc = record("a" * 64)
        doc["decided_by"]["identity_assertion"]["login"] = ""
        self.refused(doc, b"{}", "login required")

    def test_github_unavailable_fails_closed(self):
        doc = record("a" * 64)
        self.refused(doc, self.put(doc), "cannot fetch", gh=lambda argv: (1, "", "network down"))

    def test_registry_is_explicit(self):
        self.assertEqual(set(V.PROVIDERS), {"github-signed-commit", "github-environment-approval"})


class PlatformReleaseHasNoApproval(unittest.TestCase):
    def setUp(self):
        self.arc, self.sha = build_candidate(self, "1.0.0")
        self.exp = {"version": "1.0.0", "source_revision": "c" * 40, "archive_sha256": self.sha,
                    "ref": "refs/tags/v1.0.0"}  # fmt: skip
        self.gh = Github()

    def put(self, doc):
        f = tmpdir(self) / f"{doc['id']}.json"
        raw = json.dumps(doc, indent=2).encode()
        f.write_bytes(raw)
        self.gh.sign(f"authorizations/{doc['id']}.json", raw)
        return f

    def verify(self, files=(), policy=POLICY, arc=None, exp=None, sha=None):
        att = fake_gh(sha or self.sha, (exp or self.exp)["version"])
        both = lambda argv: self.gh(argv) if argv[:2] == ["gh", "api"] else att(argv)
        return V.verify(
            arc or self.arc, exp or self.exp, policy, gh=both, authorizations=list(files), now=NOW
        )

    def test_verified_from_the_technical_checks_alone(self):
        doc = self.verify()
        self.assertEqual(doc["acceptance"]["state"], "verified")
        self.assertNotIn("authorization_evidence", doc["acceptance"])
        self.assertTrue(any("certification" in x for x in doc["acceptance"]["not_conferred"]))

    def test_approval_or_revocation_records_change_nothing(self):
        approved = self.put(record(self.sha))
        revoked = self.put(record(self.sha, "rev-1", decision="revoked", decided_at="2026-10-10T11:00:00Z"))
        for files in ([approved], [revoked], [approved, revoked]):
            self.assertEqual(self.verify(files), self.verify(), files)

    def test_a_failed_check_is_failed_whatever_is_supplied(self):
        exp = {**self.exp, "archive_sha256": "f" * 64}
        doc = self.verify([self.put(record(self.sha))], exp=exp)
        self.assertEqual(doc["acceptance"]["state"], "failed")
        self.assertIn("archive-digest", doc["acceptance"]["reasons"])

    def test_prerelease_versions_stay_prereleases(self):
        arc, sha = build_candidate(self, "1.0.0-rc.1")
        exp = {**self.exp, "version": "1.0.0-rc.1", "archive_sha256": sha, "ref": "refs/tags/v1.0.0-rc.1"}
        self.assertEqual(self.verify(arc=arc, exp=exp, sha=sha)["acceptance"]["state"], "pre-release")

    def test_a_trust_v1_policy_is_refused_not_reinterpreted(self):
        v1 = {**POLICY, "schema": "dev-platform.trust/v1", "stable_requires_authorization": True}
        doc = self.verify(policy=v1)
        self.assertEqual(doc["acceptance"]["state"], "failed")
        self.assertEqual(doc["acceptance"]["reasons"], ["policy-schema"])
        f = tmpdir(self) / "p.json"
        f.write_text(json.dumps(v1))
        argv = [str(self.arc), "--version", "1.0.0", "--source-revision", "c" * 40,
                "--archive-sha256", self.sha, "--policy", str(f)]  # fmt: skip
        self.assertEqual(V.main(argv), 2)

    def test_the_verifier_cli_takes_no_authorization(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            V.main([str(self.arc), "--version", "1.0.0", "--source-revision", "c" * 40,
                    "--archive-sha256", self.sha, "--policy", "p.json", "--authorization", "a.json"])  # fmt: skip

    def installer(self):
        verifier = IR.types.ModuleType("v")
        verifier.__dict__.update(V.__dict__)
        return verifier

    def test_installer_admits_a_verified_release_without_flags(self):
        store = tmpdir(self) / "store"
        _d, rec = IR.install(
            self.arc, store, self.exp, self.installer(), POLICY, gh=fake_gh(self.sha, "1.0.0")
        )
        self.assertEqual(rec["installation"]["admitted_state"], "verified")

    def test_installer_never_admits_a_failed_release_and_a_previous_record_confers_nothing(self):
        store = tmpdir(self) / "store"
        prev = {"subject": {"version": "0.9.0"}, "acceptance": {"state": "accepted"}, "policy_sha256": "x"}
        with self.assertRaises(IR.Refused):
            IR.install(self.arc, store, self.exp, self.installer(), POLICY,
                       gh=fake_gh(self.sha, "1.0.0", code=1), previous_record=prev)  # fmt: skip
        self.assertFalse(store.exists() and any(store.iterdir()))

    def test_only_the_verifier_produces_a_release_state(self):
        pat = re.compile(
            r"""(state\s*=\s*['"](accepted|verified)['"]|['"]state['"]\s*:\s*['"](accepted|verified)['"]"""
            r"""|state,\s*reasons\s*=\s*['"](accepted|verified))"""
        )
        offenders = []
        for p in [*ROOT.glob("src/**/*.py"), *ROOT.glob("tools/*.py")]:
            # lifecycle.py and verify_platform_current.py only *observe* the verifier's state
            if p.name not in (
                "verify_release.py",
                "lifecycle.py",
                "verify_platform_current.py",
            ) and pat.search(p.read_text()):
                offenders.append(str(p.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_no_acceptance_workflow_and_the_release_workflow_reads_no_approval(self):
        self.assertFalse((ROOT / ".github/workflows/accept.yml").exists())
        wf = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertNotIn("--authorization", wf)
        self.assertIn('verified) flag="--latest"', wf)

    def test_real_policy_is_trust_v2_without_an_approval_registry(self):
        pol = json.loads((ROOT / "trust" / "policy.json").read_text())
        self.assertEqual(pol["schema"], "dev-platform.trust/v2")
        self.assertFalse({"authorization", "stable_requires_authorization"} & set(pol))
        schema = json.loads((ROOT / "schemas" / "trust-v2.schema.json").read_text())
        self.assertEqual(set(pol) - set(schema["properties"]), set())
        self.assertTrue(set(schema["required"]) <= set(pol))


if __name__ == "__main__":
    unittest.main()
