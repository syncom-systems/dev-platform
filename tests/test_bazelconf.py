"""The platform-owned Bazel configuration: rendering from the manifest, materialization, conflict detection."""

import json
import re
import unittest

from dev_platform import bazelconf as B
from dev_platform import toolchain as T
from dev_platform.errors import ConfigError
from tests.helpers import ROOT, tmpdir

MANIFEST = T.validate(json.loads((ROOT / "toolchains" / "manifest.json").read_text()))
VERSION = "9.9.9"
MIXED, RUST, PYTHON = "rust-python-bazel-9.3", "rust-bazel-9.3", "python-bazel-9.3"


def render(profile=MIXED):
    return B.render(MANIFEST, profile, VERSION)


def project(testcase, profile=MIXED, hooks=True):
    root = tmpdir(testcase)
    if hooks:
        (root / "MODULE.bazel").write_text(f'module(name = "p")\n{B.MODULE_HOOK}\n')
        (root / ".bazelrc").write_text(f"{B.BAZELRC_HOOK}\n")
    (root / ".bazelversion").write_text(MANIFEST["profiles"][profile]["tools"]["bazel"]["version"] + "\n")
    return root


def materialized(testcase, profile=MIXED):
    root = project(testcase, profile)
    B.materialize(MANIFEST, profile, root, VERSION)
    return root


def kinds(rec):
    return sorted({(c["kind"], c["path"]) for c in rec["conflicts"]})


class Rendering(unittest.TestCase):
    def test_only_the_languages_of_the_profile_are_rendered(self):
        rust, python = set(render(RUST)), set(render(PYTHON))
        self.assertIn("rustfmt.toml", rust)
        self.assertNotIn("ruff.toml", rust)
        self.assertNotIn("dev-platform/python_lock.txt", rust)
        self.assertIn("ruff.toml", python)
        self.assertNotIn("rustfmt.toml", python)
        self.assertNotIn("dev-platform/rust.bzl", python)
        self.assertEqual(set(render(MIXED)), rust | python)

    def test_rendering_is_deterministic_and_every_file_declares_its_origin(self):
        a, b = render(), render()
        self.assertEqual(a, b)
        self.assertEqual(B.digest(a), B.digest(b))
        for rel, text in a.items():
            if rel.endswith("generated.json"):
                continue
            self.assertTrue(text.startswith(B.MARK + VERSION + " for profile " + MIXED), rel)
        self.assertNotIn("@@", "".join(a.values()))

    def test_the_release_and_profile_change_the_rendering(self):
        self.assertNotEqual(B.digest(render()), B.digest(B.render(MANIFEST, MIXED, "9.9.8")))
        self.assertNotEqual(B.digest(render(MIXED)), B.digest(render(RUST)))

    def test_versions_urls_and_hashes_come_from_the_manifest(self):
        tools = MANIFEST["profiles"][MIXED]["tools"]
        module = render()["dev-platform/toolchains.MODULE.bazel"]
        self.assertIn(f'versions = ["{tools["rust-toolchain"]["version"]}"]', module)
        self.assertIn(f'python_version = "{tools["python"]["version"]}"', module)
        self.assertIn(f'edition = "{MANIFEST["profiles"][MIXED]["bazel"]["edition"]}"', module)
        for key in B.PLATFORMS:
            self.assertIn(tools["python"]["source"][key]["sha256"], module)
            self.assertIn(tools["python"]["source"][key]["url"], module)
            self.assertIn(tools["ruff"]["source"][key]["sha256"], module)
            for comp in tools["rust-dev"]["source"][key]["components"]:
                self.assertIn(f'"{comp["archive"]}": "{comp["sha256"]}"', module)

    def test_rules_modules_are_the_versions_the_integrity_entries_pin(self):
        tools = MANIFEST["profiles"][MIXED]["tools"]
        module = render()["dev-platform/toolchains.MODULE.bazel"]
        for tool, name in (("rust-toolchain", "rules_rust"), ("python-runtime", "rules_python")):
            v = B._module_version(tools[tool], name)
            self.assertIn(f'bazel_dep(name = "{name}", version = "{v}")', module)
            # the form the existing module-integrity check reads
            self.assertTrue(
                re.search(rf'bazel_dep\(\s*name\s*=\s*"{name}"\s*,\s*version\s*=\s*"{v}"', module), name
            )

    def test_declared_tool_versions_are_read_back_from_the_generated_files(self):
        files = render()
        for name, spec in MANIFEST["profiles"][MIXED]["tools"].items():
            decl = spec.get("declared_in")
            if not spec.get("bazel_managed") or decl["file"] == ".bazelversion":
                continue
            m = re.search(decl["pattern"], files[decl["file"]])
            self.assertIsNotNone(m, name)
            self.assertEqual(m.group(1), spec["version"], name)

    def test_the_python_lock_pins_what_the_manifest_declares_and_every_requirement_is_hashed(self):
        lock = render()["dev-platform/python_lock.txt"]
        for name in ("pytest", "pytest-cov", "coverage", "mypy"):
            self.assertIn(f"{name}=={MANIFEST['profiles'][MIXED]['tools'][name]['version']}", lock)
        for block in re.split(r"\n(?=[A-Za-z])", lock):
            if re.match(r"[A-Za-z0-9_.-]+==", block):
                self.assertIn("--hash=sha256:", block, block.splitlines()[0])

    def test_the_edition_is_one_value_everywhere(self):
        edition = MANIFEST["profiles"][MIXED]["bazel"]["edition"]
        files = render()
        self.assertIn(f'edition = "{edition}"', files["rustfmt.toml"])
        self.assertIn(f'EDITION = "{edition}"', files["dev-platform/rust.bzl"])

    def test_bazel_only_rust_components_are_pinned_but_not_installed_on_the_host(self):
        src = MANIFEST["profiles"][MIXED]["tools"]["rust-dev"]["source"]["darwin-arm64"]["components"]
        bazel_only = {c["archive"].split("-1.")[0] for c in src if c.get("bazel_only")}
        self.assertEqual(bazel_only, {"cargo", "llvm-tools"})
        module = render()["dev-platform/toolchains.MODULE.bazel"]
        self.assertIn('"cargo-1.99.1-aarch64-apple-darwin.tar.xz"', module)

    def test_a_profile_that_cannot_be_rendered_is_refused(self):
        bad = json.loads(json.dumps(MANIFEST))
        del bad["profiles"][MIXED]["tools"]["ruff"]
        with self.assertRaises(ConfigError) as e:
            B.render(bad, MIXED, VERSION)
        self.assertIn("ruff", "\n".join(e.exception.problems))
        bad = json.loads(json.dumps(MANIFEST))
        bad["profiles"][MIXED]["bazel"]["edition"] = "1999"
        with self.assertRaises(ConfigError):
            T.validate(bad)


