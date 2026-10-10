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
