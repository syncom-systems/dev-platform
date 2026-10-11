import importlib.util
import unittest

from tests.helpers import ROOT, tmpdir

spec = importlib.util.spec_from_file_location("setup_env", ROOT / "tools" / "setup_env.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


class VersionStore(unittest.TestCase):
    def install(self, dev, name, version, marker):
        d = S.version_dir(dev, name, version)
        (d / "bin").mkdir(parents=True)
        (d / "bin" / "tool").write_text(marker)
        return d

    def test_versions_coexist_and_activation_only_selects(self):
        dev = tmpdir(self)
        a = self.install(dev, "python", "3.13.1", "a")
        b = self.install(dev, "python", "3.14.7", "b")
        S.activate(dev / "python", a)
        self.assertEqual((dev / "python" / "bin" / "tool").read_text(), "a")
        S.activate(dev / "python", b)
        self.assertEqual((dev / "python" / "bin" / "tool").read_text(), "b")
        self.assertEqual((a / "bin" / "tool").read_text(), "a")  # untouched by selecting another
        self.assertEqual((dev / "python").resolve(), b.resolve())

    def test_activate_replaces_legacy_real_directory(self):
        dev = tmpdir(self)
        (dev / "python" / "bin").mkdir(parents=True)
        v = self.install(dev, "python", "3.14.7", "new")
        S.activate(dev / "python", v)
        self.assertTrue((dev / "python").is_symlink())


if __name__ == "__main__":
    unittest.main()


class Provision(unittest.TestCase):
    """The shared provisioning code (also used by consumers via `toolchain provision`)."""

    def manifest(self, url="https://example.invalid/x.tar.gz", sha="0" * 64):
        return {
            "profiles": {
                "p": {"tools": {"t": {"version": "1.0", "source": {"k": {"url": url, "sha256": sha}}}}}
            }
        }

    def test_refuses_non_https_and_unknown_profile(self):
        from dev_platform.errors import ConfigError
        from dev_platform.provision import provision

        with self.assertRaises(ConfigError):
            provision(self.manifest(url="http://example.invalid/x.tar.gz"), "p", tmpdir(self), key="k")
        with self.assertRaises(ConfigError):
            provision(self.manifest(), "nope", tmpdir(self), key="k")

    def test_hash_mismatch_removes_the_download(self):
        from unittest import mock

        from dev_platform import provision as P
        from dev_platform.errors import ConfigError

        dest = tmpdir(self) / "f"
        data = b"payload"

        class R:
            def __init__(self):
                self.b = data

            def read(self, n):
                b, self.b = self.b, b""
                return b

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(P.urllib.request, "urlopen", lambda *a, **k: R()):
            with self.assertRaises(ConfigError):
                P.fetch("https://example.invalid/x", "0" * 64, dest)
            self.assertFalse(dest.exists())
            import hashlib

            P.fetch("https://example.invalid/x", hashlib.sha256(data).hexdigest(), dest)
            self.assertEqual(dest.read_bytes(), data)

    def test_tools_without_a_source_for_the_platform_are_left_to_the_caller(self):
        from dev_platform.provision import provision

        self.assertEqual(provision(self.manifest(), "p", tmpdir(self), key="other"), [])
