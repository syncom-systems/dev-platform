"""`init` derives checks from build-system markers and real test layout (pilot finding on a Rust workspace)."""

import contextlib
import io
import os
import tomllib
import unittest
from pathlib import Path

from dev_platform import cli
from dev_platform.errors import ConfigError
from tests.helpers import tmpdir


def init(test, files):
    root = tmpdir(test)
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    old = os.environ.get("DEV_PLATFORM_STORE")
    os.environ["DEV_PLATFORM_STORE"] = str(tmpdir(test))
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["init", "--project", str(root), "--platform-version", "0.1.0",
                             "--sha256", "0" * 64, "--profile", "p"])  # fmt: skip
    finally:
        if old is None:
            os.environ.pop("DEV_PLATFORM_STORE")
        else:
            os.environ["DEV_PLATFORM_STORE"] = old
    cfg = Path(root) / "dev-platform.toml"
    return code, tomllib.loads(cfg.read_text()) if cfg.is_file() else None


class Init(unittest.TestCase):
    def ids(self, doc):
        return [c["id"] for c in doc["check"]]

    def test_rust_workspace_with_incidental_python_gets_only_cargo(self):
        code, doc = init(
            self, {"Cargo.toml": "[workspace]\n", "tools/gen.py": "print(1)\n", "src/lib.rs": ""}
        )
        self.assertEqual((code, self.ids(doc), doc["project"]["languages"]), (0, ["cargo.test"], ["rust"]))

    def test_python_project_with_tests(self):
        code, doc = init(self, {"tests/test_a.py": "", "a.py": ""})
        self.assertEqual((code, self.ids(doc)), (0, ["python.unittest"]))

    def test_python_files_without_tests_get_no_python_check(self):
        _, doc = init(self, {"a.py": "", "Cargo.toml": "[package]\n"})
        self.assertEqual(self.ids(doc), ["cargo.test"])

    def test_mixed_python_tests_and_cargo(self):
        _, doc = init(self, {"Cargo.toml": "[package]\n", "tests/test_a.py": "", "a.py": ""})
        self.assertEqual(self.ids(doc), ["python.unittest", "cargo.test"])

    def test_bazel_workspace(self):
        _, doc = init(self, {"MODULE.bazel": "", "BUILD.bazel": "", "a.rs": ""})
        self.assertEqual((self.ids(doc), doc["project"]["bazel_only"]), (["bazel.test"], True))

    def test_nothing_recognised_is_refused(self):
        root = tmpdir(self)
        (root / "a.py").write_text("")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ConfigError):
            cli.cmd_init(
                type("A", (), {"project": root, "force": False, "sha256": "0" * 64, "platform_version": "0.1.0",
                               "profile": "p", "json": False})()
            )  # fmt: skip


if __name__ == "__main__":
    unittest.main()
