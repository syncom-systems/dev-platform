"""Installation contract of repository isolation (ADR 0027): explicit versions, independently verified infrastructure
digests, `[infra].source` as a convenience and never an authority, migration of pre-0.17 pins, and legacy
repository files that are reported and never read, changed or deleted.

Every case compares the whole project tree before and after (bytes, modes, timestamps, links), not `git status`.
"""

import json
import tomllib
import unittest
from unittest import mock

from dev_platform import (
    __version__,
    config,
    identity,
    infra_store,
    legacy,
    pinning,
    project_install,
    projectsetup,
)
from dev_platform.errors import ConfigError
from tests import infra_fixtures as F
from tests.helpers import tmpdir
from tests.repo_snapshot import changed, snapshot
from tests.test_project_install import IDENT, REV, InstallBase, gh_runner

SRC = "example-org/infra"
LEGACY_TOML = """\
# project-owned: keep this comment
schema_version = 1

[platform]
version = "0.14.0"
sha256 = "{tree}"
profile = "py"

[project]
name = "consumer"          # keep me
assurance = "standard"
languages = ["python"]

[impact]
global = ["pyproject.toml", "dev-platform.toml"]

[[check]]
id = "unit"
adapter = "exec"
argv = ["true"]
stages = ["pre-merge", "full"]
obligation = "always"
"""
LEGACY_FILES = {
    "dev-platform.release-pins.json": json.dumps({"version": "0.14.0"}),
    ".dev-platform/infra-profile.json": json.dumps({"schema": "dev-platform.infra/v1", "runners": []}),
    "dev-platform/generated.json": "{}",
    "dev-platform/BUILD.bazel": "# generated\n",
    "MODULE.bazel": 'module(name = "x")\ninclude("//dev-platform:toolchains.MODULE.bazel")\n',
    ".bazelrc": "import %workspace%/dev-platform/bazel.bazelrc\nbuild --jobs=4\n",
    "README.md": "hello\n",
    "src/app.py": "print('hi')\n",
}


