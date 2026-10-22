"""The independent verifier (tools/verify_release.py) against a fake `gh`."""

import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path

from dev_platform.digest import tree_digest
from tests.helpers import ROOT, tmpdir
from tests.test_pack import make_release

spec = importlib.util.spec_from_file_location("verify_release", ROOT / "tools" / "verify_release.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)

REV = "c" * 40
SHIPPED_POLICY = json.loads((ROOT / "trust" / "policy.json").read_text())
# Continuity has its own tests (tests/test_continuity.py); the rest exercise other properties.
REAL_POLICY = {k: v for k, v in SHIPPED_POLICY.items() if k != "continuity"}
# Most tests exercise other properties; environment evidence has its own tests below.
POLICY = {**REAL_POLICY, "require_environment_evidence": False}
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


def archive_sbom(path):
    import tarfile

    with tarfile.open(path, "r:gz") as t:
        name = next(m.name for m in t if m.name.endswith("/sbom.cdx.json"))
        return json.loads(t.extractfile(name).read())


def fake_gh(archive_sha, version, *, code=0, cert=None, predicate=None, subject=None, sbom=None, sbom_code=0):
    def run(argv):
        want = argv[argv.index("--predicate-type") + 1]
        if code or (want == V.CYCLONEDX and sbom_code):
            return code or sbom_code, "", "verification failed"
        stmt = {
            "predicateType": predicate or want,
            "subject": [
                {"digest": {"sha256": subject or hashlib.sha256(Path(argv[3]).read_bytes()).hexdigest()}}
            ],
        }
        if want == V.CYCLONEDX:
            stmt["predicate"] = sbom if sbom is not None else archive_sbom(argv[3])
        entry = {
            "verificationResult": {
                "signature": {"certificate": cert or good_cert(version)},
                "statement": stmt,
            }
        }
        return 0, json.dumps([entry]), ""

    return run


def build_candidate(test, version, revision=REV, manifest=None):
    import shutil

    from dev_platform import pack, release

    MANIFEST = manifest or MANIFEST_PLAIN

    out = tmpdir(test)
    test.addCleanup(shutil.rmtree, out, ignore_errors=True)
    tc = out / "tc.json"
    tc.write_text(json.dumps(MANIFEST))
    d = release.build(ROOT / "src", tc, out / "r", version, source_revision=revision, strict_version=False)
    # the verifier also checks the source __version__ matches
    init = d / "src" / "dev_platform" / "__init__.py"
    init.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', init.read_text()))
    doc = json.loads((d / "release.json").read_text())
    doc["platform"]["source_digest"] = tree_digest(d / "src")
    sbom = json.dumps(release.make_sbom(version, doc["platform"]["source_digest"], MANIFEST), indent=2)
    (d / "sbom.cdx.json").write_text(sbom)
    doc["sbom"]["sha256"] = hashlib.sha256(sbom.encode()).hexdigest()
    (d / "release.json").write_text(json.dumps(doc))
    arc = out / "a.tar.gz"
    sha = pack.pack(d, arc)
    return arc, sha


from tests.test_toolchain import MANIFEST as MANIFEST_PLAIN  # noqa: E402


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
        return build_candidate(self, version, revision)

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

    def test_prerelease_verifies_as_a_prerelease(self):
        doc, _, _ = self.run_v("1.0.0-rc.1")
        self.assertEqual(self.failed(doc), set())
        self.assertEqual(doc["acceptance"]["state"], "pre-release")

    def test_prerelease_stays_a_prerelease_whatever_is_supplied(self):
        doc, _, _ = self.run_v("1.0.0-rc.1", auths=[{"anything": "at all"}])
        self.assertEqual(doc["acceptance"]["state"], "pre-release")

    def test_stable_that_passes_every_check_is_verified(self):
        doc, _, _ = self.run_v("1.0.0")
        self.assertEqual(self.failed(doc), set())
        self.assertEqual(doc["acceptance"]["state"], "verified")
        self.assertEqual(doc["checks"][0]["id"], "policy-schema")

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
            self.assertIn("sbom-attestation-matches-policy", self.failed(doc), name)

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

    def test_sbom_attestation_is_verified_and_must_match_the_archive_sbom(self):
        arc, sha = self.rebuild("1.0.0-rc.1")
        exp = {**self.exp, "archive_sha256": sha}
        other = archive_sbom(arc)
        other["components"][0]["version"] = "9.9.9"
        cases = {
            "no sbom attestation": (dict(sbom_code=1), {"sbom-attestation-signature"}),
            "attested sbom differs from archive sbom": (dict(sbom=other), {"sbom-attestation-content"}),
        }
        for name, (kw, ids) in cases.items():
            doc = V.verify(arc, exp, POLICY, gh=fake_gh(sha, "1.0.0-rc.1", **kw))
            self.assertEqual(doc["acceptance"]["state"], "failed", name)
            self.assertTrue(ids <= self.failed(doc), name)

    def test_sbom_must_correspond_to_the_toolchain_manifest_and_artifact(self):
        from tests.test_toolchain import MANIFEST

        sbom = archive_sbom(self.arc)
        self.assertEqual(V.sbom_matches_manifest(sbom, MANIFEST), [])
        bad = json.loads(json.dumps(sbom))
        bad["components"][0]["version"] = "0.0.1"
        self.assertTrue(V.sbom_matches_manifest(bad, MANIFEST))
        extra = json.loads(json.dumps(sbom))
        extra["components"].append({"type": "application", "name": "sneaky", "version": "1"})
        self.assertIn("undeclared", V.sbom_matches_manifest(extra, MANIFEST)[0])

    def test_sbom_closure_pins_and_sources_are_checked_independently(self):
        tc = {
            "schema": "dev-platform.toolchains/v1",
            "profiles": {
                "p": {
                    "tools": {
                        "t": {
                            "version": "1",
                            "probe": {"argv": ["t"], "pattern": "(1)"},
                            "closure": {
                                "kind": "file",
                                "sha256": {"linux-x86_64": "a" * 64},
                                "system_libs": ["libc.so.6"],
                            },
                            "source": {"linux-x86_64": {"url": "https://x/t.tgz", "sha256": "b" * 64}},
                        }
                    }
                }
            },
        }
        from dev_platform import release as R

        sbom = R.make_sbom("1.0.0", "c" * 64, tc)
        self.assertEqual(V.sbom_matches_manifest(sbom, tc), [])
        sbom["components"][0]["properties"][0]["value"] = "f" * 64
        self.assertTrue(V.sbom_matches_manifest(sbom, tc))
        sbom = R.make_sbom("1.0.0", "c" * 64, tc)
        sbom["components"][0]["externalReferences"][0]["hashes"][0]["content"] = "e" * 64
        self.assertTrue(V.sbom_matches_manifest(sbom, tc))

    def env_case(self, **over):
        """A release whose manifest has one closure-pinned tool, plus a matching environment record."""
        digest = "d" * 64
        mf = json.loads(json.dumps(MANIFEST_PLAIN))
        mf["profiles"]["p"]["tools"]["tool"]["closure"] = {
            "kind": "file",
            "sha256": {"linux-x86_64": digest},
            "system_libs": ["libc.so.6"],
        }
        arc, sha = build_candidate(self, "1.0.0-rc.1", manifest=mf)
        env = {
            "profile": "p",
            "platform": "linux-x86_64",
            "conformant": True,
            "assurance": "certifiable",
            "scope": {"hermetic": False, "limitations": ["system libraries trusted by name"]},
            "tools": [
                {
                    "name": "tool",
                    "identity": "closure-verified",
                    "observed": "1.2.3",
                    "closure": {"digest": digest},
                }
            ],
        }
        env.update(over)
        f = tmpdir(self) / "env.json"
        f.write_text(json.dumps(env))
        return arc, sha, f

    def verify_env(self, arc, sha, env_file, policy=REAL_POLICY):
        exp = {**self.exp, "archive_sha256": sha}
        return V.verify(arc, exp, policy, gh=fake_gh(sha, "1.0.0-rc.1"), environment=env_file)

    def test_environment_evidence_must_match_manifest_and_state_its_limits(self):
        arc, sha, f = self.env_case()
        doc = self.verify_env(arc, sha, f)
        self.assertEqual(self.failed(doc), set())
        self.assertEqual(doc["acceptance"]["state"], "pre-release")
        ids = [c["id"] for c in doc["checks"]]
        self.assertIn("environment-evidence", ids)
        self.assertIn("environment-attestation-matches-policy", ids)

    def test_environment_evidence_failures(self):
        cases = {
            "not certifiable": {"assurance": "diagnostic"},
            "claims hermetic": {"scope": {"hermetic": True, "limitations": ["x"]}},
            "no limitations": {"scope": {"hermetic": False, "limitations": []}},
            "unknown profile": {"profile": "other"},
            "wrong closure": {
                "tools": [
                    {
                        "name": "tool",
                        "identity": "closure-verified",
                        "observed": "1.2.3",
                        "closure": {"digest": "e" * 64},
                    }
                ]
            },
            "weak identity": {
                "tools": [
                    {
                        "name": "tool",
                        "identity": "version-only",
                        "observed": "1.2.3",
                        "closure": {"digest": "d" * 64},
                    }
                ]
            },
            "wrong version": {
                "tools": [
                    {
                        "name": "tool",
                        "identity": "closure-verified",
                        "observed": "9",
                        "closure": {"digest": "d" * 64},
                    }
                ]
            },
            "tool set differs": {"tools": []},
        }
        for name, over in cases.items():
            arc, sha, f = self.env_case(**over)
            doc = self.verify_env(arc, sha, f)
            self.assertIn("environment-evidence", self.failed(doc), name)
            self.assertEqual(doc["acceptance"]["state"], "failed", name)

    def test_policy_requiring_evidence_fails_without_it(self):
        arc, sha, _ = self.env_case()
        doc = self.verify_env(arc, sha, None)
        self.assertIn("environment-evidence", self.failed(doc))

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