class Materialize(unittest.TestCase):
    def test_a_fresh_project_is_materialized_and_then_conformant(self):
        root = project(self, hooks=False)
        before = B.check(MANIFEST, MIXED, root, VERSION)
        self.assertEqual(before["status"], "mismatch")
        self.assertEqual(kinds(before)[0], ("hook", ".bazelrc"))
        self.assertIn(("missing", "dev-platform/"), kinds(before))
        rep = B.materialize(MANIFEST, MIXED, root, VERSION, add_hooks=True)
        self.assertEqual(rep["refused"], [])
        after = B.check(MANIFEST, MIXED, root, VERSION)
        self.assertEqual(after["status"], "ok", after["conflicts"])
        self.assertEqual(after["digest"], B.digest(render()))

    def test_materializing_twice_changes_nothing(self):
        root = materialized(self)
        rep = B.materialize(MANIFEST, MIXED, root, VERSION)
        self.assertEqual(rep["written"], [])
        self.assertEqual(len(rep["unchanged"]), len(render()))

    def test_project_owned_files_are_never_touched_without_the_hook_flag(self):
        root = project(self, hooks=False)
        (root / "MODULE.bazel").write_text('module(name = "mine")\n')
        (root / ".bazelrc").write_text("build --jobs=4\n")
        B.materialize(MANIFEST, MIXED, root, VERSION)
        self.assertEqual((root / "MODULE.bazel").read_text(), 'module(name = "mine")\n')
        self.assertEqual((root / ".bazelrc").read_text(), "build --jobs=4\n")

    def test_the_hook_flag_appends_and_never_rewrites(self):
        root = project(self, hooks=False)
        (root / "MODULE.bazel").write_text('module(name = "mine")\n\nbazel_dep(name = "x", version = "1")')
        (root / ".bazelrc").write_text("build --jobs=4\n")
        rep = B.materialize(MANIFEST, MIXED, root, VERSION, add_hooks=True)
        self.assertEqual(sorted(rep["added_hooks"]), [".bazelrc", "MODULE.bazel"])
        self.assertEqual(
            (root / "MODULE.bazel").read_text(),
            f'module(name = "mine")\n\nbazel_dep(name = "x", version = "1")\n{B.MODULE_HOOK}\n',
        )
        self.assertEqual((root / ".bazelrc").read_text(), f"build --jobs=4\n{B.BAZELRC_HOOK}\n")
        again = B.materialize(MANIFEST, MIXED, root, VERSION, add_hooks=True)
        self.assertEqual(again["added_hooks"], [])

    def test_missing_entry_files_are_created_only_when_asked(self):
        root = tmpdir(self)
        B.materialize(MANIFEST, MIXED, root, VERSION, add_hooks=True)
        self.assertIn(B.MODULE_HOOK, (root / "MODULE.bazel").read_text())
        self.assertTrue((root / "MODULE.bazel").read_text().startswith("module(name ="))
        self.assertEqual((root / ".bazelversion").read_text().strip(), "9.3.1")

    def test_create_hooks_wires_a_new_project_but_never_edits_an_existing_file(self):
        fresh = tmpdir(self)
        B.materialize(MANIFEST, MIXED, fresh, VERSION, create_hooks=True)
        self.assertIn(B.MODULE_HOOK, (fresh / "MODULE.bazel").read_text())
        self.assertIn(B.BAZELRC_HOOK, (fresh / ".bazelrc").read_text())
        owned = tmpdir(self)
        (owned / "MODULE.bazel").write_text('module(name = "p")\n')
        rep = B.materialize(MANIFEST, MIXED, owned, VERSION, create_hooks=True)
        self.assertEqual(rep["added_hooks"], [".bazelrc"])
        self.assertEqual((owned / "MODULE.bazel").read_text(), 'module(name = "p")\n')
        hooks = [c for c in B.check(MANIFEST, MIXED, owned, VERSION)["conflicts"] if c["kind"] == "hook"]
        self.assertEqual([c["path"] for c in hooks], ["MODULE.bazel"])

    def test_ruff_targets_the_pinned_python_minor(self):
        text = B.render(MANIFEST, PYTHON, VERSION)["ruff.toml"]
        minor = MANIFEST["profiles"][PYTHON]["tools"]["python"]["version"].split(".")[:2]
        self.assertIn(f'target-version = "py{minor[0]}{minor[1]}"', text)

    def test_an_existing_bazelversion_is_never_rewritten(self):
        root = project(self, hooks=False)
        (root / ".bazelversion").write_text("8.0.0\n")
        B.materialize(MANIFEST, MIXED, root, VERSION)
        self.assertEqual((root / ".bazelversion").read_text(), "8.0.0\n")

    def test_a_foreign_file_blocks_materialization_and_nothing_is_written(self):
        root = project(self)
        (root / "ruff.toml").write_text("line-length = 79\n")
        rep = B.materialize(MANIFEST, MIXED, root, VERSION)
        self.assertEqual([c["path"] for c in rep["refused"]], ["ruff.toml"])
        self.assertEqual(rep["written"], [])
        self.assertFalse((root / "dev-platform").exists())
        self.assertEqual((root / "ruff.toml").read_text(), "line-length = 79\n")

    def test_dry_run_writes_nothing(self):
        root = project(self)
        rep = B.materialize(MANIFEST, MIXED, root, VERSION, dry_run=True)
        self.assertTrue(rep["written"])
        self.assertFalse((root / "dev-platform").exists())

    def test_a_file_generated_by_an_older_release_is_updated_not_refused(self):
        root = project(self)
        B.materialize(MANIFEST, MIXED, root, "9.9.8")
        self.assertEqual(B.check(MANIFEST, MIXED, root, VERSION)["status"], "mismatch")
        rep = B.materialize(MANIFEST, MIXED, root, VERSION)
        self.assertEqual(rep["refused"], [])
        self.assertEqual(B.check(MANIFEST, MIXED, root, VERSION)["status"], "ok")


