import shutil
import unittest

from dev_platform import resolve as R
from dev_platform.config import PlatformPin
from dev_platform.digest import tree_digest
from dev_platform.errors import PlatformResolutionError
from tests.helpers import ROOT, tmpdir


class _Cfg:
    def __init__(self, pin):
        self.platform = pin


def make_release(test, version="0.1.0"):
    store = tmpdir(test)
    vdir = store / version
    shutil.copytree(ROOT / "src", vdir / "src", ignore=shutil.ignore_patterns("__pycache__"))
    return store, vdir


class ResolveTest(unittest.TestCase):
    def test_pinned_resolution_verifies_digest(self):
        store, vdir = make_release(self)
        pin = PlatformPin("0.1.0", tree_digest(vdir), False)
        res = R.resolve(_Cfg(pin), env={R.STORE_ENV: str(store)})
        self.assertEqual((res.mode, res.version, res.digest), ("pinned", "0.1.0", pin.sha256))
        self.assertTrue(res.certifiable)

    def test_tampered_release_is_rejected(self):
        store, vdir = make_release(self)
        pin = PlatformPin("0.1.0", tree_digest(vdir), False)
        (vdir / "src" / "dev_platform" / "model.py").write_text("# tampered\n")
        with self.assertRaisesRegex(PlatformResolutionError, "integrity failure"):
            R.resolve(_Cfg(pin), env={R.STORE_ENV: str(store)})

    def test_missing_version(self):
        with self.assertRaisesRegex(PlatformResolutionError, "not installed"):
            R.resolve(_Cfg(PlatformPin("9.9.9", "0" * 64, False)), env={R.STORE_ENV: str(tmpdir(self))})

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
        pin = PlatformPin("0.1.0", "0" * 64, False)
        res = R.resolve(_Cfg(pin), env={R.OVERRIDE_ENV: str(dev)})
        self.assertEqual(res.mode, "override")
        self.assertFalse(res.certifiable)

    def test_override_refused_in_protected_contexts(self):
        dev = tmpdir(self)
        (dev / "src" / "dev_platform").mkdir(parents=True)
        pin = PlatformPin("0.1.0", "0" * 64, False)
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
