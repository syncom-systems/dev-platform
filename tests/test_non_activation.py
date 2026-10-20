"""Installing or running the CLI activates nothing (ADR 0023): no files outside what a command is asked to write,
no network unless a command is explicitly about reading GitHub, no service, no workflow, no setting."""

import importlib.util
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from dev_platform import infra_release
from tests.helpers import ROOT, tmpdir
from tests.infra_fixtures import VERSION, config_repo

spec = importlib.util.spec_from_file_location("homebrew_formula", ROOT / "tools" / "homebrew_formula.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)


def snapshot(d: Path) -> dict:
    """Every path under `d` with its content (or a directory marker), to compare before and after."""
    out = {}
    for p in sorted(d.rglob("*")):
        out[p.relative_to(d).as_posix()] = p.read_bytes() if p.is_file() and not p.is_symlink() else None
    return out


class Sandbox(unittest.TestCase):
    """A user with an empty home and a `gh` that records every call (a network action)."""

    def setUp(self):
        self.base = tmpdir(self)
        self.home = self.base / "home"
        self.calls = self.base / "gh-calls"
        bindir = self.base / "bin"
        bindir.mkdir()
        gh = bindir / "gh"
        gh.write_text(f'#!/bin/sh\necho "$@" >> {self.calls}\nexit 1\n')
        gh.chmod(0o755)
        self.env = {
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "HOME": str(self.home),
            "PYTHONPATH": str(ROOT / "src"),
            "LANG": "C.UTF-8",
        }

    def cli(self, *argv, cwd=None):
        return subprocess.run([sys.executable, "-m", "dev_platform", *argv], capture_output=True, text=True,
                              env=self.env, cwd=cwd or self.base)  # fmt: skip

    def assertNothingActivated(self):
        self.assertFalse(self.home.exists(), "a command wrote into the user's home")
        self.assertFalse(self.calls.exists(), "a command reached GitHub")


class ReadOnlyCommands(Sandbox):
    def test_help_and_version_of_every_command(self):
        p = self.cli("infra", "--help")
        subs = re.search(r"\{([a-z,-]+)\}", p.stdout).group(1).split(",")
        self.assertGreaterEqual(len(subs), 15)
        for argv in (
            ["--version"],
            ["--help"],
            ["workflow", "--help"],
            *(["infra", s, "--help"] for s in subs),
        ):
            self.assertEqual(self.cli(*argv).returncode, 0, argv)
        self.assertNothingActivated()

    def test_operator_commands_without_network(self):
        repo = self.base / "cfg"
        repo.mkdir()
        digests = config_repo(repo)
        project = self.base / "project"
        project.mkdir()
        (project / "dev-platform.toml").write_text(
            f'[infra]\nprovider = "example-infra"\nconfig_release = "{VERSION}"\nconfig_digest = "{digests[VERSION]}"\n'
        )
        store = self.base / "store"
        before_repo = snapshot(repo)
        before_project = snapshot(project)
        runs = [
            ["infra", "release", "verify", "--root", str(repo)],
            ["infra", "validate", str(repo)],
            ["infra", "digest", str(repo / "releases" / VERSION)],
            ["infra", "authorization", "check", str(repo / "authorization" / "current.v1.json")],
            ["infra", "doctor", "--root", str(repo), "--project", str(project), "--repo", "example-org/app"],
            ["infra", "store", "list", "--store", str(store)],
            ["infra", "doctor", "--store", str(store)],
        ]
        for argv in runs:
            self.cli(*argv)
        self.assertEqual(snapshot(repo), before_repo)
        self.assertEqual(snapshot(project), before_project)
        self.assertFalse(store.exists())
        self.assertNothingActivated()

    def test_assurance_evaluate_runs_nothing_and_writes_nothing(self):
        from dev_platform import assurance
        from tests.test_assurance import projection

        work = self.base / "work"
        work.mkdir()
        doc = projection(producer_verdicts={"closure": "PASS"})
        (work / "p.json").write_text(json.dumps(doc))
        (work / "dev-platform.toml").write_text(
            '[[check]]\nid = "x"\nadapter = "exec"\nargv = ["touch", "ran"]\n'
        )
        before = snapshot(work)
        p = self.cli("assurance", "evaluate", "--projection", str(work / "p.json"), "--json", cwd=work)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout), assurance.evaluate(doc))  # the CLI adds nothing
        self.assertEqual(
            self.cli("assurance", "evaluate", "--projection", str(work / "p.json"), cwd=work).returncode, 0
        )
        self.assertEqual(snapshot(work), before)
        self.assertNothingActivated()

    def test_default_locations_are_not_created_by_reading(self):
        for argv in (["infra", "store", "list"], ["infra", "doctor"]):
            self.cli(*argv)
        self.assertNothingActivated()

    def test_init_writes_only_the_configuration(self):
        root = self.base / "infra-repo"
        p = self.cli(
            "infra", "init", "--root", str(root), "--owner", "example-org", "--template", "self-hosted"
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(list(snapshot(root)), ["config", "config/infra.v1.json"])
        self.assertNothingActivated()

    def test_workflow_preview_writes_nothing(self):
        project = self.base / "p"
        import shutil

        shutil.copytree(ROOT / "fixtures-real" / "setup-0.8.2", project)
        before = snapshot(project)
        self.assertEqual(self.cli("workflow", "--project", str(project)).returncode, 0)
        self.assertEqual(snapshot(project), before)
        self.assertNothingActivated()


class OnlyExplicitCommandsReadGitHub(Sandbox):
    def test_discover_fetch_and_sync_are_the_only_ones_and_use_get(self):
        for argv in (
            ["infra", "discover", "--owner", "example-org", "--repo", "app"],
            ["infra", "store", "fetch", VERSION, "--digest", "sha256:" + "0" * 64, "--source", "example-org/infra",
             "--store", str(self.base / "s")],
            ["infra", "store", "sync", "--source", "example-org/infra", "--store", str(self.base / "s")],
        ):  # fmt: skip
            self.cli(*argv)
        calls = self.calls.read_text().splitlines()
        self.assertTrue(calls)
        for c in calls:
            self.assertTrue(c.startswith("api --method GET "), c)
        self.assertFalse((self.base / "s" / "releases").exists())  # no access: nothing stored


class SourceHasNoActivationPaths(unittest.TestCase):
    """Static guards over the shipped package (src/dev_platform is the release tree)."""

    SRC = ROOT / "src" / "dev_platform"

    def text(self):
        return {p.name: p.read_text() for p in sorted(self.SRC.glob("*.py"))}

    def test_no_service_scheduler_or_runner_registration(self):
        forbidden = re.compile(
            r"launchctl|LaunchAgents|systemctl|crontab|config\.sh|svc\.sh|actions/runners/registration-token"
            r"|registration-token|/actions/runners/[a-z-]*remove-token"
        )
        for name, text in self.text().items():
            self.assertIsNone(forbidden.search(text), name)

    def test_no_writes_to_github(self):
        # Every `gh api` the package issues is a GET (planning has an explicit --apply mode of its own and is not an
        # infrastructure command); no infrastructure module can change a setting.
        for name, text in self.text().items():
            if not name.startswith("infra"):
                continue
            for m in re.finditer(r'"gh",\s*"api"[^\]]*\]', text):
                self.assertIn('"--method", "GET"', m.group(0), name)
            for verb in (
                '"POST"',
                '"PUT"',
                '"PATCH"',
                '"DELETE"',
                '"-X"',
                '"--field"',
                '"-f"',
                '"-F"',
                '"--input"',
            ):
                self.assertNotIn(verb, text, f"{name}: {verb}")

    def test_no_infrastructure_module_writes_workflows_or_settings(self):
        for name, text in self.text().items():
            if name.startswith("infra") or name == "workflow_preview.py":
                self.assertNotRegex(text, r"\.github/workflows/[^\s\"']*\"\s*\)?\s*\.write", name)
                self.assertIsNone(
                    re.search(r'"git",\s*(?:"-C",\s*[^,]+,\s*)?"(commit|push|tag)"', text), name
                )


class Formula(unittest.TestCase):
    def render(self):
        f = tmpdir(self) / "identity.json"
        f.write_text(json.dumps({"version": "0.10.0", "archive": "dev-platform-0.10.0.tar.gz",
                                 "archive_sha256": "a" * 64, "tree_digest_pin": "b" * 64,
                                 "source_revision": "c" * 40}))  # fmt: skip
        return H.from_identity(f)

    def test_installs_the_cli_only(self):
        text = self.render()
        for word in ("service do", "post_install", "plist", "launchctl", "crontab", "systemctl", "etc.install",
                     "var.install", "HOMEBREW_PREFIX/etc", "infra"):  # fmt: skip
            self.assertNotIn(word, text)
        install = text[text.index("def install") : text.index("def caveats")]
        self.assertEqual(re.findall(r"(\w+)\.install", install), ["libexec"])
        self.assertEqual(sorted(re.findall(r'depends_on "([^"]+)"', text)), ["gh", "python@3.14"])
        # the test block only reads: version, digest, and a dry-run in its own testpath
        test = text[text.index("test do") :]
        for line in (x for x in test.splitlines() if " setup " in x):
            self.assertIn("--dry-run", line)


class UpgradePreservesSelections(Sandbox):
    """A newer CLI reads what an older one stored without changing a byte, and pins never move."""

    def test_store_and_pins_unchanged_by_every_reading_command(self):
        repo = self.base / "cfg"
        repo.mkdir()
        digests = config_repo(repo, versions=(VERSION, "2026.02.1"))
        store = self.base / "store"
        for v, d in digests.items():
            p = self.cli("infra", "store", "import", v, "--digest", d, "--from", str(repo), "--with-policy",
                         "--store", str(store))  # fmt: skip
            self.assertEqual(p.returncode, 0, p.stderr)
        project = self.base / "project"
        project.mkdir()
        pin = f'[infra]\nprovider = "example-infra"\nconfig_release = "{VERSION}"\nconfig_digest = "{digests[VERSION]}"\n'
        (project / "dev-platform.toml").write_text(pin)
        before_store, before_project = snapshot(store), snapshot(project)
        req = json.dumps({"schema_version": "dev-platform.infra-resolve-request/v1", "repo": "example-org/app",
                          "event_trust": "trusted", "contract": "dev-platform.infra/v1",
                          "requested": {"version": VERSION, "digest": digests[VERSION]},
                          "profile_out": str(self.base / "profile.json")})  # fmt: skip
        req_file = self.base / "req.json"
        req_file.write_text(req)
        for argv in (["infra", "store", "list", "--store", str(store)],
                     ["infra", "doctor", "--store", str(store), "--project", str(project), "--repo", "example-org/app"],
                     ["infra", "resolve", "--root", str(store), "--request", str(req_file)],
                     ["infra", "store", "import", VERSION, "--digest", digests[VERSION], "--from", str(repo),
                      "--store", str(store)]):  # fmt: skip
            p = self.cli(*argv)
            self.assertEqual(p.returncode, 0, (argv, p.stdout, p.stderr))
        self.assertEqual(snapshot(store), before_store)
        self.assertEqual(snapshot(project), before_project)
        for v, d in digests.items():
            self.assertEqual(
                infra_release.wire(infra_release.digest_of(infra_release.read_tree(store / "releases" / v))),
                d,
            )


if __name__ == "__main__":
    unittest.main()
