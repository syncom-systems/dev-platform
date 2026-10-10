"""The independent verifier (tools/verify_release.py) against a fake `gh`."""

import importlib.util
import json
import re
import unittest

from dev_platform.digest import tree_digest
from tests.helpers import ROOT, tmpdir
from tests.test_pack import make_release

spec = importlib.util.spec_from_file_location("verify_release", ROOT / "tools" / "verify_release.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)

REV = "c" * 40
POLICY = json.loads((ROOT / "trust" / "policy.json").read_text())
REPO = "syncom-systems/dev-platform"


def good_cert(version, **over):
    c = {
        "issuer": POLICY["oidc_issuer"],
        "sourceRepositoryURI": f"https://github.com/{REPO}",
        "sourceRepositoryDigest": REV,
        "sourceRepositoryRef": f"refs/tags/v{version}",
        "buildSignerURI": f"https://github.com/{REPO}/.github/workflows/release.yml@refs/tags/v{version}",
        "runnerEnvironment": "github-hosted",
    }
    c.update(over)
    return c


def fake_gh(archive_sha, version, *, code=0, cert=None, predicate=V.SLSA, subject=None):
    def run(argv):
        if code:
            return code, "", "verification failed"
        entry = {
            "verificationResult": {
                "signature": {"certificate": cert or good_cert(version)},
                "statement": {
                    "predicateType": predicate,
                    "subject": [{"digest": {"sha256": subject or archive_sha}}],
                },
            }
        }
        return 0, json.dumps([entry]), ""

    return run


def auth(archive_sha, **over):
    d = {
        "schema": "dev-platform.authorization/v1",
        "id": "auth-1",
        "subject": {"kind": "platform-release", "digest": archive_sha},
        "decision": "approved",
        "decided_by": {
            "id": "owner",
            "role": "owner",
            "identity_assertion": {"provider": "github-oidc", "reference": "matssun"},
        },
        "decided_at": "2026-10-10T12:00:00Z",
    }
    d.update(over)
    return d


class VerifierTest(unittest.TestCase):
    def setUp(self):
        self.version = "1.0.0-rc.1"
        self.d, self.arc, self.sha = make_release(self, self.version)
        # source_revision recorded inside release.json is part of the identity under test
        self.exp = {
            "version": self.version,
            "source_revision": REV,
            "archive_sha256": self.sha,
            "ref": f"refs/tags/v{self.version}",
        }

    def rebuild(self, version, revision=REV):
        import shutil

        from dev_platform import pack, release
        from tests.test_toolchain import MANIFEST

        out = tmpdir(self)
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        tc = out / "tc.json"
        tc.write_text(json.dumps(MANIFEST))
        d = release.build(
            ROOT / "src", tc, out / "r", version, source_revision=revision, strict_version=False
        )
        # the verifier also checks the source __version__ matches
        init = d / "src" / "dev_platform" / "__init__.py"
        init.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', init.read_text()))
        doc = json.loads((d / "release.json").read_text())
        doc["platform"]["source_digest"] = tree_digest(d / "src")
        (d / "release.json").write_text(json.dumps(doc))
        arc = out / "a.tar.gz"
        sha = pack.pack(d, arc)
        return arc, sha

    def run_v(self, version, revision=REV, gh=None, auths=(), policy=POLICY, ref=None):
        arc, sha = self.rebuild(version, revision)
        exp = {
            "version": version,
            "source_revision": REV,
            "archive_sha256": sha,
            "ref": ref or f"refs/tags/v{version}",
        }
        gh = gh or fake_gh(sha, version)
        authfiles = []
        for a in auths:
            f = tmpdir(self) / "a.json"
            f.write_text(json.dumps(a(sha) if callable(a) else a))
            authfiles.append(f)
        return V.verify(arc, exp, policy, gh=gh, authorizations=authfiles), sha, sha

    def failed(self, doc):
        return {c["id"] for c in doc["checks"] if c["status"] == "failed"}

    def test_prerelease_verifies_but_is_never_accepted(self):
        doc, _, _ = self.run_v("1.0.0-rc.1")
        self.assertEqual(self.failed(doc), set())
        self.assertEqual(doc["acceptance"]["state"], "pre-release")

    def test_prerelease_ignores_even_a_valid_authorization(self):
        doc, _, _ = self.run_v("1.0.0-rc.1", auths=[auth])
        self.assertEqual(doc["acceptance"]["state"], "pre-release")

    def test_stable_without_authorization_is_verified_unaccepted(self):
        doc, _, _ = self.run_v("1.0.0")
        self.assertEqual(doc["acceptance"]["state"], "verified-unaccepted")

    def test_stable_with_effective_authorization_is_accepted(self):
        doc, _, _ = self.run_v("1.0.0", auths=[auth])
        self.assertEqual(doc["acceptance"]["state"], "accepted")
        self.assertEqual(doc["acceptance"]["authorization"], "auth-1")

    def test_revoked_wrong_subject_and_git_identity_authorizations_do_not_accept(self):
        revoked = lambda sha: [
            auth(sha),
            auth(
                sha,
                id="auth-2",
                decision="revoked",
                supersedes=["auth-1"],
                decided_at="2026-10-11T00:00:00Z",
            ),
        ]
        for name, a in {
            "wrong subject": lambda sha: auth("f" * 64),
            "rejected": lambda sha: auth(sha, decision="rejected"),
            "git identity": lambda sha: auth(
                sha,
                decided_by={
                    "id": "x",
                    "role": "r",
                    "identity_assertion": {"provider": "git-commit-author", "reference": "a@b"},
                },
            ),
            "wrong kind": lambda sha: auth(sha, subject={"kind": "change", "digest": sha}),
        }.items():
            doc, _, _ = self.run_v("1.0.0", auths=[a])
            self.assertEqual(doc["acceptance"]["state"], "verified-unaccepted", name)
        _arc, sha = self.rebuild("1.0.0")
        f = tmpdir(self) / "r.json"
        f.write_text(json.dumps(revoked(sha)[0]))
        g = tmpdir(self) / "r2.json"
        g.write_text(json.dumps(revoked(sha)[1]))
        self.assertIsNone(V.effective_authorization([f, g], sha))

    def test_valid_signature_from_untrusted_identity_fails(self):
        for name, over in {
            "other repo": {"sourceRepositoryURI": "https://github.com/evil/dev-platform"},
            "other workflow": {
                "buildSignerURI": f"https://github.com/{REPO}/.github/workflows/other.yml@refs/tags/v1.0.0"
            },
            "other revision": {"sourceRepositoryDigest": "d" * 40},
            "other ref": {"sourceRepositoryRef": "refs/heads/main"},
            "self-hosted": {"runnerEnvironment": "self-hosted"},
            "other issuer": {"issuer": "https://evil.example"},
        }.items():
            arc, sha = self.rebuild("1.0.0-rc.1")
            doc = V.verify(
                arc,
                {**self.exp, "archive_sha256": sha},
                POLICY,
                gh=fake_gh(sha, "1.0.0-rc.1", cert=good_cert("1.0.0-rc.1", **over)),
            )
            self.assertEqual(doc["acceptance"]["state"], "failed", name)
            self.assertIn("attestation-matches-policy", self.failed(doc), name)

    def test_attestation_for_a_different_artifact_fails(self):
        doc, _, _ = self.run_v("1.0.0-rc.1", gh=fake_gh("a" * 64, "1.0.0-rc.1", subject="e" * 64))
        self.assertEqual(doc["acceptance"]["state"], "failed")

    def test_wrong_predicate_type_fails(self):
        arc, sha = self.rebuild("1.0.0-rc.1")
        doc = V.verify(
            arc,
            {**self.exp, "archive_sha256": sha},
            POLICY,
            gh=fake_gh(sha, "1.0.0-rc.1", predicate="https://example/other"),
        )
        self.assertEqual(doc["acceptance"]["state"], "failed")

    def test_gh_failure_or_missing_gh_fails_closed(self):
        arc, sha = self.rebuild("1.0.0-rc.1")
        for gh in (fake_gh(sha, "x", code=1), lambda argv: (127, "", "gh not found")):
            doc = V.verify(arc, {**self.exp, "archive_sha256": sha}, POLICY, gh=gh)
            self.assertEqual(doc["acceptance"]["state"], "failed")
            self.assertIn("attestation-signature", self.failed(doc))

    def test_expectation_mismatches_fail(self):
        arc, sha = self.rebuild("1.0.0-rc.1")
        base = {**self.exp, "archive_sha256": sha}
        gh = fake_gh(sha, "1.0.0-rc.1")
        cases = {
            "archive-digest": {"archive_sha256": "0" * 64},
            "version-binding": {"version": "1.0.1-rc.1"},
            "source-revision": {"source_revision": "e" * 40},
            "tree-digest": {"tree_digest": "0" * 64},
        }
        for failing, over in cases.items():
            doc = V.verify(arc, {**base, **over}, POLICY, gh=gh)
            self.assertIn(failing, self.failed(doc), failing)
            self.assertEqual(doc["acceptance"]["state"], "failed")

    def test_ref_not_allowed_by_policy(self):
        doc, _, _ = self.run_v("1.0.0-rc.1", ref="refs/heads/main")
        self.assertIn("policy-allows-ref", self.failed(doc))

    def test_empty_policy_fails_closed(self):
        doc, _, _ = self.run_v("1.0.0-rc.1", policy={**POLICY, "signers": []})
        self.assertEqual(doc["acceptance"]["state"], "failed")

    def test_tampered_archive_content(self):
        import gzip
        import io
        import tarfile

        arc, sha = self.rebuild("1.0.0-rc.1")
        # rewrite one file inside the archive, keeping a valid tar: digest and source checks must catch it
        out = io.BytesIO()
        with tarfile.open(arc, "r:gz") as raw, tarfile.open(fileobj=out, mode="w") as t:
            for m in raw:
                data = raw.extractfile(m).read() if m.isfile() else None
                if m.name.endswith("model.py"):
                    data = b"# tampered\n"
                    m.size = len(data)
                t.addfile(m, io.BytesIO(data) if data is not None else None)
        evil = arc.parent / "evil.tar.gz"
        evil.write_bytes(gzip.compress(out.getvalue(), mtime=0))
        doc = V.verify(evil, {**self.exp, "archive_sha256": sha}, POLICY, gh=fake_gh(sha, "1.0.0-rc.1"))
        self.assertTrue({"archive-digest", "source-digest"} <= self.failed(doc))

    def test_independent_tree_digest_agrees_with_platform_implementation(self):
        self.assertEqual(V.tree_digest(self.d), tree_digest(self.d))

    def test_record_is_deterministic_and_versioned(self):
        arc, sha = self.rebuild("1.0.0-rc.1")
        exp = {**self.exp, "archive_sha256": sha}
        a = V.verify(arc, exp, POLICY, gh=fake_gh(sha, "1.0.0-rc.1"))
        b = V.verify(arc, exp, POLICY, gh=fake_gh(sha, "1.0.0-rc.1"))
        self.assertEqual(a, b)
        self.assertEqual(a["schema"], "dev-platform.verification/v1")


if __name__ == "__main__":
    unittest.main()
