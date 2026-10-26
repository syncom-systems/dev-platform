"""Repository isolation (ADR 0027): `install` and `update` write only dev-platform.toml; setup, repeated
installation and verification leave every other project file, and the project tree itself, untouched."""

import json
import os
import shutil
import subprocess
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from dev_platform import config, infra_store, pinning, project_install, projectsetup
from dev_platform import locations as L
from dev_platform.errors import ConfigError
from tests import infra_fixtures as F
from tests.helpers import ROOT, tmpdir
from tests.repo_snapshot import changed, snapshot
from tests.test_cli_e2e import make_store, run
from tests.test_pack import rmtree_rw
from tests.test_setup import FakeToolchains, build_release, platform_repo, write_project

REV = "c" * 40


def tree(root: Path) -> dict:
    """Every entry under root: directories and file bytes."""
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None) for p in sorted(root.rglob("*"))
    }


def gh_runner(identity, tag_sha):
    def run(argv, **kw):
        path = argv[argv.index("--method") + 2] if "--method" in argv else ""
        out = json.dumps(identity).encode() if "contents/releases" in path else (tag_sha + "\n").encode()
        return subprocess.CompletedProcess(argv, 0, out, b"")

    return run


IDENT = {
    "version": "0.17.0",
    "source_revision": REV,
    "archive_sha256": "b" * 64,
    "tree_digest_pin": "a" * 64,
    "verifier_pins": {
        "verify_release.py_sha256": "1" * 64,
        "trust_policy_sha256": "2" * 64,
        "install_release.py_sha256": "3" * 64,
        "install_release_extra": "ignored",
    },
}


class Pins(unittest.TestCase):
    def test_identity_comes_from_the_published_record_and_the_tag_must_agree(self):
        got = pinning.platform_identity("0.17.0", run=gh_runner(IDENT, REV))
        self.assertEqual(
            got["verifier_pins"],
            {"verify_release": "1" * 64, "trust_policy": "2" * 64, "install_release": "3" * 64},
        )
        with self.assertRaises(ConfigError) as e:
            pinning.platform_identity("0.17.0", run=gh_runner(IDENT, "d" * 40))
        self.assertIn("tag v0.17.0 does not name", str(e.exception))
        with self.assertRaises(ConfigError):
            pinning.platform_identity("0.17.0", run=gh_runner({**IDENT, "version": "0.17.1"}, REV))

    def test_releases_before_isolation_cannot_be_pinned(self):
        with self.assertRaises(ConfigError) as e:
            pinning.platform_identity("0.16.0", run=gh_runner(IDENT, REV))
        self.assertIn("predates repository isolation", str(e.exception))

    def test_block_roundtrips_through_the_config(self):
        pins = pinning.platform_identity("0.17.0", run=gh_runner(IDENT, REV))
        text = "schema_version = 1\n" + pinning.platform_block(pins, "py") + "\n[project]\nname = 'x'\n"
        text += '[[check]]\nid = "t"\nadapter = "exec"\nargv = ["true"]\nstages = ["pre-merge"]\nobligation = "always"\n'
        p = config.parse(tomllib.loads(text)).platform
        self.assertEqual(
            (p.version, p.sha256, p.source_revision, p.archive_sha256), ("0.17.0", "a" * 64, REV, "b" * 64)
        )
        self.assertEqual(p.verifier_pins, pins["verifier_pins"])

    def test_partial_identity_is_a_configuration_error(self):
        for extra in (f'source_revision = "{REV}"\n', 'archive_sha256 = "%s"\n' % ("b" * 64)):
            text = f'schema_version = 1\n[platform]\nversion = "0.17.0"\nsha256 = "{"a" * 64}"\nprofile = "p"\n{extra}'
            text += "[project]\nname = 'x'\n"
            with self.assertRaises(ConfigError):
                config.parse(tomllib.loads(text))


