import tomllib
import unittest

from dev_platform import engine
from dev_platform.config import parse
from dev_platform.model import Stage
from dev_platform.resolve import Resolution
from tests.helpers import cfg_text, tmpdir

CHECKS = [
    ("unit", '["pre-merge", "full"]', "change", '["src/**"]'),
    ("proofs", '["pre-merge", "full"]', "change", '["kernel/**"]'),
    ("drift", '["full"]', "periodic", "[]"),
]
CFG = parse(tomllib.loads(cfg_text(CHECKS)))
PINNED = Resolution("pinned", "0.1.0", None, "d")


def fake(codes):
    def run(cmd, cwd):
        return codes.get(cmd.argv[-1], 0)

    return run


def build(stage, changed, codes=None, res=PINNED, execute=True, **kw):
    cfg = kw.pop("cfg", CFG)
    return engine.build(
        cfg,
        tmpdir_root,
        res,
        stage,
        changed,
        execute=execute,
        executor=lambda cmd, cwd: (codes or {}).get("rc", 0),
        **kw,
    )


tmpdir_root = tmpdir.__globals__["Path"]("/")


def by_id(doc):
    return {c["id"]: c for c in doc["checks"]}


class EnginePolicyTest(unittest.TestCase):
    def test_passing_run_is_admitted_and_slow_unreached_check_stays_pending(self):
        doc = build(Stage.PRE_MERGE, ("src/a.py",))
        c = by_id(doc)
        self.assertEqual(c["unit"]["state"], "verified")
        self.assertEqual(c["proofs"]["state"], "pending")  # not run is never "verified"
        self.assertFalse(c["proofs"]["selected"])
        self.assertEqual(doc["admission"], "admitted")
        self.assertEqual(doc["exit"], 0)

    def test_failed_check_blocks_admission(self):
        doc = build(Stage.PRE_MERGE, ("src/a.py",), {"rc": 1})
        self.assertEqual(doc["admission"], "blocked")
        self.assertEqual(doc["unsatisfied_obligations"], ["unit"])
        self.assertEqual(doc["exit"], 1)

    def test_missing_tool_is_unsatisfied_not_pass(self):
        doc = build(Stage.PRE_MERGE, ("src/a.py",), {"rc": 127})
        self.assertEqual(by_id(doc)["unit"]["outcome"], "unavailable")
        self.assertEqual(doc["admission"], "blocked")

    def test_unknown_change_set_runs_everything_owed(self):
        doc = build(Stage.PRE_MERGE, None)
        self.assertEqual(sorted(doc["unsatisfied_obligations"]), [])
        self.assertTrue(all(c["selected"] for c in doc["checks"] if c["id"] != "drift"))
        self.assertFalse(doc["change_set"]["known"])

    def test_dry_run_never_admits(self):
        doc = build(Stage.PRE_MERGE, ("src/a.py",), execute=False)
        self.assertEqual(doc["admission"], "blocked")
        self.assertEqual(doc["exit"], 0)  # explaining is not failing
        self.assertEqual(by_id(doc)["unit"]["outcome"], "not_run")

    def test_edit_and_pre_commit_are_not_admission_stages(self):
        self.assertIsNone(build(Stage.PRE_COMMIT, ("src/a.py",))["admission"])

    def test_carry_invalidation_and_regression(self):
        prev = {
            "checks": [
                {"id": "unit", "state": "verified"},
                {"id": "proofs", "state": "verified"},
                {"id": "drift", "state": "verified"},
            ]
        }
        doc = build(Stage.PRE_MERGE, ("src/a.py",), execute=False, previous=prev)
        c = by_id(doc)
        self.assertEqual(c["unit"]["state"], "invalidated")  # reached, not re-run
        self.assertEqual(c["proofs"]["state"], "verified")  # carried: provably unreached
        doc = build(Stage.PRE_MERGE, ("src/a.py",), {"rc": 1}, previous=prev)
        self.assertEqual(doc["regressions"], ["unit"])

    def test_certification_needs_full_stage_pinned_platform_and_all_verified(self):
        full = build(Stage.FULL, (), revision="abc")
        self.assertTrue(full["certification"]["certified"])
        self.assertFalse(build(Stage.PRE_MERGE, ("src/a.py",), revision="abc")["certification"]["certified"])
        self.assertFalse(build(Stage.FULL, (), revision=None)["certification"]["certified"])
        self.assertFalse(build(Stage.FULL, (), {"rc": 1}, revision="abc")["certification"]["certified"])
        override = Resolution("override", None, None, None)
        cert = build(Stage.FULL, (), res=override, revision="abc")["certification"]
        self.assertFalse(cert["certified"])
        self.assertIn("not certifiable", " ".join(cert["blockers"]))

    def test_dirty_tree_is_not_certifiable(self):
        cert = build(Stage.FULL, (), revision="abc", dirty=True)["certification"]
        self.assertFalse(cert["certified"])
        self.assertIn("uncommitted", " ".join(cert["blockers"]))

    def test_unroutable_runner_blocks_instead_of_running(self):
        text = cfg_text([CHECKS[0]], extra='[runner.cred]\ncredentials = ["deploy"]\n')
        text = text.replace('inputs = ["src/**"]\n', 'inputs = ["src/**"]\nrunner = "cred"\n')
        calls = []
        doc = engine.build(
            parse(tomllib.loads(text)),
            tmpdir_root,
            PINNED,
            Stage.PRE_MERGE,
            ("src/a.py",),
            execute=True,
            executor=lambda c, w: calls.append(c) or 0,
        )
        self.assertEqual(calls, [])
        self.assertEqual(doc["admission"], "blocked")
        self.assertFalse(by_id(doc)["unit"]["runner"]["routed"])

    def test_result_is_deterministic_and_versioned(self):
        a = build(Stage.PRE_MERGE, ("src/a.py",))
        self.assertEqual(a, build(Stage.PRE_MERGE, ("src/a.py",)))
        self.assertEqual(a["schema"], "dev-platform.result/v1")


if __name__ == "__main__":
    unittest.main()
