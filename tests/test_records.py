import json
import unittest

from dev_platform import records as R
from tests.helpers import tmpdir

H = "a" * 64


def app_release(**over):
    d = {
        "schema": R.APP_RELEASE,
        "application": {"name": "pv", "version": "2.0.0"},
        "source": {"uri": "https://example/repo", "revision": "abc"},
        "dependencies": {"resolution_digest": H},
        "platform": {
            "release_version": "1.0.0",
            "release_tree_digest": H,
            "profile": "p",
            "toolchain_identity_digest": H,
        },
        "artifacts": [{"name": "image", "sha256": H}],
        "evidence": [{"kind": "result", "sha256": H}],
        "authorizations": [{"record_sha256": H}],
    }
    d.update(over)
    return d


def auth(**over):
    d = {
        "schema": R.AUTHORIZATION,
        "id": "a1",
        "subject": {"kind": "application-release", "digest": H},
        "decision": "approved",
        "decided_by": {
            "id": "u1",
            "role": "qa-approver",
            "identity_assertion": {"provider": "github-signed-commit", "reference": "sub-123"},
        },
        "basis": {"kind": "change-ticket", "reference": "CHG-42"},
        "decided_at": "2026-10-10T12:00:00Z",
        "retention": {"class": "regulated", "until": None},
    }
    d.update(over)
    return d


class AppReleaseTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(R.validate_app_release(app_release()), [])

    def test_requires_every_provenance_link(self):
        for key in ("source", "dependencies", "platform", "artifacts", "evidence"):
            self.assertTrue(
                R.validate_app_release(
                    app_release(**{key: {} if key not in ("artifacts", "evidence") else []})
                ),
                key,
            )

    def test_digest_format_enforced(self):
        bad = app_release(artifacts=[{"name": "i", "sha256": "xyz"}])
        self.assertTrue(any("artifacts[0].sha256" in p for p in R.validate_app_release(bad)))


class AuthorizationTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(R.validate_authorization(auth()), [])

    def test_git_authorship_is_not_approval(self):
        bad = auth()
        bad["decided_by"]["identity_assertion"] = {"provider": "git-commit-author", "reference": "a@b"}
        self.assertTrue(any("not a supported provider" in p for p in R.validate_authorization(bad)))
        bad["decided_by"].pop("identity_assertion")
        self.assertTrue(any("identity_assertion" in p for p in R.validate_authorization(bad)))

    def test_timestamps_must_be_utc_rfc3339(self):
        self.assertTrue(R.validate_authorization(auth(decided_at="2026-10-10 12:00")))
        self.assertTrue(R.validate_authorization(auth(decided_at="2026-10-10T12:00:00+02:00")))

    def test_retention_is_explicit(self):
        bad = auth()
        bad["retention"] = {"class": "x"}
        self.assertTrue(R.validate_authorization(bad))

    def test_supersession_and_revocation(self):
        a1 = auth()
        self.assertEqual(R.effective_decision([a1], H)["id"], "a1")
        revoke = auth(id="a2", decision="revoked", supersedes=["a1"], decided_at="2026-10-11T00:00:00Z")
        self.assertIsNone(R.effective_decision([a1, revoke], H))
        reapprove = auth(id="a3", supersedes=["a2"], decided_at="2026-10-12T00:00:00Z")
        self.assertEqual(R.effective_decision([a1, revoke, reapprove], H)["id"], "a3")
        self.assertIsNone(R.effective_decision([a1], "b" * 64))  # other subject


class AdvisoryTest(unittest.TestCase):
    def test_affected_releases_and_consumers(self):
        sbom = {"components": [{"name": "ruff", "version": "0.17.0"}]}
        rels = {"1.0.0": {"sbom_doc": sbom}, "1.0.1": {"sbom_doc": {"components": []}}}
        adv = {
            "schema": R.ADVISORY,
            "id": "ADV-1",
            "summary": "s",
            "severity": "high",
            "affected": [{"component": "ruff", "versions": ["0.17.0"]}],
        }
        self.assertEqual(R.validate_advisory(adv), [])
        self.assertEqual(R.releases_affected(adv, rels), {"1.0.0": ["ruff@0.17.0"]})
        d = tmpdir(self)
        (d / "a.json").write_text(json.dumps(app_release()))
        (d / "c.toml").write_text('[platform]\nversion = "1.0.1"\n')
        self.assertEqual(R.consumer_release(d / "a.json"), "1.0.0")
        self.assertEqual(R.consumer_release(d / "c.toml"), "1.0.1")

    def test_platform_version_itself_can_be_affected(self):
        adv = {"affected": [{"component": "dev-platform", "versions": ["1.0.0"]}]}
        self.assertEqual(R.releases_affected(adv, {"1.0.0": {}}), {"1.0.0": ["dev-platform@1.0.0"]})


if __name__ == "__main__":
    unittest.main()