class Edit(unittest.TestCase):
    ORIGINAL = (
        '# project policy\nschema_version = 1\n\n[platform]\nversion = "0.17.0"\nsha256 = "'
        + "a" * 64
        + '"\n'
        'profile = "py"\n\n# the project\n[project]\nname = "x"\n\n[[check]]\nid = "t"\nadapter = "exec"\n'
        'argv = ["true"]\nstages = ["pre-merge"]\nobligation = "always"\n'
    )

    def block(self, ver="0.17.1"):
        pins = pinning.platform_identity("0.17.0", run=gh_runner(IDENT, REV))
        return pinning.platform_block({**pins, "version": ver}, "py")

    def test_only_the_platform_table_changes_and_applying_twice_changes_nothing(self):
        new = pinning.apply(self.ORIGINAL, platform=self.block())
        again = pinning.apply(new, platform=self.block())
        self.assertEqual(new, again)
        gone = [
            ln
            for ln in pinning.diff(self.ORIGINAL, new).splitlines()
            if ln.startswith("-") and not ln.startswith("---")
        ]
        self.assertEqual(gone, ['-version = "0.17.0"'])
        self.assertEqual(new.split("# the project\n")[1], self.ORIGINAL.split("# the project\n")[1])
        self.assertTrue(new.startswith("# project policy\nschema_version = 1\n"))

    def test_infra_is_added_after_platform_then_replaced_in_place(self):
        pin = {
            "provider": "org-infra",
            "config_release": "2026.10.2",
            "config_digest": "sha256:" + "e" * 64,
            "config_digest_kind": "release-tree",
        }
        once = pinning.apply(self.ORIGINAL, platform=self.block(), infra=pinning.infra_block(pin))
        self.assertLess(once.index("[platform.verifier_pins]"), once.index("[infra]"))
        self.assertLess(once.index("[infra]"), once.index("[project]"))
        twice = pinning.apply(once, infra=pinning.infra_block({**pin, "config_release": "2026.10.3"}))
        self.assertEqual(twice.count("[infra]"), 1)
        self.assertIn('config_release = "2026.10.3"', twice)
        self.assertEqual(
            pinning.apply(twice, infra=pinning.infra_block({**pin, "config_release": "2026.10.3"})), twice
        )

    def test_owner_tables_with_quoted_names_survive_a_platform_replacement(self):
        text = self.ORIGINAL + '\n[runner."owner table"]\nos = "linux"\n'
        new = pinning.apply(text, platform=self.block())
        self.assertIn('[runner."owner table"]\nos = "linux"', new)
        self.assertIn('[runner."owner table"]', pinning.apply(new, infra=pinning.infra_block(
            {"provider": "p", "config_release": "2026.10.2", "config_digest": "sha256:" + "e" * 64,
             "config_digest_kind": "release-tree"})))  # fmt: skip

    def test_an_invalid_result_is_refused(self):
        with self.assertRaises(ConfigError):
            pinning.apply(self.ORIGINAL, infra="[infra]\nprovider = 'x'")


class InstallBase(unittest.TestCase):
    """The whole project tree before and after, through install, a repeated install, update and verification."""

    def setUp(self):
        self.vdir, self.tree = build_release(self, "0.8.9")
        sources = {"0.8.9": {"dir": str(self.vdir), "archive_sha256": "b" * 64, "tree": self.tree}}
        self.repo, rev, tool_pins = platform_repo(self, sources)
        self.pins = {
            "version": "0.8.9",
            "source_revision": rev,
            "archive_sha256": "b" * 64,
            "tree_digest_pin": self.tree,
            "verifier_pins": {
                "verify_release": tool_pins["verify_release.py_sha256"],
                "trust_policy": tool_pins["trust_policy_sha256"],
                "install_release": tool_pins["install_release.py_sha256"],
            },
        }
        home = self.home = tmpdir(self)
        self.addCleanup(rmtree_rw, home)
        self.loc = L.locate({}, home=home)
        bindir = tmpdir(self)
        (bindir / "gh").write_text("#!/bin/sh\nexit 0\n")
        (bindir / "gh").chmod(0o755)
        self.env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}
        for k in ("CI", "GITHUB_ACTIONS", "PYTHONPATH", "DEV_PLATFORM_OVERRIDE"):
            self.env.pop(k, None)
        self.patch = mock.patch.object(pinning, "platform_identity", return_value=self.pins)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def install(self, project, **kw):
        return project_install.install(
            project, self.loc, repo_url=str(self.repo), env=self.env, run=FakeToolchains(),
            allow_unaccepted=True, infra_store_dir=self.home / "infra", **kw,
        )  # fmt: skip

    def python_project(self):
        d = tmpdir(self) / "app"
        (d / "tests").mkdir(parents=True)
        (d / "tests" / "test_a.py").write_text("import unittest\n")
        (d / "README.md").write_text("hello\n")
        return d


