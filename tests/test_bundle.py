"""Immutable application-release evidence bundles: build, tamper-evidence, the independent reader, rollback use."""

import contextlib
import io
import json
import os
import unittest

from dev_platform import bundle, cli, records
from dev_platform.errors import ConfigError
from tests.test_app_release_verifier import PV_PATH, PV_SHA, A, Case, approval


class Base(Case):
    def setUp(self):
        super().setUp()
        self.rp = self.w("release.json", self.rel)
        self.resp = self.w("result.json", self.res)
        self.ap = self.good_auth()
        self.out = self.d / "bundle"

    def build(self, **kw):
        args = dict(results=[self.resp], authorizations=[self.ap])
        args.update(kw)
        return bundle.build(self.out, self.rp, **args)


class Build(Base):
    def test_builds_a_read_only_bundle_whose_manifest_digest_is_the_pin(self):
        pin = self.build()
        self.assertEqual(bundle.verify(self.out, pin), [])
        m = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(m["release_sha256"], records.canonical_digest(self.rel))
        self.assertEqual(m["retention"], {"class": "regulated", "until": None})
        self.assertEqual({e["kind"] for e in m["entries"]}, {"release", "result", "authorization"})
        self.assertFalse(os.access(self.out / "release.json", os.W_OK))

    def test_write_once(self):
        self.build()
        with self.assertRaises(ConfigError):
            self.build()

    def test_refuses_an_authorization_about_another_release(self):
        other = dict(self.rel, application={"name": "app", "version": "7"})
        bad = self.w("bad.json", approval(other, name="bad"))
        with self.assertRaises(ConfigError):
            self.build(authorizations=[bad])

    def test_refuses_missing_evidence(self):
        with self.assertRaises(ConfigError):
            self.build(results=[])

    def test_retention_is_the_longest_lived_record(self):
        a = approval(self.rel, name="a2", retention={"class": "extended", "until": "2030-01-01T00:00:00Z"})
        r = bundle.retention_of(
            [a, approval(self.rel, retention={"class": "standard", "until": "2031-01-01T00:00:00Z"})]
        )
        self.assertEqual(r, {"class": "extended", "until": "2031-01-01T00:00:00Z"})
        with self.assertRaises(ConfigError):
            bundle.retention_of([approval(self.rel, retention={"class": "forever", "until": None})])

    def test_chain_to_a_previous_bundle(self):
        first = self.build()
        rv = self.w(
            "rev.json", approval(self.rel, name="rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        )
        self.out = self.d / "bundle2"
        self.build(authorizations=[self.ap, rv], previous=first)
        self.assertEqual(json.loads((self.out / "manifest.json").read_text())["previous"], first)


class Tamper(Base):
    def setUp(self):
        super().setUp()
        self.pin = self.build()

    def writable(self, name):
        p = self.out / name
        p.chmod(0o600)
        return p

    def test_each_tamper_is_detected_by_both_readers(self):
        def edit(name):
            p = self.writable(name)
            p.write_bytes(p.read_bytes() + b" ")

        def extra(_):
            (self.out / "extra.json").write_text("{}")

        def remove(name):
            self.writable(name).unlink()

        for label, fn, name in (
            ("changed release", edit, "release.json"),
            ("changed approval", edit, "authorizations/appr-1.json"),
            ("unlisted file", extra, None),
            (
                "deleted result",
                remove,
                next(p.relative_to(self.out).as_posix() for p in (self.out / "results").glob("*")),
            ),
        ):
            with self.subTest(label):
                fn(name)
                self.assertTrue(bundle.verify(self.out, self.pin), label)
                problems, _ = A.load_bundle(self.out, self.pin)
                self.assertTrue(problems, label)
                # undo for the next case
                self.tearDown_bundle()
                self.pin = self.build()

    def tearDown_bundle(self):
        import shutil

        for p in self.out.rglob("*"):
            p.chmod(0o700)
        shutil.rmtree(self.out)

    def test_wrong_pin_and_unreadable_manifest(self):
        self.assertTrue(bundle.verify(self.out, "0" * 64))
        self.assertTrue(A.load_bundle(self.out, "0" * 64)[0])
        self.assertTrue(A.load_bundle(self.d / "nowhere", self.pin)[0])

    def test_symlink_is_not_a_file(self):
        p = self.writable("release.json")
        p.unlink()
        p.symlink_to(self.rp)
        self.assertTrue(bundle.verify(self.out, self.pin))
        self.assertTrue(A.load_bundle(self.out, self.pin)[0])

    def test_path_traversal_in_manifest(self):
        m = json.loads((self.out / "manifest.json").read_text())
        m["entries"][0]["path"] = "../release.json"
        self.writable("manifest.json").write_text(json.dumps(m))
        import hashlib

        pin = hashlib.sha256((self.out / "manifest.json").read_bytes()).hexdigest()
        self.assertTrue(A.load_bundle(self.out, pin)[0])


class IndependentReader(Base):
    def run_main(self, *extra):
        argv = [
            "--bundle", str(self.out), "--policy", str(self.w("policy.json", self.policy)),
            "--platform-verifier", str(PV_PATH), "--platform-verifier-sha256", PV_SHA,
            "--mode", "select", *extra,
        ]  # fmt: skip
        with contextlib.redirect_stdout(io.StringIO()):
            return A.main([*argv, "--out", str(self.d / "v.json")]), json.loads(
                (self.d / "v.json").read_text()
            )

    def test_intact_bundle_without_approval_is_unapproved_not_failed(self):
        pin = self.build(authorizations=[])
        code, rec = self.run_main("--manifest-sha256", pin)
        self.assertEqual((code, rec["approval"]["state"]), (3, "unapproved"))
        self.assertIn("evidence-bundle", {c["id"] for c in rec["checks"]})

    def test_modified_bundle_fails_and_nothing_from_it_is_used(self):
        pin = self.build()
        p = self.out / "authorizations" / "appr-1.json"
        p.chmod(0o600)
        p.write_text("{}")
        code, rec = self.run_main("--manifest-sha256", pin)
        self.assertEqual((code, rec["approval"]["state"]), (1, "failed"))

    def test_bundle_requires_a_pin(self):
        self.build()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(A.main(["--bundle", str(self.out), "--policy", "p", "--platform-verifier", str(PV_PATH),
                                     "--platform-verifier-sha256", PV_SHA]), 2)  # fmt: skip


class Rollback(Base):
    def select(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["rollback", "select", "--application", "app", "--current", "9.9.9",
                             "--unauthenticated", *extra])  # fmt: skip
        return code, json.loads(out.getvalue()) if out.getvalue().strip() else None

    def test_bundled_release_is_selectable_and_loose_records_are_not(self):
        pin = self.build()
        _, out = self.select("--bundle", f"{self.out}={pin}")
        self.assertEqual([e["version"] for e in out["eligible"]], ["1.0.0"])
        _, out = self.select(
            "--release", str(self.rp), "--result", str(self.resp), "--authorization", str(self.ap)
        )
        self.assertEqual(out["eligible"], [])
        self.assertIn("not immutable", out["rejected"][0]["reasons"][0])
        _, out = self.select("--allow-unbundled", "--release", str(self.rp), "--result", str(self.resp),
                                "--authorization", str(self.ap))  # fmt: skip
        self.assertEqual(len(out["eligible"]), 1)

    def test_a_tampered_bundle_aborts_selection(self):
        pin = self.build()
        p = self.out / "release.json"
        p.chmod(0o600)
        p.write_text(p.read_text() + " ")
        code, out = self.select("--bundle", f"{self.out}={pin}")
        self.assertNotEqual(code, 0)
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
