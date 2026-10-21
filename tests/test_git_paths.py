"""Path coordinates of change sets (ADR 0006 §3): git-derived sets only at the worktree root, explicit paths
project-relative, everything else unknown impact. Temporary git fixtures only."""

import argparse
import subprocess
import tomllib
import unittest

from dev_platform import cli, engine
from dev_platform.config import parse
from dev_platform.impact import select
from dev_platform.model import Stage
from dev_platform.resolve import Resolution
from tests.helpers import cfg_text, tmpdir

UNIT = ("unit", '["pre-merge", "full"]', "change", '["src/**"]')
DOCS = ("docs", '["pre-merge", "full"]', "change", '["docs/**"]')
LINT = ("lint", '["pre-commit", "pre-merge"]', "always", "[]")
DRIFT = ("drift", '["pre-merge", "full"]', "periodic", "[]")
PLAIN = parse(tomllib.loads(cfg_text([UNIT, DOCS])))
# The investigation's escape: the PR narrows `unit`, maps **/*.py to `lint` and ignores **/*.toml.
NARROWED = parse(
    tomllib.loads(
        cfg_text(
            [
                ("unit", '["pre-merge", "full"]', "change", '["tests/**"]'),
                ("pylint", '["pre-merge", "full"]', "change", '["**/*.py"]'),
            ],
            extra='[impact]\nignore = ["**/*.toml"]\n',
        )
    )
)
CONFORMANT = {"profile": "p", "conformant": True, "assurance": "certifiable", "weak_tools": [], "tools": []}


def changed(project, base=None, staged=False, explicit=None):
    return cli._changed(argparse.Namespace(changed=explicit, base=base, staged=staged), project)


def chosen(cfg, ch, stage=Stage.PRE_MERGE):
    return {s.check.id: s for s in select(cfg, stage, ch)}


class Fixture(unittest.TestCase):
    def git(self, d, *a):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=d, check=True, capture_output=True
        )

    def repo(self, files, root=None):
        d = root or tmpdir(self)
        self.git(d, "init", "-q", "-b", "main")
        for f in files:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_text("1")
        self.git(d, "add", ".")
        self.git(d, "commit", "-qm", "c1")
        self.git(d, "checkout", "-qb", "topic")
        return d

    def nested(self):
        d = self.repo(["apps/service/dev-platform.toml", "apps/service/src/x.py", "shared/lib.py"])
        return d, d / "apps" / "service"


class RootProjectTest(Fixture):
    def test_repository_root_base_and_staged_are_unchanged(self):
        d = self.repo(["dev-platform.toml", "src/x.py", "docs/a.md"])
        (d / "src/x.py").write_text("2")
        (d / "src/new.py").write_text("n")
        self.assertEqual(changed(d, base="main"), ("src/new.py", "src/x.py"))
        self.assertEqual(
            {k for k, v in chosen(PLAIN, changed(d, base="main")).items() if v.selected}, {"unit"}
        )
        self.git(d, "add", "src/x.py")
        self.assertEqual(changed(d, staged=True), ("src/x.py",))

    def test_root_configuration_change_still_triggers_the_safeguard(self):
        d = self.repo(["dev-platform.toml", "src/x.py"])
        (d / "dev-platform.toml").write_text("2")
        (d / "src/x.py").write_text("2")
        s = chosen(NARROWED, changed(d, base="main"))
        self.assertTrue(s["unit"].selected)
        self.assertIn("selection configuration dev-platform.toml changed", s["unit"].reasons[0])

    def test_a_project_with_its_own_repository_inside_a_workspace_is_a_root_project(self):
        workspace = self.repo(["README.md"])
        (workspace / "service").mkdir()
        d = self.repo(["dev-platform.toml", "src/x.py"], root=workspace / "service")
        (d / "src/x.py").write_text("2")
        self.assertEqual(changed(d, base="main"), ("src/x.py",))