class Isolation(InstallBase):
    def test_first_installation_creates_only_the_pin_file_and_repeating_it_changes_nothing(self):
        d = self.python_project()
        before = tree(d)
        rec, code = self.install(d, version="0.8.9", profile="py")
        self.assertEqual(code, 0, rec.get("problem"))
        self.assertTrue(rec["created"])
        after = tree(d)
        self.assertEqual(set(after) - set(before), {"dev-platform.toml"})
        self.assertEqual({k: v for k, v in after.items() if k != "dev-platform.toml"}, before)
        written = after["dev-platform.toml"]
        again, code = self.install(d)  # idempotent: verifies and reuses
        self.assertEqual(code, 0, again.get("problem"))
        self.assertFalse(again["created"])
        self.assertEqual(again["release"]["action"], "present")
        self.assertEqual(tree(d), after)
        self.assertEqual(tree(d)["dev-platform.toml"], written)
        pin = config.load(d).platform
        self.assertEqual((pin.version, pin.source_revision), ("0.8.9", self.pins["source_revision"]))

    def test_everything_installed_lives_outside_the_project(self):
        d = self.python_project()
        self.install(d, version="0.8.9", profile="py")
        self.assertTrue((self.loc.store / "0.8.9").is_dir())
        self.assertTrue((self.loc.toolchains / "0.8.9" / "py").is_dir())
        for p in (self.loc.store, self.loc.toolchains, self.loc.cache):
            self.assertFalse(p.is_relative_to(d.resolve()), p)

    def test_an_existing_pin_file_is_never_changed_by_install(self):
        d = write_project(
            tmpdir(self) / "p",
            "0.8.9",
            self.tree,
            {
                **self.pins,
                "verifier_pins": {
                    "verify_release.py_sha256": self.pins["verifier_pins"]["verify_release"],
                    "trust_policy_sha256": self.pins["verifier_pins"]["trust_policy"],
                    "install_release.py_sha256": self.pins["verifier_pins"]["install_release"],
                },
            },
        )
        before = tree(d)
        rec, code = self.install(d)
        self.assertEqual(code, 0, rec.get("problem"))
        self.assertEqual(tree(d), before)
        with self.assertRaises(projectsetup.Refused) as e:
            self.install(d, version="0.8.10")
        self.assertIn("`dev-platform update` proposes the change", str(e.exception))
        self.assertEqual(tree(d), before)

    def test_install_without_a_pin_file_needs_a_profile(self):
        d = self.python_project()
        with self.assertRaises(ConfigError):
            self.install(d)
        self.assertFalse((d / "dev-platform.toml").exists())

    def test_dry_run_writes_nothing(self):
        d = self.python_project()
        before = tree(d)
        rec, code = self.install(d, version="0.8.9", profile="py", dry_run=True)
        self.assertEqual((code, tree(d)), (0, before))
        self.assertIn("[platform]", rec["text"])

    def test_update_proposes_without_writing_and_writes_only_that_file(self):
        d = self.python_project()
        self.install(d, version="0.8.9", profile="py")
        before = tree(d)
        newer = {**self.pins, "version": "0.17.5", "tree_digest_pin": "f" * 64}
        with mock.patch.object(pinning, "platform_identity", return_value=newer):
            rec = project_install.propose(d, to="0.17.5")
            self.assertTrue(rec["changed"])
            self.assertFalse(rec["written"])
            self.assertEqual(tree(d), before)
            self.assertIn('+version = "0.17.5"', rec["diff"])
            rec = project_install.propose(d, to="0.17.5", write=True)
            self.assertTrue(rec["written"])
            changed = {k for k, v in tree(d).items() if before.get(k) != v}
            self.assertEqual(changed, {"dev-platform.toml"})
            again = project_install.propose(d, to="0.17.5", write=True)
            self.assertFalse(again["changed"])
        self.assertEqual(config.load(d).platform.version, "0.17.5")

    def test_infra_release_is_pinned_from_the_index_and_verified_into_an_external_store(self):
        cfgrepo = tmpdir(self) / "cfg"
        digests = F.config_repo(cfgrepo, versions=("2026.01.1",))
        fake = lambda repo, ref, version=None, runner=None: infra_store.from_directory(cfgrepo, version)
        d = self.python_project()
        with mock.patch.object(infra_store, "from_github", fake):
            rec, code = self.install(
                d, version="0.8.9", profile="py", infra_source="example-org/infra",
                infra_release="2026.01.1", infra_provider="example-infra",
                infra_digest=digests["2026.01.1"],
            )  # fmt: skip
            self.assertEqual(code, 0, rec.get("problem"))
            pin = config.load(d).infra
            self.assertEqual((pin.config_release, pin.config_digest, pin.config_digest_kind),
                             ("2026.01.1", digests["2026.01.1"], "release-tree"))  # fmt: skip
            self.assertEqual(rec["infra"]["action"], "installed")
            self.assertFalse(Path(rec["infra"]["store"]).is_relative_to(d.resolve()))
            after = tree(d)
            again, code = self.install(d, infra_source="example-org/infra")
            self.assertEqual((code, again["infra"]["action"], tree(d)), (0, "present", after))
        missing, code = self.install(d)  # no source: only an already-held release satisfies the pin
        self.assertEqual((code, missing["infra"]["action"]), (0, "present"))

    def test_a_pinned_infra_release_that_is_not_installed_is_unsatisfied(self):
        d = self.python_project()
        self.install(d, version="0.8.9", profile="py")
        text = (d / "dev-platform.toml").read_text()
        pin = {"provider": "p", "config_release": "2026.01.1", "config_digest": "sha256:" + "9" * 64,
               "config_digest_kind": "release-tree"}  # fmt: skip
        (d / "dev-platform.toml").write_text(pinning.apply(text, infra=pinning.infra_block(pin)))
        rec, code = self.install(d)
        self.assertEqual(code, 1)
        self.assertEqual(rec["infra"]["action"], "missing")
        self.assertIn("--infra-source", rec["problem"])


