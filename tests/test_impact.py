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