class NestedProjectTest(Fixture):
    def test_nested_base_and_staged_are_unknown_impact(self):
        d, p = self.nested()
        (p / "src/x.py").write_text("2")
        (p / "src/new.py").write_text("n")
        self.assertIsNone(changed(p, base="main"))  # was ('apps/service/src/x.py', 'src/new.py')
        self.git(d, "add", ".")
        self.assertIsNone(changed(p, staged=True))  # was ('apps/service/src/x.py', 'apps/service/src/new.py')
        s = chosen(PLAIN, changed(p, base="main"))
        self.assertTrue(s["unit"].selected and s["docs"].selected)
        self.assertIn("change set unknown", s["unit"].reasons[0])

    def test_the_configuration_safeguard_escape_selects_every_owed_check(self):
        _, p = self.nested()
        (p / "dev-platform.toml").write_text("2")
        (p / "src/x.py").write_text("2")
        # Before: ('apps/service/dev-platform.toml', 'apps/service/src/x.py') left `unit` unselected.
        s = chosen(NARROWED, changed(p, base="main"))
        self.assertTrue(all(v.selected for v in s.values()))

    def test_an_untracked_change_outside_the_project_is_not_an_empty_known_set(self):
        d, p = self.nested()
        (d / "shared/new.py").write_text("n")
        self.assertIsNone(changed(p, base="main"))  # was () and nothing selected
        self.assertTrue(chosen(PLAIN, changed(p, base="main"))["unit"].selected)

    def test_a_nested_project_with_no_changes_is_still_unknown(self):
        # Deliberate over-selection: precise nested incremental selection is unsupported, not approximated.
        _, p = self.nested()
        self.assertIsNone(changed(p, base="main"))
        self.assertIsNone(changed(p, staged=True))

    def test_a_failing_check_blocks_pre_merge_admission_in_the_nested_reproduction(self):
        _, p = self.nested()
        (p / "dev-platform.toml").write_text("2")
        (p / "src/x.py").write_text("2")
        doc = engine.build(
            NARROWED,
            p,
            Resolution("pinned", "0.1.0", None, "d"),
            Stage.PRE_MERGE,
            changed(p, base="main"),
            execute=True,
            executor=lambda cmd, cwd: 1,
            environment=CONFORMANT,
        )
        self.assertEqual(doc["admission"], "blocked")
        self.assertIn("unit", doc["unsatisfied_obligations"])

    def test_outside_a_worktree_is_unknown(self):
        self.assertIsNone(changed(tmpdir(self), base="main"))
        self.assertIsNone(changed(tmpdir(self), staged=True))


class ExplicitChangedTest(unittest.TestCase):
    def test_dot_slash_paths_are_project_relative(self):
        self.assertEqual(changed(None, explicit=["./src/x.py"]), ("src/x.py",))
        self.assertTrue(chosen(PLAIN, changed(None, explicit=["./src/x.py"]))["unit"].selected)
        self.assertFalse(chosen(PLAIN, changed(None, explicit=["./src/x.py"]))["docs"].selected)

    def test_dot_slash_configuration_triggers_the_safeguard(self):
        s = chosen(NARROWED, changed(None, explicit=["./dev-platform.toml"]))
        self.assertIn("selection configuration dev-platform.toml changed", s["unit"].reasons[0])

    def test_absolute_or_escaping_paths_make_the_whole_set_unknown(self):
        for bad in ("../shared/x.py", "src/../../x", "/abs/x", ".", ".."):
            with self.subTest(path=bad):
                self.assertIsNone(changed(None, explicit=["src/x.py", bad]))

    def test_unknown_and_full_stage_behaviour_is_unchanged(self):
        cfg = parse(tomllib.loads(cfg_text([LINT, UNIT, DRIFT])))
        s = chosen(cfg, None)
        self.assertTrue(s["unit"].selected and s["lint"].selected)
        self.assertFalse(s["drift"].selected)
        full = chosen(cfg, changed(None, explicit=["docs/a.md"]), Stage.FULL)
        self.assertEqual({v.reasons for v in full.values()}, {("full validation runs every check",)})
