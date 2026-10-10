import unittest

from dev_platform.detect import detect, is_bazel_workspace
from tests.helpers import FIXTURES


class DetectTest(unittest.TestCase):
    def test_python_only(self):
        f = detect(FIXTURES / "python-only")
        self.assertEqual(f["languages"], {"python": 2})
        self.assertEqual(f["build_systems"], {})

    def test_rust_cargo(self):
        f = detect(FIXTURES / "rust-cargo")
        self.assertEqual(f["languages"], {"rust": 1})
        self.assertEqual(f["build_systems"], {"cargo": ["Cargo.toml"]})
        self.assertFalse(is_bazel_workspace(f))

    def test_rust_bazel(self):
        f = detect(FIXTURES / "rust-bazel")
        self.assertTrue(is_bazel_workspace(f))
        self.assertNotIn("cargo", f["build_systems"])

    def test_mixed(self):
        f = detect(FIXTURES / "mixed-bazel")
        self.assertEqual(sorted(f["languages"]), ["python", "rust"])
        self.assertTrue(is_bazel_workspace(f))

    def test_facts_do_not_assert_requirements(self):
        f = detect(FIXTURES / "mixed-bazel")
        self.assertNotIn("assurance", f)
        self.assertIn("declared in dev-platform.toml", f["note"])

    def test_deterministic(self):
        self.assertEqual(detect(FIXTURES / "mixed-bazel"), detect(FIXTURES / "mixed-bazel"))


if __name__ == "__main__":
    unittest.main()