class Versions(InstallBase):
    def setUp(self):
        super().setUp()
        self.d = self.python_project()
        self.cfgrepo = tmpdir(self) / "cfg"
        self.digests = F.config_repo(self.cfgrepo, versions=("2026.01.1",))
        self.good = self.digests["2026.01.1"]
        self.fake = lambda repo, ref, version=None, runner=None: infra_store.from_directory(
            self.cfgrepo, version
        )

    def infra_install(self, **kw):
        args = dict(version="0.8.9", profile="py", infra_source=SRC, infra_release="2026.01.1",
                    infra_provider="example-infra", infra_digest=self.good)  # fmt: skip
        args.update(kw)
        with mock.patch.object(infra_store, "from_github", self.fake):
            return self.install(self.d, **args)

    def assertNothingWritten(self, before):
        self.assertEqual(changed(before, snapshot(self.d)), {})

    # --- the platform version is explicit and distinct from the bootstrap CLI ---
    def test_a_first_installation_requires_an_explicit_version(self):
        before = snapshot(self.d)
        with self.assertRaises(ConfigError) as e:
            self.install(self.d, profile="py")
        self.assertIn("--version", str(e.exception))
        self.assertIn(__version__, str(e.exception))  # names the CLI it will not default to
        self.assertNothingWritten(before)

    def test_the_cli_version_is_never_the_default_even_when_the_release_exists(self):
        before = snapshot(self.d)
        with mock.patch.object(pinning, "platform_identity") as ident, self.assertRaises(ConfigError):
            self.install(self.d, profile="py")
        ident.assert_not_called()  # nothing was even looked up for the CLI's own version
        self.assertNothingWritten(before)

    def test_dry_run_distinguishes_the_bootstrap_cli_from_the_release_that_executes(self):
        before = snapshot(self.d)
        rec, code = self.install(self.d, version="0.8.9", profile="py", dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(rec["bootstrap_cli"]["version"], __version__)
        self.assertEqual(rec["executes_release"]["version"], "0.8.9")
        self.assertEqual(rec["executes_release"]["tree_digest"], self.tree)
        lines = "\n".join(project_install._text_identity(rec))
        self.assertIn(f"bootstrap CLI   dev-platform {__version__}", lines)
        self.assertIn("executes        release 0.8.9", lines)
        self.assertNotEqual(__version__, "0.8.9")
        self.assertNothingWritten(before)

    def test_existing_pins_are_preserved_unless_an_explicit_update_is_approved(self):
        self.install(self.d, version="0.8.9", profile="py")
        pinned = snapshot(self.d)
        rec, code = self.install(self.d)  # no version: whatever is pinned, unchanged
        self.assertEqual((code, rec["executes_release"]["version"], rec["bootstrap_cli"]["version"]),
                         (0, "0.8.9", __version__))  # fmt: skip
        self.assertNothingWritten(pinned)
        for kw in (dict(version="0.8.10"), dict(profile="other"), dict(infra_release="2026.01.1")):
            with self.assertRaises(projectsetup.Refused):
                self.install(self.d, **kw)
            self.assertNothingWritten(pinned)

    # --- the infrastructure release is verified against an independently supplied digest ---
    def test_an_infra_release_needs_an_independent_digest(self):
        before = snapshot(self.d)
        with self.assertRaises(ConfigError) as e:
            self.infra_install(infra_digest=None)
        self.assertIn("--infra-digest", str(e.exception))
        self.assertNothingWritten(before)

    def test_a_wrong_digest_is_refused_whatever_the_source_says(self):
        before = snapshot(self.d)
        for bad in ("sha256:" + "1" * 64, "sha256:" + "G" * 64, self.good.upper(), "e" * 64, "latest"):
            with self.assertRaises(ConfigError, msg=bad):
                self.infra_install(infra_digest=bad)
            self.assertNothingWritten(before)

    def test_a_source_whose_index_disagrees_with_the_supplied_digest_is_refused(self):
        index = self.cfgrepo / "releases" / "index.v1.json"
        doc = json.loads(index.read_text())
        doc["releases"][0]["digest"] = "1" * 64  # the received tree is right, the (mutable) index lies
        index.write_text(json.dumps(doc))
        before = snapshot(self.d)
        with self.assertRaises(ConfigError) as e:
            self.infra_install()
        self.assertIn("another digest", str(e.exception))
        self.assertNothingWritten(before)

    def test_a_tampered_release_does_not_match_the_supplied_digest(self):
        release = self.cfgrepo / "releases" / "2026.01.1" / "profiles" / "app.json"
        release.chmod(0o644)
        release.write_text(release.read_text() + " ")
        before = snapshot(self.d)
        with self.assertRaises(ConfigError):
            self.infra_install()
        self.assertNothingWritten(before)

    def test_a_release_of_another_contract_is_refused(self):
        index = self.cfgrepo / "releases" / "index.v1.json"
        doc = json.loads(index.read_text())
        doc["releases"][0]["contract"] = "dev-platform.infra/v2"
        index.write_text(json.dumps(doc))
        before = snapshot(self.d)
        with self.assertRaises(ConfigError):
            self.infra_install()
        self.assertNothingWritten(before)

    def test_an_unlisted_release_is_refused(self):
        before = snapshot(self.d)
        with self.assertRaises(ConfigError):
            self.infra_install(infra_release="2026.01.2")
        self.assertNothingWritten(before)

    def test_the_pin_records_the_supplied_digest_and_the_source(self):
        rec, code = self.infra_install()
        self.assertEqual(code, 0, rec.get("problem"))
        pin = config.load(self.d).infra
        self.assertEqual(
            (pin.config_digest, pin.source, pin.config_digest_kind), (self.good, SRC, "release-tree")
        )
        text = (self.d / "dev-platform.toml").read_text()
        self.assertIn(f'source = "{SRC}"', text)
        self.assertEqual(rec["infra"]["action"], "installed")

    def test_update_needs_the_same_independent_digest(self):
        self.infra_install()
        before = snapshot(self.d)
        with self.assertRaises(ConfigError) as e:
            project_install.propose(self.d, infra_release="2026.01.1")
        self.assertIn("--infra-digest", str(e.exception))
        self.assertNothingWritten(before)
        with mock.patch.object(infra_store, "from_github", self.fake):
            with self.assertRaises(ConfigError):
                project_install.propose(self.d, infra_release="2026.01.1", infra_digest="sha256:" + "2" * 64)
            self.assertNothingWritten(before)
            rec = project_install.propose(self.d, infra_release="2026.01.1", infra_digest=self.good)
        self.assertFalse(rec["changed"])  # source, provider and digest come from the existing pin

    # --- [infra].source ---
    def test_source_is_a_valid_optional_key_and_is_never_part_of_identity(self):
        base = {"provider": "p", "config_release": "1.0.0", "config_digest": "sha256:" + "a" * 64}

        def parse(extra):
            errs: list[str] = []
            return config.parse_pin({**base, **extra}, errs), errs

        self.assertEqual(
            parse({"source": SRC}), (config.InfraPin("p", "1.0.0", "sha256:" + "a" * 64, None, SRC), [])
        )
        self.assertIsNone(parse({})[0].source)
        for bad in ("nope", "a/b/c", "/x", "a/", 5, ""):
            pin, errs = parse({"source": bad})
            self.assertIsNone(pin, bad)
            self.assertTrue(any("infra.source" in e for e in errs), bad)
        self.assertTrue(any("unknown key" in e for e in parse({"mirror": "x"})[1]))
        # identity: adding a source changes no result's evidence identity
        text = (
            'schema_version = 1\n[platform]\nversion = "0.17.0"\nsha256 = "'
            + "a" * 64
            + '"\nprofile = "py"\n'
            '[project]\nname = "t"\n[[check]]\nid = "c"\nadapter = "exec"\nargv = ["true"]\n'
            'stages = ["pre-merge", "full"]\nobligation = "always"\n[infra]\nprovider = "p"\nconfig_release = "1.0.0"\n'
            'config_digest = "sha256:' + "a" * 64 + '"\n'
        )
        digests = []
        for extra in ("", f'source = "{SRC}"\n'):
            cfg = config.parse(tomllib.loads(text + extra))
            digests.append(
                identity.compute(cfg, cfg.checks[0], {"global": "g", "inputs": "i"}, platform={"v": 1},
                                 environment={"identity_digest": "e" * 64}, execution={}, exec_env=None,
                                 runner=None)["digest"]
            )  # fmt: skip
        self.assertEqual(digests[0], digests[1])
        self.assertTrue(digests[0])

    def test_a_source_only_says_where_never_whether_to_trust(self):
        self.infra_install()
        # a source that serves different bytes cannot satisfy the pinned digest
        index = self.cfgrepo / "releases" / "index.v1.json"
        doc = json.loads(index.read_text())
        doc["releases"][0]["digest"] = "3" * 64
        index.write_text(json.dumps(doc))
        other = self.d.parent / "second"
        other.mkdir()
        (other / "README.md").write_text("x")
        # the held, verified release is used as is; the changed source is not consulted by install
        rec, code = self.install(self.d)
        self.assertEqual((code, rec["infra"]["action"]), (0, "present"))


class Migration(InstallBase):
    """From a pre-0.17 pin (toml without identity, release-pins.json, Bazel files, vendored profile) to the single
    pin file: `update --to` writes dev-platform.toml and nothing else."""

    def setUp(self):
        super().setUp()
        self.patch.stop()  # the real identity lookup, through a fake gh that serves the 0.17.0 record

    def make_legacy(self, infra: str = ""):
        d = tmpdir(self).resolve() / "legacy"
        for rel, text in LEGACY_FILES.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(text)
        (d / "dev-platform.toml").write_text(LEGACY_TOML.format(tree="9" * 64) + infra)
        return d

    GH = staticmethod(lambda: gh_runner(IDENT, REV))

    def test_migration_writes_only_the_pin_file_and_keeps_project_configuration(self):
        d = self.make_legacy()
        before = snapshot(d)
        old = (d / "dev-platform.toml").read_text()
        rec = project_install.propose(d, to="0.17.0", gh=self.GH())  # a proposal first
        self.assertTrue(rec["changed"])
        self.assertFalse(rec["written"])
        self.assertEqual(changed(before, snapshot(d)), {})
        self.assertEqual(rec["migration"], {"from": "0.14.0", "to": "0.17.0", "writes": ["dev-platform.toml"],
                         "kept": "every other line of dev-platform.toml and every other file of the project"})  # fmt: skip
        rec = project_install.propose(d, to="0.17.0", write=True, gh=self.GH())
        self.assertTrue(rec["written"])
        self.assertEqual(set(changed(before, snapshot(d))), {"dev-platform.toml"})
        new = (d / "dev-platform.toml").read_text()
        # project-owned configuration, comments included, is preserved byte for byte
        for keep in ("# project-owned: keep this comment", 'name = "consumer"          # keep me',
                     'global = ["pyproject.toml", "dev-platform.toml"]', 'id = "unit"', 'obligation = "always"'):  # fmt: skip
            self.assertIn(keep, new)
        self.assertEqual(old[old.index("[project]") :], new[new.index("[project]") :])
        cfg = config.load(d)
        self.assertEqual((cfg.platform.version, cfg.platform.profile, cfg.platform.source_revision),
                         ("0.17.0", "py", REV))  # fmt: skip
        self.assertEqual(cfg.platform.sha256, IDENT["tree_digest_pin"])

    def test_after_migration_the_toml_alone_is_the_pin_and_legacy_files_are_never_read(self):
        d = self.make_legacy()
        project_install.propose(d, to="0.17.0", write=True, gh=self.GH())
        (d / "dev-platform.release-pins.json").write_text("this is not json {")  # a corrupt legacy file
        _cfg, pins = projectsetup.read_pins(d)
        self.assertEqual((pins["version"], pins["source_revision"]), ("0.17.0", REV))
        self.assertEqual(pins["tree_digest_pin"], IDENT["tree_digest_pin"])

    def test_migration_is_idempotent_and_survives_a_second_update(self):
        d = self.make_legacy()
        project_install.propose(d, to="0.17.0", write=True, gh=self.GH())
        once = snapshot(d)
        again = project_install.propose(d, to="0.17.0", write=True, gh=self.GH())
        self.assertFalse(again["changed"])
        self.assertNotIn("migration", again)  # already migrated
        self.assertEqual(changed(once, snapshot(d)), {})

    def test_migration_keeps_an_existing_infra_pin(self):
        infra = ('\n[infra]\nprovider = "example-infra"\nconfig_release = "2026.01.1"\n'
                 'config_digest = "sha256:' + "5" * 64 + '"\nconfig_digest_kind = "release-tree"\n')  # fmt: skip
        d = self.make_legacy(infra)
        project_install.propose(d, to="0.17.0", write=True, gh=self.GH())
        pin = config.load(d).infra
        self.assertEqual((pin.provider, pin.config_release, pin.config_digest, pin.config_digest_kind),
                         ("example-infra", "2026.01.1", "sha256:" + "5" * 64, "release-tree"))  # fmt: skip

    def test_migration_needs_an_explicit_target_and_never_targets_an_older_release(self):
        d = self.make_legacy()
        before = snapshot(d)
        with self.assertRaises(ConfigError) as e:
            project_install.propose(d, profile="py", gh=self.GH())
        self.assertIn("predates repository isolation", str(e.exception))
        self.assertIn("--to", str(e.exception))
        for older in ("0.14.0", "0.16.2", "0.15.0"):
            with self.assertRaises(ConfigError, msg=older):
                project_install.propose(d, to=older, write=True, gh=self.GH())
        self.assertEqual(changed(before, snapshot(d)), {})

    def test_a_symlinked_pin_file_is_refused_and_its_target_untouched(self):
        d = self.make_legacy()
        elsewhere = tmpdir(self) / "elsewhere.toml"
        elsewhere.write_text(LEGACY_TOML.format(tree="9" * 64))
        (d / "dev-platform.toml").unlink()
        (d / "dev-platform.toml").symlink_to(elsewhere)
        with self.assertRaises(ConfigError) as e:
            project_install.propose(d, to="0.17.0", write=True, gh=self.GH())
        self.assertIn("symbolic link", str(e.exception))
        self.assertEqual(elsewhere.read_text(), LEGACY_TOML.format(tree="9" * 64))

    def test_legacy_integration_is_reported_and_never_changed_or_deleted(self):
        d = self.make_legacy()
        before = snapshot(d)
        found = {f["path"] for f in legacy.integration_files(d)}
        self.assertEqual(found, {"dev-platform.release-pins.json", ".dev-platform/infra-profile.json",
                                 "dev-platform/", "MODULE.bazel", ".bazelrc"})  # fmt: skip
        rec = project_install.propose(d, to="0.17.0", gh=self.GH())
        self.assertEqual({f["path"] for f in rec["legacy_integration"]}, found)
        self.assertEqual(changed(before, snapshot(d)), {})
        project_install.propose(d, to="0.17.0", write=True, gh=self.GH())
        for rel in LEGACY_FILES:  # after writing the pin file every legacy file is still there, unchanged
            self.assertEqual((d / rel).read_text(), LEGACY_FILES[rel], rel)
        self.assertEqual(
            legacy.integration_files(self.python_project()), []
        )  # a clean project reports nothing


class LegacyReports(InstallBase):
    """Projects installed with a release before the migration: setup reports legacy files, never touches them."""

    def test_setup_reports_legacy_files_and_leaves_them_alone(self):
        d = self.python_project()
        for rel in (".dev-platform/infra-profile.json", "dev-platform.release-pins.json"):
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text("{}")
        self.install(d, version="0.8.9", profile="py")
        before = snapshot(d)
        rec, code = self.install(d)
        self.assertEqual(code, 0, rec.get("problem"))
        self.assertEqual({f["path"] for f in rec["legacy_integration"]},
                         {"dev-platform.release-pins.json", ".dev-platform/infra-profile.json"})  # fmt: skip
        self.assertIn("legacy     .dev-platform/infra-profile.json", projectsetup.render(rec))
        self.assertEqual(rec["project"]["files"], ["dev-platform.toml"])  # the toml alone is the pin
        self.assertEqual(changed(before, snapshot(d)), {})

    def test_a_project_still_pinned_before_0_17_keeps_working_from_its_pins_file(self):
        """Not migrated yet: `setup` still reads the legacy pins file (never writes it), per ADR 0027 §1."""
        d = self.python_project()
        (d / "dev-platform.toml").write_text(
            LEGACY_TOML.format(tree=self.tree).replace('version = "0.14.0"', 'version = "0.8.9"')
        )
        vp = self.pins["verifier_pins"]
        (d / "dev-platform.release-pins.json").write_text(json.dumps({
            "version": "0.8.9", "source_revision": self.pins["source_revision"], "archive_sha256": "b" * 64,
            "tree_digest_pin": self.tree,
            "verifier_pins": {"verify_release.py_sha256": vp["verify_release"],
                              "trust_policy_sha256": vp["trust_policy"],
                              "install_release.py_sha256": vp["install_release"]},
        }))  # fmt: skip
        before = snapshot(d)
        rec, code = self.install(d)
        self.assertEqual(code, 0, rec.get("problem"))
        self.assertIn("dev-platform.release-pins.json", rec["project"]["files"])
        self.assertEqual(changed(before, snapshot(d)), {})


class LegacyProfile(unittest.TestCase):
    def test_doctor_no_longer_takes_a_vendored_profile_from_the_repository(self):
        d = tmpdir(unittest.TestCase())
        (d / ".dev-platform").mkdir(parents=True)
        (d / ".dev-platform" / "infra-profile.json").write_text("{}")
        calls = []

        def run(argv, **kw):
            calls.append(argv)
            import subprocess

            return subprocess.CompletedProcess(argv, 0, json.dumps({"findings": []}), "")

        before = snapshot(d)
        projectsetup.doctor(d, None, {}, run)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("--infra-profile", calls[0])
        self.assertEqual(changed(before, snapshot(d)), {})


if __name__ == "__main__":
    unittest.main()