class VerificationIsReadOnly(unittest.TestCase):
    def test_doctor_explain_and_check_leave_the_project_tree_unchanged(self):
        store, _ = make_store(self)
        proj = tmpdir(self) / "p"
        shutil.copytree(ROOT / "fixtures" / "python-only", proj)
        self.assertEqual(
            run(proj, store, "init", "--platform-version", "0.1.0", "--profile", "py").returncode, 0
        )
        before, bytes_before = snapshot(proj), tree(proj)
        for argv in (("doctor",), ("explain", "--changed", "app.py"), ("check", "--changed", "app.py"),
                     ("check", "--stage", "full", "--changed", "app.py")):  # fmt: skip
            r = run(proj, store, *argv)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(tree(proj), bytes_before, argv)
            self.assertEqual(changed(before, snapshot(proj)), {}, argv)  # modes, mtimes and links too

    def test_consumer_commands_leave_git_metadata_untouched(self):
        """A stale index is the case where `git status` would rewrite .git/index: the engine's git calls must not."""
        store, _ = make_store(self)
        proj = tmpdir(self) / "p"
        shutil.copytree(ROOT / "fixtures" / "python-only", proj)
        self.assertEqual(
            run(proj, store, "init", "--platform-version", "0.1.0", "--profile", "py").returncode, 0
        )
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        for argv in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "i"]):
            subprocess.run([*git, *argv], cwd=proj, check=True, capture_output=True, env=env)
        os.utime(proj / "app.py", (1_000_000_000, 1_000_000_000))  # the index now holds stale stat data
        before = snapshot(proj)
        for argv in (("doctor",), ("explain", "--base", "HEAD"), ("check", "--base", "HEAD"),
                     ("check", "--staged"), ("check", "--stage", "full")):  # fmt: skip
            r = run(proj, store, *argv)
            self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
            self.assertEqual(changed(before, snapshot(proj)), {}, argv)  # .git included


if __name__ == "__main__":
    unittest.main()
