"""github-environment-approval: a record is authentic only if the pinned approval workflow attested exactly its bytes.

The provider remains in the verifier's registry for application-release approvals (ADR 0019); platform releases
no longer read approval records (ADR 0024). `gh` is faked at the attestation boundary; the provider is the real one.
"""

import hashlib
import json
import unittest
from pathlib import Path

from tests.legacy_platform import OTHER, OWNER, REPO, record
from tests.test_verify_release import V

PROVIDER = "github-environment-approval"
WORKFLOW = ".github/workflows/approve.yml"
AUTH_POLICY = {
    "providers": [PROVIDER],
    "evidence_repo": REPO,
    "evidence_ref": "main",
    "environment_approval": {"repo": REPO, "workflow": WORKFLOW, "ref": "refs/heads/main"},
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
        self.attested: dict[str, dict] = {}  # sha256 of record bytes -> certificate

    def put(self, doc=None, *, attest=True, **certover):
        doc = doc or self.rec()
        raw = json.dumps(doc, indent=2).encode()
        if attest:
            self.attested[hashlib.sha256(raw).hexdigest()] = cert(**certover)
        return doc, raw

    def rec(self, **over):
        doc = record("a" * 64, **over)
        doc["decided_by"]["identity_assertion"]["provider"] = PROVIDER
        return doc

    def gh(self, argv):
        assert argv[:3] == ["gh", "attestation", "verify"], argv
        sha = hashlib.sha256(Path(argv[3]).read_bytes()).hexdigest()
        c = self.attested.get(sha)
        if c is None:
            return 1, "", "no attestations found"
        stmt = {"predicateType": V.SLSA, "subject": [{"digest": {"sha256": sha}}]}
        return (
            0,
            json.dumps([{"verificationResult": {"signature": {"certificate": c}, "statement": stmt}}]),
            "",
        )

    def auth(self, doc, raw, policy=AUTH_POLICY, gh=None):
        return V.PROVIDERS[PROVIDER](doc, raw, policy, gh or self.gh)

    def test_attested_record_names_the_approver(self):
        login, ev = self.auth(*self.put())
        self.assertEqual(login, OWNER)
        self.assertEqual((ev["workflow"], ev["ref"]), (WORKFLOW, "refs/heads/main"))

    def test_record_without_attestation_is_refused(self):
        with self.assertRaisesRegex(ValueError, "no valid attestation"):
            self.auth(*self.put(attest=False))

    def test_edited_record_loses_its_attestation(self):
        doc, _raw = self.put()
        edited = json.dumps(dict(doc, basis={"kind": "x", "reference": "y"})).encode()
        with self.assertRaises(ValueError):
            self.auth(doc, edited)

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
            with self.assertRaisesRegex(ValueError, "does not match", msg=str(over)):
                self.auth(*self.put(**over))

    def test_login_is_whatever_the_attested_record_says_authority_is_the_callers(self):
        doc = self.rec()
        doc["decided_by"]["identity_assertion"]["login"] = OTHER
        self.assertEqual(self.auth(*self.put(doc))[0], OTHER)

    def test_policy_without_the_pinned_workflow_authenticates_nothing(self):
        pol = {k: v for k, v in AUTH_POLICY.items() if k != "environment_approval"}
        with self.assertRaisesRegex(ValueError, "environment_approval"):
            self.auth(*self.put(), policy=pol)

    def test_attestation_service_failure_fails_closed(self):
        with self.assertRaises(ValueError):
            self.auth(*self.put(), gh=lambda argv: (1, "", "HTTP 502"))


if __name__ == "__main__":
    unittest.main()