class Conflicts(unittest.TestCase):
    def check(self, root, profile=MIXED):
        return B.check(MANIFEST, profile, root, VERSION)

    def test_an_edited_generated_file_is_stale(self):
        root = materialized(self)
        f = root / "dev-platform" / "lint.bzl"
        f.write_text(f.read_text() + "# local tweak\n")
        rec = self.check(root)
        self.assertEqual(rec["status"], "mismatch")
        self.assertEqual(kinds(rec), [("stale", "dev-platform/lint.bzl")])

    def test_a_deleted_generated_file_is_missing(self):
        root = materialized(self)
        (root / "dev-platform" / "coveragerc").unlink()
        self.assertEqual(kinds(self.check(root)), [("missing", "dev-platform/coveragerc")])

    def test_a_file_the_release_does_not_generate_is_unexpected(self):
        root = materialized(self)
        (root / "dev-platform" / "mine.bzl").write_text("x = 1\n")
        self.assertEqual(kinds(self.check(root)), [("unexpected", "dev-platform/mine.bzl")])

    def test_missing_entry_lines_are_reported_with_the_line_to_add(self):
        root = materialized(self)
        (root / "MODULE.bazel").write_text('module(name = "p")\n# ' + B.MODULE_HOOK + "\n")
        rec = self.check(root)
        self.assertEqual(kinds(rec), [("hook", "MODULE.bazel")])
        self.assertIn(B.MODULE_HOOK, rec["conflicts"][0]["action"])

    def test_independent_rust_and_python_declarations_conflict(self):
        root = materialized(self)
        (root / "MODULE.bazel").write_text(
            f"""module(name = "p")
{B.MODULE_HOOK}
bazel_dep(name = "rules_rust", version = "0.60.0")
bazel_dep(name = "rules_python", version = "1.0.0")
rust = use_extension("@rules_rust//rust:extensions.bzl", "rust")
rust.toolchain(versions = ["1.80.0"])
python = use_extension("@rules_python//python/extensions:python.bzl", "python")
python.toolchain(python_version = "3.12")
register_toolchains("@rust_toolchains//:all")
pip.parse(hub_name = "mine", python_version = "3.12", requirements_lock = "//:r.txt")
"""
        )
        what = {c["detail"] for c in self.check(root)["conflicts"]}
        self.assertTrue(
            {
                "declares rules_rust",
                "declares rules_python",
                "configures the Rust toolchain",
                "configures the Python toolchain",
                "registers a Rust toolchain",
            }
            <= what
        )
        self.assertTrue(any("python_version 3.12 differs" in w for w in what))

    def test_a_pip_hub_of_the_project_at_the_platform_python_is_not_a_conflict(self):
        root = materialized(self)
        v = MANIFEST["profiles"][MIXED]["tools"]["python"]["version"]
        (root / "MODULE.bazel").write_text(
            f'module(name = "p")\n{B.MODULE_HOOK}\npip.parse(hub_name = "pypi", python_version = "{v}")\n'
        )
        self.assertEqual(self.check(root)["status"], "ok")

    def test_comments_are_not_declarations(self):
        root = materialized(self)
        (root / "MODULE.bazel").write_text(
            f'module(name = "p")\n{B.MODULE_HOOK}\n# bazel_dep(name = "rules_rust", version = "1")\n'
        )
        self.assertEqual(self.check(root)["status"], "ok")

    def test_a_try_import_is_not_the_entry_line_and_the_hook_flag_adds_the_real_one(self):
        root = materialized(self)
        (root / ".bazelrc").write_text("try-import %workspace%/dev-platform/bazel.bazelrc\n")
        self.assertEqual(kinds(self.check(root)), [("hook", ".bazelrc")])
        B.materialize(MANIFEST, MIXED, root, VERSION, add_hooks=True)
        self.assertEqual(self.check(root)["status"], "ok")

    def test_independent_bazelrc_and_bazelisk_settings_conflict(self):
        root = materialized(self)
        (root / ".bazelrc").write_text(
            f"{B.BAZELRC_HOOK}\nbuild --@rules_rust//rust/settings:clippy_flags=-A,warnings\n"
            "build --@rules_python//python/config_settings:python_version=3.11\nbuild --extra_toolchains=//x:y\n"
        )
        (root / ".bazeliskrc").write_text("USE_BAZEL_VERSION=8.0.0\n")
        found = {c["detail"].split(" ")[0] for c in self.check(root)["conflicts"]}
        self.assertEqual(found, {"sets", "selects", "registers", "USE_BAZEL_VERSION"})

    def test_a_bazelisk_pin_equal_to_the_platform_version_is_not_a_conflict(self):
        root = materialized(self)
        (root / ".bazeliskrc").write_text("USE_BAZEL_VERSION=9.3.1\n")
        self.assertEqual(self.check(root)["status"], "ok")

    def test_tool_configuration_the_platform_owns_conflicts_wherever_it_is(self):
        root = materialized(self)
        (root / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "1.80.0"\n')
        (root / "sub").mkdir()
        (root / "sub" / "rustfmt.toml").write_text("max_width = 80\n")
        (root / "sub" / "mypy.ini").write_text("[mypy]\n")
        (root / ".python-version").write_text("3.11\n")
        (root / "pytest.ini").write_text("[pytest]\n")
        (root / ".tool-versions").write_text("rust 1.80.0\nnodejs 20\n")
        (root / "pyproject.toml").write_text(
            "[tool.ruff]\nline-length = 79\n[tool.black]\nline-length = 79\n"
        )
        (root / "tox.ini").write_text("[mypy]\nstrict = false\n")
        got = {c["path"] for c in self.check(root)["conflicts"]}
        self.assertEqual(
            got,
            {
                "rust-toolchain.toml",
                "sub/rustfmt.toml",
                "sub/mypy.ini",
                ".python-version",
                "pytest.ini",
                ".tool-versions",
                "pyproject.toml",
                "tox.ini",
            },
        )

    def test_a_pyproject_without_tool_policy_is_fine(self):
        root = materialized(self)
        (root / "pyproject.toml").write_text('[project]\nname = "x"\n[tool.black]\nline-length = 79\n')
        self.assertEqual(self.check(root)["status"], "ok")

    def test_only_the_profiles_languages_are_policed(self):
        root = materialized(self, RUST)
        (root / "ruff.toml").write_text("line-length = 79\n")
        (root / "mypy.ini").write_text("[mypy]\n")
        self.assertEqual(self.check(root, RUST)["status"], "ok")

    def test_build_outputs_and_the_platform_directory_are_not_scanned_for_strays(self):
        root = materialized(self)
        for d in ("bazel-out", ".devenv", ".git", "node_modules"):
            (root / d).mkdir()
            (root / d / "ruff.toml").write_text("x = 1\n")
        self.assertEqual(self.check(root)["status"], "ok")


class VerifiedAsPartOfTheEnvironment(unittest.TestCase):
    """Conformance judges the files against the release whose code runs: this one."""

    def setUp(self):
        from dev_platform import __version__

        self.version = __version__

    def materialize(self, profile=PYTHON):
        root = project(self, profile)
        B.materialize(MANIFEST, profile, root, self.version)
        return root

    def verify(self, root, profile=PYTHON):
        return T.verify_profile(MANIFEST, profile, root, probe=lambda argv: (0, "ruff 0.17.2 Python 3.15.1"))

    def entry(self, rec, name):
        return next(t for t in rec["tools"] if t["name"] == name)

    def test_the_configuration_is_one_item_of_the_environment_record(self):
        root = self.materialize()
        rec = self.verify(root)
        cfg = self.entry(rec, "bazel-config")
        self.assertEqual((cfg["status"], cfg["identity"]), ("ok", "config-locked"))
        self.assertEqual(cfg["observed"], cfg["expected"])
        for name in ("pytest", "pytest-cov", "coverage", "mypy"):
            t = self.entry(rec, name)
            self.assertEqual((t["status"], t["identity"]), ("ok", "config-locked"), name)

    def test_a_conflict_makes_the_environment_non_conformant_and_demotes_the_bound_tools(self):
        root = self.materialize()
        (root / "ruff.toml").write_text("line-length = 79\n")
        rec = self.verify(root)
        self.assertFalse(rec["conformant"])
        cfg = self.entry(rec, "bazel-config")
        self.assertEqual((cfg["status"], cfg["identity"]), ("mismatch", "none"))
        self.assertEqual(cfg["config"]["conflicts"][0]["kind"], "foreign")
        self.assertEqual(self.entry(rec, "pytest")["identity"], "bazel-declared")
        self.assertEqual(self.entry(rec, "bazel-config")["observed"], None)

    def test_the_configuration_changes_the_identity_of_the_environment(self):
        a = self.verify(self.materialize())
        root = self.materialize()
        f = root / "dev-platform" / "python.bzl"
        f.write_text(f.read_text() + "\n")
        b = self.verify(root)
        self.assertNotEqual(a["identity_digest"], b["identity_digest"])

    def test_setup_reports_the_conflicts_and_their_actions(self):
        from dev_platform import projectsetup

        root = self.materialize()
        self.assertEqual(projectsetup.config_problems(self.verify(root)), "")
        (root / "ruff.toml").write_text("line-length = 79\n")
        text = projectsetup.config_problems(self.verify(root))
        self.assertIn("foreign: ruff.toml", text)
        self.assertIn("never overwritten", text)

    def test_profiles_without_a_bazel_section_have_no_such_item(self):
        rec = T.verify_profile(MANIFEST, "rust-bazel-9", tmpdir(self), probe=lambda argv: (0, ""))
        self.assertNotIn("bazel-config", [t["name"] for t in rec["tools"]])

    def test_the_scope_states_what_the_configuration_evidence_does_not_cover(self):
        rec = self.verify(self.materialize())
        self.assertTrue(
            any("proven equal to what the pinned release generates" in x for x in rec["scope"]["limitations"])
        )


class Existing(unittest.TestCase):
    def test_existing_profiles_are_unchanged_by_the_baseline(self):
        """The baseline adds profiles only: nothing an established build selects has a Bazel section."""
        for name in (
            "dev-platform",
            "dev-platform-release",
            "python",
            "rust-bazel",
            "rust-cargo",
            "rust-cargo-1.99",
            "rust-bazel-9",
        ):
            self.assertNotIn("bazel", MANIFEST["profiles"][name], name)

    def test_the_new_profiles_are_exactly_the_baseline(self):
        got = {n for n, p in MANIFEST["profiles"].items() if "bazel" in p}
        self.assertEqual(got, {MIXED, RUST, PYTHON})
        t = MANIFEST["profiles"][MIXED]["tools"]
        self.assertEqual(
            {
                k: t[k]["version"]
                for k in ("bazel", "bazelisk", "python", "ruff", "rust-toolchain", "rust-dev")
            },
            {
                "bazel": "9.3.1",
                "bazelisk": "1.30.0",
                "python": "3.15.1",
                "ruff": "0.17.2",
                "rust-toolchain": "1.99.1",
                "rust-dev": "1.99.1",
            },
        )
        self.assertEqual(B._module_version(t["rust-toolchain"], "rules_rust"), "0.74.0")
        self.assertEqual(B._module_version(t["python-runtime"], "rules_python"), "2.4.5")

    def test_no_cargo_interface_is_installed_on_the_host(self):
        for key, src in MANIFEST["profiles"][MIXED]["tools"]["rust-dev"]["source"].items():
            host = [c for c in src["components"] if not c.get("bazel_only")]
            self.assertFalse(any(c["archive"].startswith("cargo-") for c in host), key)
            clippy = next(c for c in host if c["archive"].startswith("clippy-"))
            fmt = next(c for c in host if c["archive"].startswith("rustfmt-"))
            self.assertEqual(clippy["omit"], ["bin/cargo-clippy"])
            self.assertEqual(fmt["omit"], ["bin/cargo-fmt"])


if __name__ == "__main__":
    unittest.main()
