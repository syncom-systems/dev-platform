"""`dev-platform workflow`: a proposal on GitHub-hosted runners; nothing is written unless asked, never replaced."""

import json
import os
import shutil
import subprocess
import sys
import unittest

from dev_platform import workflow_preview as W
from dev_platform.errors import ConfigError
from tests.helpers import ROOT, tmpdir

PINNED = ROOT / "fixtures-real" / "setup-0.8.2"


def project(test, version="0.8.2"):
    d = tmpdir(test) / "p"
    shutil.copytree(PINNED, d)
    if version != "0.8.2":
        pins = json.loads((d / W.PINS_FILENAME).read_text())
        pins["version"] = version
        (d / W.PINS_FILENAME).write_text(json.dumps(pins))
    return d


class Render(unittest.TestCase):
    def test_caller_of_the_pinned_reusable_workflow(self):
        text, notes = W.render(project(self))
        rev = json.loads((PINNED / W.PINS_FILENAME).read_text())["source_revision"]
        self.assertIn(f"uses: {W.REUSABLE}@{rev}", text)
        self.assertIn(f'platform_source_revision: "{rev}"', text)
        self.assertIn("permissions:\n  contents: read\n", text)
        self.assertIn("allow_unaccepted: false", text)
        self.assertNotIn("pull_request_target", text)
        self.assertNotIn("secrets", text)
        self.assertNotIn("self-hosted", text)
        self.assertEqual(notes, [])

    def test_the_proposal_has_no_admission_violation(self):
        from dev_platform import prcheck

        text, _ = W.render(project(self), runs_on="macos-15")
        out = prcheck.check({"dev-platform.yml": text}, None)
        self.assertEqual(out["policy_violations"], [])
        # The external reusable workflow is not visible to a static check of the caller alone: incomplete, never
        # passed silently. The reusable workflow itself is checked here, in its own repository.
        self.assertEqual([i["detail"] for i in out["incomplete"] if "is not visible" not in i["detail"]], [])
        own = (ROOT / ".github/workflows/consumer-pilot.yml").read_text()
        self.assertEqual(prcheck.check({"consumer-pilot.yml": own}, None)["admission"], "ok")

    def test_only_github_hosted_labels(self):
        for label in (
            "self-hosted",
            "build",
            "linux",
            "windows-2025",
            "ubuntu-24.04 ",
            "${{ vars.RUNNER }}",
            "Ubuntu-24.04",
        ):
            with self.assertRaises(ConfigError, msg=label):
                W.render(project(self), runs_on=label)

    def test_unprovisionable_platform_is_noted(self):
        _, notes = W.render(project(self), runs_on="ubuntu-24.04-arm")
        self.assertTrue(any("linux-arm64" in n for n in notes))

    def test_the_pinned_version_cannot_inject_yaml(self):
        for v in ("0.8.2\n    secrets: inherit", "0.8.2 # x", "0.9.0x"):
            with self.assertRaises(ConfigError, msg=v):
                W.render(project(self, version=v))

    def test_needs_config_and_a_working_release(self):
        d = project(self)
        (d / "dev-platform.toml").unlink()
        with self.assertRaises(ConfigError):
            W.render(d)
        with self.assertRaises(ConfigError):
            W.render(project(self, version="0.8.1"))
        d = project(self)
        (d / W.PINS_FILENAME).unlink()
        with self.assertRaises(ConfigError):
            W.render(d)


class Command(unittest.TestCase):
    def run_cli(self, *a):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        return subprocess.run(
            [sys.executable, "-m", "dev_platform", "workflow", *a], capture_output=True, text=True, env=env
        )

    def test_prints_and_writes_nothing(self):
        d = project(self)
        before = sorted(p.relative_to(d) for p in d.rglob("*"))
        p = self.run_cli("--project", str(d))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("name: dev-platform", p.stdout)
        self.assertEqual(sorted(p.relative_to(d) for p in d.rglob("*")), before)
        self.assertFalse((d / ".github").exists())

    def test_output_creates_and_never_replaces(self):
        d = project(self)
        out = tmpdir(self) / "proposed.yml"
        self.assertEqual(self.run_cli("--project", str(d), "--output", str(out)).returncode, 0)
        first = out.read_text()
        out.write_text("mine")
        p = self.run_cli("--project", str(d), "--output", str(out))
        self.assertEqual(p.returncode, 2)
        self.assertEqual(out.read_text(), "mine")
        link = tmpdir(self) / "link.yml"
        os.symlink(tmpdir(self) / "target.yml", link)
        self.assertEqual(self.run_cli("--project", str(d), "--output", str(link)).returncode, 2)
        self.assertFalse((link.parent / "target.yml").exists())
        self.assertIn("consumer-pilot.yml", first)


if __name__ == "__main__":
    unittest.main()
