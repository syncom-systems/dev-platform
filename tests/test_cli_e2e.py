"""First milestone: a standalone consumer, a pinned release, no private infrastructure."""

import json
import os
import shutil
import subprocess
import sys
import unittest

from dev_platform.digest import tree_digest
from tests.helpers import ROOT, copy_fixture, tmpdir


def make_store(test):
    store = tmpdir(test)
    vdir = store / "0.1.0"
    shutil.copytree(ROOT / "src", vdir / "src", ignore=shutil.ignore_patterns("__pycache__"))
    init = vdir / "src" / "dev_platform" / "__init__.py"
    init.write_text(init.read_text().replace('"0.1.0"', '"0.1.0+store"'))  # prove which code runs
    return store, vdir


def run(project, store, *args, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS", "PYTHONPATH")}
    env.update({"PYTHONPATH": str(ROOT / "src"), "DEV_PLATFORM_STORE": str(store), **(env_extra or {})})
    return subprocess.run(
        [sys.executable, "-m", "dev_platform", args[0], "--project", str(project), *args[1:]],
        capture_output=True,
        text=True,
        env=env,
    )


class MilestoneTest(unittest.TestCase):
    def setUp(self):
        self.store, self.vdir = make_store(self)
        self.proj = copy_fixture(self, "python-only")
        self.proj_git = subprocess.run(["git", "init", "-q"], cwd=self.proj).returncode == 0

    def test_end_to_end(self):
        r = run(self.proj, self.store, "detect", "--json")
        self.assertEqual(json.loads(r.stdout)["languages"], {"python": 2})

        r = run(self.proj, self.store, "init", "--platform-version", "0.1.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = (self.proj / "dev-platform.toml").read_text()
        self.assertIn(tree_digest(self.vdir), cfg)
        self.assertIn('assurance = "standard"', cfg)

        r = run(self.proj, self.store, "doctor")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no private infrastructure required", r.stdout)

        r = run(self.proj, self.store, "explain", "--changed", "app.py")
        self.assertIn("app.py matches input **/*.py", r.stdout)

        out = self.proj / "result.json"
        r = run(self.proj, self.store, "check", "--changed", "app.py", "--result", str(out))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        doc = json.loads(out.read_text())
        self.assertEqual(doc["schema"], "dev-platform.result/v1")
        self.assertEqual(doc["platform"]["running_version"], "0.1.0+store")  # re-exec'd into the pin
        self.assertEqual(doc["platform"]["mode"], "pinned")
        self.assertEqual(doc["admission"], "admitted")
        self.assertEqual(doc["checks"][0]["state"], "verified")

    def test_failing_test_blocks_with_exit_1(self):
        run(self.proj, self.store, "init", "--platform-version", "0.1.0")
        (self.proj / "app.py").write_text("def add(a, b):\n    return a - b\n")
        r = run(self.proj, self.store, "check", "--changed", "app.py")
        self.assertEqual(r.returncode, 1)
        self.assertIn("admission: blocked", r.stdout)

    def test_tampered_release_exit_3(self):
        run(self.proj, self.store, "init", "--platform-version", "0.1.0")
        with open(self.vdir / "src" / "dev_platform" / "model.py", "a") as f:
            f.write("# tampered\n")
        r = run(self.proj, self.store, "check", "--changed", "app.py")
        self.assertEqual(r.returncode, 3)
        self.assertIn("integrity failure", r.stderr)

    def test_override_refused_when_protected(self):
        run(self.proj, self.store, "init", "--platform-version", "0.1.0")
        r = run(
            self.proj,
            self.store,
            "explain",
            "--changed",
            "app.py",
            env_extra={"DEV_PLATFORM_OVERRIDE": str(ROOT), "GITHUB_ACTIONS": "true"},
        )
        self.assertEqual(r.returncode, 3)
        r = run(
            self.proj,
            self.store,
            "explain",
            "--changed",
            "app.py",
            env_extra={"DEV_PLATFORM_OVERRIDE": str(ROOT)},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("override", r.stdout)

    def test_invalid_config_exit_2(self):
        (self.proj / "dev-platform.toml").write_text("schema_version = 7\n")
        r = run(self.proj, self.store, "check")
        self.assertEqual(r.returncode, 2)
        self.assertIn("config error", r.stderr)

    def test_missing_config_exit_2_with_hint(self):
        r = run(self.proj, self.store, "doctor")
        self.assertEqual(r.returncode, 2)
        self.assertIn("dev-platform init", r.stdout)

    def test_init_refuses_overwrite(self):
        run(self.proj, self.store, "init", "--platform-version", "0.1.0")
        self.assertEqual(run(self.proj, self.store, "init", "--platform-version", "0.1.0").returncode, 2)

    def test_init_bazel_only_never_proposes_cargo(self):
        proj = copy_fixture(self, "rust-bazel")
        r = run(proj, self.store, "init", "--platform-version", "0.1.0")
        self.assertEqual(r.returncode, 0, r.stderr)
        cfg = (proj / "dev-platform.toml").read_text()
        self.assertIn("bazel_only = true", cfg)
        self.assertNotIn("cargo", cfg)

    def test_init_cargo_project_gets_cargo_adapter(self):
        proj = copy_fixture(self, "rust-cargo")
        run(proj, self.store, "init", "--platform-version", "0.1.0")
        self.assertIn('adapter = "cargo"', (proj / "dev-platform.toml").read_text())

    def test_doctor_warns_on_undeclared_language(self):
        proj = copy_fixture(self, "mixed-bazel")
        run(proj, self.store, "init", "--platform-version", "0.1.0")
        text = (
            (proj / "dev-platform.toml")
            .read_text()
            .replace('languages = ["python", "rust"]', "languages = []")
        )
        (proj / "dev-platform.toml").write_text(text)
        r = run(proj, self.store, "doctor")
        self.assertIn("[warn] detected python is not declared", r.stdout)


if __name__ == "__main__":
    unittest.main()
