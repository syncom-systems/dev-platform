"""github-environment-approval: a record is authentic only if the pinned acceptance workflow attested exactly its bytes.

`gh` is faked at the attestation boundary; the verifier code under test is the real one.
"""

import hashlib
import json
import unittest
from pathlib import Path

from tests.helpers import tmpdir
from tests.test_authorization import NOW, OTHER, OWNER, REPO, record
from tests.test_authorization import POLICY as SIGNED_POLICY
from tests.test_verify_release import V, build_candidate, fake_gh

PROVIDER = "github-environment-approval"
WORKFLOW = ".github/workflows/accept.yml"
POLICY = {
    **SIGNED_POLICY,
    "authorization": {
        "providers": [PROVIDER],
        "evidence_repo": REPO,
        "evidence_ref": "main",
        "environment_approval": {"repo": REPO, "workflow": WORKFLOW, "ref": "refs/heads/main"},
        "approvers": [
            {
                "id": "owner",
                "provider": PROVIDER,
                "login": OWNER,
                "roles": ["owner"],
                "may_approve": ["platform-release"],
                "may_confer": ["platform-baseline"],
            }
        ],
    },
}


def cert(**over):
    c = {
        "issuer": "https://token.actions.githubusercontent.com",
        "sourceRepositoryURI": f"https://github.com/{REPO}",
        "sourceRepositoryRef": "refs/heads/main",
        "sourceRepositoryDigest": "d" * 40,
        "buildSignerURI": f"https://github.com/{REPO}/{WORKFLOW}@refs/heads/main",
        "buildTrigger": "workflow_dispatch",
        "runnerEnvironment": "github-hosted",
        "runInvocationURI": f"https://github.com/{REPO}/actions/runs/1/attempts/1",
    }
    c.update(over)
    return c


class EnvironmentApproval(unittest.TestCase):
    def setUp(self):
        self.arc, self.sha = build_candidate(self, "1.0.0")
        self.exp = {
            "version": "1.0.0",
            "source_revision": "c" * 40,
            "archive_sha256": self.sha,
            "ref": "refs/tags/v1.0.0",
        }
        self.attested: dict[str, dict] = {}  # sha256 of record bytes -> certificate

    def put(self, doc=None, *, attest=True, **certover):
        doc = doc or self.rec()
        f = tmpdir(self) / f"{doc['id']}.json"
        raw = json.dumps(doc, indent=2).encode()
        f.write_bytes(raw)
        if attest:
            self.attested[hashlib.sha256(raw).hexdigest()] = cert(**certover)
        return f

    def rec(self, **over):
        doc = record(self.sha, **over)
        doc["decided_by"]["identity_assertion"]["provider"] = PROVIDER
        return doc

    def gh(self, argv):
        if argv[:3] == ["gh", "attestation", "verify"] and "record.json" in argv[3]:
            sha = hashlib.sha256(Path(argv[3]).read_bytes()).hexdigest()
            c = self.attested.get(sha)
            if c is None:
                return 1, "", "no attestations found"
            stmt = {
                "predicateType": V.SLSA,
                "subject": [{"digest": {"sha256": sha}}],
            }
            entry = {"verificationResult": {"signature": {"certificate": c}, "statement": stmt}}
            return 0, json.dumps([entry]), ""
        return fake_gh(self.sha, "1.0.0")(argv)

    def state(self, files, policy=POLICY):
        doc = V.verify(self.arc, self.exp, policy, gh=self.gh, authorizations=files, now=NOW)
        return doc["acceptance"]["state"], doc

    def test_attested_record_by_the_approver_is_accepted(self):
        st, doc = self.state([self.put()])
        self.assertEqual(st, "accepted")
        self.assertEqual(doc["acceptance"]["confers"], ["platform-baseline"])

    def test_record_without_attestation_is_ignored(self):
        st, doc = self.state([self.put(attest=False)])
        self.assertEqual(st, "verified-unaccepted")
        self.assertIn("no valid attestation", doc["acceptance"]["authorization_evidence"][0]["problems"][0])

    def test_edited_record_loses_its_attestation(self):
        f = self.put()
        d = json.loads(f.read_text())
        d["basis"] = {"kind": "x", "reference": "y"}
        f.write_text(json.dumps(d))
        self.assertEqual(self.state([f])[0], "verified-unaccepted")

    def test_wrong_workflow_ref_trigger_runner_repo_or_issuer(self):
        for over in (
            {"buildSignerURI": f"https://github.com/{REPO}/.github/workflows/other.yml@refs/heads/main"},
            {"sourceRepositoryRef": "refs/heads/feature"},
            {"buildTrigger": "push"},
            {"runnerEnvironment": "self-hosted"},
            {"sourceRepositoryURI": "https://github.com/evil/dev-platform"},
            {"issuer": "https://evil.example"},
        ):
            self.setUp()
            self.assertEqual(self.state([self.put(**over)])[0], "verified-unaccepted", str(over))

    def test_approver_must_be_in_the_policy(self):
        doc = self.rec()
        doc["decided_by"]["identity_assertion"]["login"] = OTHER
        st, doc = self.state([self.put(doc)])
        self.assertEqual(st, "verified-unaccepted")
        self.assertIn("not an approver", doc["acceptance"]["authorization_evidence"][0]["problems"][0])

    def test_policy_without_the_pinned_workflow_or_provider_accepts_nothing(self):
        pol = {**POLICY, "authorization": {**POLICY["authorization"]}}
        del pol["authorization"]["environment_approval"]
        self.assertEqual(self.state([self.put()], pol)[0], "verified-unaccepted")
        pol = {**POLICY, "authorization": {**POLICY["authorization"], "providers": ["github-signed-commit"]}}
        self.assertEqual(self.state([self.put()], pol)[0], "verified-unaccepted")

    def test_revocation_is_attested_too_and_a_later_one_wins(self):
        a = self.rec(id="a")
        r = self.rec(id="r", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        self.assertEqual(self.state([self.put(a), self.put(r)])[0], "verified-unaccepted")

    def test_attestation_service_failure_fails_closed(self):
        f = self.put()
        orig = self.gh
        self.gh = lambda argv: (1, "", "HTTP 502") if "record.json" in argv[3] else orig(argv)
        self.assertEqual(self.state([f])[0], "verified-unaccepted")

    def test_workflow_file_is_manual_only_and_environment_gated(self):
        text = (Path(__file__).resolve().parent.parent / ".github/workflows/accept.yml").read_text()
        self.assertIn("workflow_dispatch:", text)
        self.assertNotIn("pull_request", text)
        self.assertNotIn("\n  push:", text)
        self.assertIn("environment: owner-approval", text)


if __name__ == "__main__":
    unittest.main()
