import tomllib
import unittest

from dev_platform.config import parse
from dev_platform.impact import matches, select
from dev_platform.model import Stage
from tests.helpers import cfg_text

CFG = parse(
    tomllib.loads(
        cfg_text(
            [
                ("lint", '["pre-commit", "pre-merge"]', "always", "[]"),
                ("unit", '["pre-merge", "full"]', "change", '["src/**", "tests/**"]'),
                ("proofs", '["pre-merge", "full"]', "change", '["kernel/**"]'),
                ("drift", '["full"]', "periodic", "[]"),
            ],
            extra='[impact]\nglobal = ["Cargo.lock", ".bazelrc"]\nignore = ["docs/**", "*.md"]\n',
        )
    )
)


def sel(stage, changed):
    return {s.check.id: s for s in select(CFG, stage, changed)}


class ImpactTest(unittest.TestCase):
    def test_glob(self):
        self.assertTrue(matches("src/a/b.py", ["src/**"]))
        self.assertTrue(matches("a/b/c.rs", ["**/*.rs"]))
        self.assertTrue(matches("c.rs", ["**/*.rs"]))
        self.assertFalse(matches("src/a/b.py", ["src/*.py"]))
        self.assertTrue(matches("docs/x/y", ["docs/"]))

    def test_reached_check_selected_with_reason(self):
        s = sel(Stage.PRE_MERGE, ("src/x.py",))
        self.assertTrue(s["unit"].selected)
        self.assertIn("src/x.py matches input src/**", s["unit"].reasons)
        self.assertFalse(s["proofs"].selected)  # provably unreached

    def test_always_obligation_always_selected(self):
        self.assertTrue(sel(Stage.PRE_MERGE, ())["lint"].selected)

    def test_unknown_change_set_selects_every_owed_check(self):
        s = sel(Stage.PRE_MERGE, None)
        self.assertTrue(all(s[i].selected for i in ("lint", "unit", "proofs")))
        self.assertNotIn("drift", s)  # not defined at this stage

    def test_unmapped_path_fails_closed(self):
        s = sel(Stage.PRE_MERGE, ("tools/new.sh",))
        self.assertTrue(s["unit"].selected and s["proofs"].selected)
        self.assertIn("unmapped", s["proofs"].reasons[0])

    def test_declared_ignore_is_not_unmapped(self):
        s = sel(Stage.PRE_MERGE, ("docs/a.md", "README.md"))
        self.assertFalse(s["unit"].selected or s["proofs"].selected)

    def test_global_input_selects_everything_owed(self):
        s = sel(Stage.PRE_MERGE, ("Cargo.lock",))
        self.assertTrue(s["unit"].selected and s["proofs"].selected)

    def test_full_stage_selects_all_including_periodic(self):
        s = sel(Stage.FULL, ())
        self.assertTrue(all(v.selected for v in s.values()))
        self.assertIn("drift", s)

    def test_slow_check_is_still_selected_when_reached(self):
        # cost does not appear anywhere in selection
        self.assertTrue(sel(Stage.PRE_MERGE, ("kernel/a.rs",))["proofs"].selected)


if __name__ == "__main__":
    unittest.main()


def cfg(checks, ignore=(), global_=()):
    extra = f"[impact]\nglobal = {list(global_)!r}\nignore = {list(ignore)!r}\n".replace("'", '"')
    return parse(tomllib.loads(cfg_text(checks, extra=extra)))


LINT = ("lint", '["pre-commit", "pre-merge"]', "always", "[]")
DRIFT = ("drift", '["pre-merge", "full"]', "periodic", "[]")
# The demonstrated escape: before, `unit` reads src/**; the PR's own configuration drops it and ignores
# both the source path and the configuration file.
BEFORE = cfg([LINT, ("unit", '["pre-merge", "full"]', "change", '["src/**", "tests/**"]')], ignore=["*.toml"])
AFTER = cfg(
    [LINT, ("unit", '["pre-merge", "full"]', "change", '["tests/**"]'), DRIFT], ignore=["*.toml", "src/**"]
)


AFTER_UNIT = ("unit", '["pre-merge", "full"]', "change", '["tests/**"]')


def chosen(c, changed, stage=Stage.PRE_MERGE):
    return {s.check.id: s for s in select(c, stage, changed)}


class ConfigurationChangeTest(unittest.TestCase):
    """A change to the project's dev-platform.toml is unknown impact (ADR 0006 §3 clarification)."""

    def assert_config_owed(self, s, path="dev-platform.toml"):
        self.assertTrue(s["unit"].selected)
        self.assertIn(f"selection configuration {path} changed", s["unit"].reasons[0])

    def test_a_change_cannot_narrow_its_own_selection_through_the_configuration(self):
        changed = ("dev-platform.toml", "src/x.py")
        self.assertTrue(chosen(BEFORE, changed)["unit"].selected)
        self.assert_config_owed(chosen(AFTER, changed))

    def test_ignored_configuration_file_still_selects_every_owed_check(self):
        self.assert_config_owed(chosen(AFTER, ("dev-platform.toml",)))

    def test_configuration_file_mapped_to_one_check_selects_every_owed_check(self):
        c = cfg([("cfg-lint", '["pre-merge"]', "change", '["dev-platform.toml"]'), AFTER_UNIT])
        s = chosen(c, ("dev-platform.toml",))
        self.assertTrue(s["cfg-lint"].selected)
        self.assert_config_owed(s)

    def test_otherwise_unmapped_configuration_file_names_the_configuration(self):
        c = cfg([AFTER_UNIT])
        self.assert_config_owed(chosen(c, ("dev-platform.toml",)))

    def test_configuration_change_alone_and_with_source_changes(self):
        for changed in (("dev-platform.toml",), ("dev-platform.toml", "src/x.py", "docs/a.md")):
            with self.subTest(changed=changed):
                self.assert_config_owed(chosen(AFTER, changed))

    def test_dot_slash_prefix_is_the_same_file(self):
        self.assert_config_owed(chosen(AFTER, ("./dev-platform.toml",)), "./dev-platform.toml")

    def test_a_nested_namesake_is_not_the_project_configuration(self):
        for path in ("src/dev-platform.toml", "docs/dev-platform.toml", "dev-platform.toml.bak"):
            with self.subTest(path=path):
                c = cfg([AFTER_UNIT], ignore=["src/**", "docs/**", "*.bak"])
                s = chosen(c, (path,))
                self.assertFalse(s["unit"].selected)

    def test_obligations_keep_their_meaning(self):
        s = chosen(AFTER, ("dev-platform.toml",))
        self.assertEqual(s["lint"].reasons[0], "always-obligation")
        self.assertFalse(s["drift"].selected)  # periodic is never owed by a change
        self.assertNotIn("drift", chosen(AFTER, ("dev-platform.toml",), Stage.PRE_COMMIT))
        self.assertTrue(chosen(AFTER, ("dev-platform.toml",), Stage.PRE_COMMIT)["lint"].selected)

    def test_full_stage_and_unknown_change_sets_are_unchanged(self):
        s = chosen(AFTER, ("dev-platform.toml",), Stage.FULL)
        self.assertTrue(all(v.selected for v in s.values()))
        self.assertEqual({v.reasons for v in s.values()}, {("full validation runs every check",)})
        self.assertIn("change set unknown", chosen(AFTER, None)["unit"].reasons[0])
