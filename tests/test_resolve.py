import json
import unittest
from unittest import mock

from dev_platform import release
from dev_platform import resolve as R
from dev_platform.config import PlatformPin
from dev_platform.digest import tree_digest
from dev_platform.errors import ConfigError, PlatformResolutionError
from tests.helpers import ROOT, tmpdir
from tests.test_toolchain import MANIFEST


class _Cfg:
    def __init__(self, pin):
        self.platform = pin


def make_release(test, version="0.1.0"):
    out = tmpdir(test)
    tc = out / "tc.json"
    tc.write_text(json.dumps(MANIFEST))
    vdir = release.build(ROOT / "src", tc, out / "store", version, strict_version=False)
    return out / "store", vdir


class ResolveTest(unittest.TestCase):
    def test_pinned_resolution_verifies_digest(self):
        store, vdir = make_release(self)
        pin = PlatformPin("0.1.0", tree_digest(vdir), False, "p")
        res = R.resolve(_Cfg(pin), env={R.STORE_ENV: str(store)})
        self.assertEqual((res.mode, res.version, res.digest), ("pinned", "0.1.0", pin.sha256))
        self.assertTrue(res.certifiable)
        self.assertIsNone(res.release)  # the release validates its own record when it runs
        res.dispose()

    def test_verified_bytes_are_the_executed_bytes(self):
        """Closes the verify->exec race: mutating the store after resolution cannot change what runs."""
        store, vdir = make_release(self)
        pin = PlatformPin("0.1.0", tree_digest(vdir), False, "p")
        res = R.resolve(_Cfg(pin), env={R.STORE_ENV: str(store)})
        self.addCleanup(res.dispose)
        (vdir / "src" / "dev_platform" / "model.py").write_text("# swapped after verification\n")
        snap_model = res.root / "dev_platform" / "model.py"
        self.assertNotIn("swapped", snap_model.read_text())
        self.assertEqual(tree_digest(res.root.parent), pin.sha256)  # what runs == what was pinned

    def test_snapshot_is_private_and_disposable(self):
        store, vdir = make_release(self)
        res = R.resolve(
            _Cfg(PlatformPin("0.1.0", tree_digest(vdir), False, "p")), env={R.STORE_ENV: str(store)}
        )
        self.assertEqual(oct(res.cleanup.stat().st_mode & 0o777), "0o700")
        res.dispose()
        self.assertFalse(res.cleanup.exists())

    def test_the_launcher_does_not_validate_a_release_it_has_not_run(self):
        store, vdir = make_release(self, "99.0.0")
        pin = PlatformPin("99.0.0", tree_digest(vdir), False, "p")
        err = ConfigError(["toolchain manifest: profiles.p.bazel: unknown key"])
        with mock.patch.object(R.releases, "load", side_effect=err) as load:
            res = R.resolve(_Cfg(pin), env={R.STORE_ENV: str(store)})
        self.addCleanup(res.dispose)
        load.assert_not_called()  # a manifest newer than this code is the release's to judge
        self.assertEqual((res.mode, res.digest), ("pinned", pin.sha256))
        self.assertIsNone(res.release)

    def test_the_release_itself_validates_its_own_record_when_it_runs(self):
        _store, vdir = make_release(self, "0.0.1")
        pin = PlatformPin("0.0.1", tree_digest(vdir), False, "p")
        env = {R.REEXEC_ENV: "0.0.1"}
        with (
            mock.patch.object(R, "PACKAGE_ROOT", vdir / "src"),
            mock.patch.object(R.releases, "load", side_effect=ConfigError(["bad"])),
            self.assertRaisesRegex(PlatformResolutionError, "invalid release"),
        ):
            R.resolve(_Cfg(pin), env=env)

    def test_an_integrity_failure_is_still_refused_for_a_newer_release(self):
        store, vdir = make_release(self, "99.0.0")
        pin = PlatformPin("99.0.0", tree_digest(vdir), False, "p")
        (vdir / "release.json").write_text("{}")  # no longer the pinned bytes
        with self.assertRaisesRegex(PlatformResolutionError, "integrity failure"):
            R.resolve(_Cfg(pin), env={R.STORE_ENV: str(store)})

    def test_tampered_release_is_rejected(self):
        store, vdir = make_release(self)
        pin = PlatformPin("0.1.0", tree_digest(vdir), False, "p")
        (vdir / "src" / "dev_platform" / "model.py").write_text("# tampered\n")
        with self.assertRaisesRegex(PlatformResolutionError, "integrity failure"):
            R.resolve(_Cfg(pin), env={R.STORE_ENV: str(store)})

    def test_missing_version(self):
        with self.assertRaisesRegex(PlatformResolutionError, "not installed"):
            R.resolve(_Cfg(PlatformPin("9.9.9", "0" * 64, False, "p")), env={R.STORE_ENV: str(tmpdir(self))})

    def test_self_hosted_is_never_certifiable(self):
        res = R.resolve(_Cfg(PlatformPin(None, None, True)), env={})
        self.assertEqual(res.mode, "self")
        self.assertFalse(res.certifiable)

    def test_digest_ignores_bytecode_but_not_content(self):
        _, vdir = make_release(self)
        d = tree_digest(vdir)
        (vdir / "src" / "__pycache__").mkdir()
        (vdir / "src" / "__pycache__" / "x.pyc").write_bytes(b"x")
        self.assertEqual(d, tree_digest(vdir))
        (vdir / "src" / "new.txt").write_text("x")
        self.assertNotEqual(d, tree_digest(vdir))

    def test_symlinks_in_pinned_tree_rejected(self):
        _, vdir = make_release(self)
        (vdir / "link").symlink_to(vdir / "src")
        with self.assertRaises(ValueError):
            tree_digest(vdir)

    def test_override_allowed_locally_but_not_certifiable(self):
        dev = tmpdir(self)
        (dev / "src" / "dev_platform").mkdir(parents=True)
        pin = PlatformPin("0.1.0", "0" * 64, False, "p")
        res = R.resolve(_Cfg(pin), env={R.OVERRIDE_ENV: str(dev)})
        self.assertEqual(res.mode, "override")
        self.assertFalse(res.certifiable)

    def test_override_refused_in_protected_contexts(self):
        dev = tmpdir(self)
        (dev / "src" / "dev_platform").mkdir(parents=True)
        pin = PlatformPin("0.1.0", "0" * 64, False, "p")
        for env in ({"CI": "true"}, {"GITHUB_ACTIONS": "true"}):
            with self.assertRaisesRegex(PlatformResolutionError, "protected"):
                R.resolve(_Cfg(pin), env={R.OVERRIDE_ENV: str(dev), **env})
        with self.assertRaises(PlatformResolutionError):
            R.resolve(_Cfg(pin), env={R.OVERRIDE_ENV: str(dev)}, protected=True)

    def test_reexec_decision_and_loop_guard(self):
        other = R.Resolution("pinned", "0.1.0", tmpdir(self), "d")
        self.assertTrue(R.needs_reexec(other, env={}))
        with self.assertRaisesRegex(PlatformResolutionError, "re-executed"):
            R.needs_reexec(other, env={R.REEXEC_ENV: "0.1.0"})
        here = R.Resolution("self", "0.1.0", R.PACKAGE_ROOT, None)
        self.assertFalse(R.needs_reexec(here, env={}))


if __name__ == "__main__":
    unittest.main()
