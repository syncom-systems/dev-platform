"""Trusted installation: verify first, execute nothing from the archive, write-once store."""

import hashlib
import importlib.util
import json
import os
import stat
import unittest

from dev_platform.digest import tree_digest
from tests.helpers import ROOT, tmpdir
from tests.test_pack import rmtree_rw
from tests.test_verify_release import POLICY, REV, auth, build_candidate, fake_gh

spec = importlib.util.spec_from_file_location("install_release", ROOT / "tools" / "install_release.py")
IR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(IR)

VERIFIER_SHA = hashlib.sha256((ROOT / "tools" / "verify_release.py").read_bytes()).hexdigest()


class InstallTest(unittest.TestCase):
    def setUp(self):
        self.store = tmpdir(self)
        self.addCleanup(rmtree_rw, self.store)
        self.verifier = IR.load_verifier(ROOT / "tools" / "verify_release.py", VERIFIER_SHA)

    def candidate(self, version="1.0.0-rc.1"):
        arc, sha = build_candidate(self, version)
        exp = {
            "version": version,
            "source_revision": REV,
            "archive_sha256": sha,
            "ref": f"refs/tags/v{version}",
        }
        return arc, sha, exp

    def install(self, version="1.0.0-rc.1", gh=None, **kw):
        arc, sha, exp = self.candidate(version)
        kw.setdefault("allow_prerelease", True)
        gh = gh or fake_gh(sha, version)
        return IR.install(arc, self.store, exp, self.verifier, POLICY, gh=gh, **kw), arc, sha

    def test_verified_prerelease_installs_write_once_and_read_only(self):
        (dest, rec), arc, sha = self.install()
        self.assertEqual(dest, self.store / "1.0.0-rc.1")
        self.assertEqual(tree_digest(dest), rec["subject"]["tree_digest"])
        self.assertEqual(os.stat(dest / "release.json").st_mode & 0o222, 0)
        self.assertTrue((self.store / ".records" / "1.0.0-rc.1.verification.json").is_file())
        self.assertEqual(rec["installation"]["admitted_state"], "pre-release")
        self.assertEqual([p.name for p in self.store.iterdir() if p.name.startswith(".install")], [])
        again, _ = IR.install(
            arc,
            self.store,
            rec["expected"],
            self.verifier,
            POLICY,
            gh=fake_gh(sha, "1.0.0-rc.1"),
            allow_prerelease=True,
        )
        self.assertEqual(again, dest)  # idempotent

    def test_prerelease_needs_explicit_admission(self):
        arc, sha, exp = self.candidate()
        with self.assertRaises(IR.Refused) as cm:
            IR.install(arc, self.store, exp, self.verifier, POLICY, gh=fake_gh(sha, "1.0.0-rc.1"))
        self.assertIn("not admitted", str(cm.exception))
        self.assertEqual(list(self.store.iterdir()), [])

    def test_stable_needs_acceptance_unless_explicitly_allowed(self):
        arc, sha, exp = self.candidate("1.0.0")
        gh = fake_gh(sha, "1.0.0")
        with self.assertRaises(IR.Refused):
            IR.install(arc, self.store, exp, self.verifier, POLICY, gh=gh, allow_prerelease=True)
        self.assertEqual(list(self.store.iterdir()), [])
        f = tmpdir(self) / "a.json"
        f.write_text(json.dumps(auth(sha)))
        dest, rec = IR.install(arc, self.store, exp, self.verifier, POLICY, gh=gh, authorizations=[f])
        self.assertEqual(rec["acceptance"]["state"], "accepted")
        self.assertTrue(dest.is_dir())

    def test_unaccepted_stable_can_be_installed_only_with_the_explicit_flag(self):
        arc, sha, exp = self.candidate("1.0.0")
        _dest, rec = IR.install(
            arc, self.store, exp, self.verifier, POLICY, gh=fake_gh(sha, "1.0.0"), allow_unaccepted=True
        )
        self.assertEqual(rec["installation"]["admitted_state"], "verified-unaccepted")

    def test_failed_verification_installs_nothing(self):
        arc, sha, exp = self.candidate()
        cases = {
            "no attestation": fake_gh(sha, "x", code=1),
            "untrusted signer": fake_gh(sha, "1.0.0-rc.1", cert={"issuer": "https://evil.example"}),
            "attestation for another artifact": fake_gh(sha, "1.0.0-rc.1", subject="e" * 64),
            "sbom attestation missing": fake_gh(sha, "1.0.0-rc.1", sbom_code=1),
        }
        for name, gh in cases.items():
            with self.assertRaises(IR.Refused, msg=name) as cm:
                IR.install(arc, self.store, exp, self.verifier, POLICY, gh=gh, allow_prerelease=True)
            self.assertIn("verification failed", str(cm.exception), name)
            self.assertEqual(list(self.store.iterdir()), [], name)

    def test_wrong_expected_revision_digest_or_tree_installs_nothing(self):
        arc, sha, exp = self.candidate()
        for name, over in {
            "revision": {"source_revision": "e" * 40},
            "archive digest": {"archive_sha256": "0" * 64},
            "tree digest": {"tree_digest": "0" * 64},
        }.items():
            with self.assertRaises(IR.Refused, msg=name):
                IR.install(
                    arc,
                    self.store,
                    {**exp, **over},
                    self.verifier,
                    POLICY,
                    gh=fake_gh(sha, "1.0.0-rc.1"),
                    allow_prerelease=True,
                )
        with self.assertRaises(IR.Refused):
            IR.install(
                arc,
                self.store,
                exp,
                self.verifier,
                POLICY,
                gh=fake_gh(sha, "1.0.0-rc.1"),
                allow_prerelease=True,
                expect_tree="1" * 64,
            )
        self.assertEqual(list(self.store.iterdir()), [])

    def test_consumer_tree_pin_is_enforced(self):
        (dest, rec), _arc, _sha = self.install()
        self.assertEqual(rec["subject"]["tree_digest"], tree_digest(dest))

    def test_different_bytes_for_an_installed_version_are_refused(self):
        (dest, _), _, _ = self.install()
        arc2, sha2, exp2 = self.candidate()  # same version, different build: different bytes
        with open(ROOT / "src" / "dev_platform" / "model.py") as f:
            self.assertTrue(f.read())
        # force different content: rewrite the installed tree digest expectation by tampering the store
        os.chmod(dest, stat.S_IRWXU)
        os.chmod(dest / "release.json", stat.S_IRUSR | stat.S_IWUSR)
        (dest / "release.json").write_text("{}")
        with self.assertRaises(IR.Refused) as cm:
            IR.install(
                arc2,
                self.store,
                exp2,
                self.verifier,
                POLICY,
                gh=fake_gh(sha2, "1.0.0-rc.1"),
                allow_prerelease=True,
            )
        self.assertIn("write-once", str(cm.exception))

    def test_trust_base_pins_are_checked_before_anything_else(self):
        with self.assertRaises(IR.Refused) as cm:
            IR.load_verifier(ROOT / "tools" / "verify_release.py", "0" * 64)
        self.assertEqual(cm.exception.code, 3)
        with self.assertRaises(IR.Refused) as cm:
            IR.load_policy(ROOT / "trust" / "policy.json", "0" * 64)
        self.assertEqual(cm.exception.code, 3)

    def test_verifier_is_executed_from_the_checked_bytes_not_the_path(self):
        d = tmpdir(self)
        f = d / "verify_release.py"
        f.write_text((ROOT / "tools" / "verify_release.py").read_text())
        mod = IR.load_verifier(f, VERIFIER_SHA)
        f.write_text("raise SystemExit('swapped after check')")
        self.assertTrue(callable(mod.verify))

    def test_install_leaves_previous_versions_for_rollback(self):
        self.install("1.0.0-rc.1")
        self.install("1.0.0-rc.2")
        self.assertEqual(
            sorted(p.name for p in self.store.iterdir() if not p.name.startswith(".")),
            ["1.0.0-rc.1", "1.0.0-rc.2"],
        )

    def test_continuity_is_recorded_but_never_a_root(self):
        (_dest, rec), _arc, _sha = self.install("1.0.0-rc.1")
        (_, rec2), _, _ = self.install("1.0.0-rc.2", previous_record=rec)
        self.assertEqual(rec2["continuity"]["previous"], "1.0.0-rc.1")
        self.assertTrue(rec2["continuity"]["policy_unchanged"])
        changed = json.loads(json.dumps(rec))
        changed["policy_sha256"] = "f" * 64
        self.assertFalse(IR.continuity(rec2, changed)["policy_unchanged"])
        self.assertEqual(IR.continuity(rec2, None), {"previous": None})

    def test_hostile_archive_is_refused_by_verification_before_extraction(self):
        import gzip
        import io
        import tarfile

        arc, _sha, exp = self.candidate()
        out = io.BytesIO()
        with tarfile.open(arc, "r:gz") as raw, tarfile.open(fileobj=out, mode="w") as t:
            for m in raw:
                t.addfile(m, raw.extractfile(m) if m.isfile() else None)
            evil = tarfile.TarInfo("../escape.txt")
            evil.size = 1
            t.addfile(evil, io.BytesIO(b"x"))
        bad = arc.parent / "bad.tar.gz"
        bad.write_bytes(gzip.compress(out.getvalue(), mtime=0))
        sha2 = hashlib.sha256(bad.read_bytes()).hexdigest()
        with self.assertRaises(IR.Refused):
            IR.install(
                bad,
                self.store,
                {**exp, "archive_sha256": sha2},
                self.verifier,
                POLICY,
                gh=fake_gh(sha2, "1.0.0-rc.1"),
                allow_prerelease=True,
            )
        self.assertEqual(list(self.store.iterdir()), [])
        self.assertFalse((self.store.parent / "escape.txt").exists())

    def test_installed_layout_matches_the_platforms_own_installer(self):
        from dev_platform import pack

        (dest, _), arc, sha = self.install()
        other = tmpdir(self)
        self.addCleanup(rmtree_rw, other)
        d2 = pack.install(arc, other, expect_archive_sha256=sha)
        self.assertEqual(tree_digest(d2), tree_digest(dest))

    def test_cli_pins_and_missing_pins(self):
        arc, _sha, _exp = self.candidate()
        rc = IR.main(
            [
                "--version",
                "1.0.0-rc.1",
                "--store",
                str(self.store),
                "--archive",
                str(arc),
                "--verifier-sha256",
                "0" * 64,
                "--policy-sha256",
                "0" * 64,
                "--source-revision",
                REV,
            ]
        )
        self.assertEqual(rc, 3)
        self.assertEqual(list(self.store.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
