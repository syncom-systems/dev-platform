"""Identity-bound evidence reuse (R-5(i), draft ADR B): a previous record carries `verified` only when the
evidence identity of the check still matches; otherwise the previous state is history, never current evidence."""

import copy
import json
import subprocess
import tomllib
import unittest

from dev_platform import engine
from dev_platform.config import parse
from dev_platform.model import Stage
from dev_platform.resolve import Resolution
from tests.helpers import cfg_text, tmpdir

CHECKS = [
    ("lint", '["pre-commit", "pre-merge", "full"]', "change", '["src/**"]'),
    ("docs", '["pre-merge", "full"]', "change", '["docs/**"]'),
    ("unit", '["pre-merge", "full"]', "always", "[]"),
]
GLOBAL = '[impact]\nglobal = ["WORKSPACE"]\n'
CFG = parse(tomllib.loads(cfg_text(CHECKS, GLOBAL)))
PINNED = Resolution("pinned", "0.1.0", None, "d")
ENV = {
    "profile": "p",
    "conformant": True,
    "assurance": "certifiable",
    "weak_tools": [],
    "tools": [],
    "identity_digest": "e" * 64,
}
LEGACY = {"checks": [{"id": "lint", "state": "verified"}, {"id": "docs", "state": "verified"}]}


def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


class IdentityBoundReuseTest(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        for rel, text in {
            "src/a.py": "a = 1\n",
            "docs/d.md": "doc\n",
            "helpers/h.py": "h = 1\n",
            "WORKSPACE": "ws\n",
        }.items():
            self.write(rel, text)
        git(self.root, "init", "-q")
        git(self.root, "add", "-A")
        git(self.root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def build(
        self, stage=Stage.PRE_MERGE, changed=(), cfg=CFG, res=PINNED, env=ENV, execute=True, rc=0, **kw
    ):
        return engine.build(
            cfg,
            self.root,
            res,
            stage,
            changed,
            execute=execute,
            executor=lambda cmd, cwd: rc,
            environment=dict(env),
            revision="r1",
            **kw,
        )

    def previous(self, **kw):
        """A genuine record in which every check passed (change set unknown: every owed check selected)."""
        doc = self.build(changed=None, **kw)
        self.assertEqual({c["state"] for c in doc["checks"]}, {"verified"})
        return json.loads(json.dumps(doc))

    def lint(self, doc):
        return {c["id"]: c for c in doc["checks"]}["lint"]

    def assert_not_carried(self, doc, applicability, cause=None):
        c = self.lint(doc)
        self.assertEqual(c["outcome"], "not_run")
        self.assertNotEqual(c["state"], "verified")
        self.assertEqual(c["reuse"]["applicability"], applicability)
        self.assertFalse(c["reuse"]["carried"])
        if cause:
            self.assertEqual(c["reuse"]["cause"], cause)

    # 9. legitimate reuse
    def test_unchanged_evidence_is_reused_and_labelled_declared(self):
        doc = self.build(previous=self.previous())
        c = self.lint(doc)
        self.assertEqual(c["state"], "verified")
        self.assertEqual(c["reuse"]["applicability"], "current")
        self.assertTrue(c["reuse"]["carried"])
        self.assertEqual(c["reuse"]["boundary"], "declared")
        self.assertEqual(c["reuse"]["origin"], "unauthenticated")

    def test_new_revision_that_does_not_touch_the_inputs_keeps_evidence(self):
        prev = self.previous()
        self.write("docs/d.md", "changed\n")
        git(self.root, "commit", "-qam", "docs")
        c = self.lint(self.build(previous=prev))
        self.assertEqual(c["reuse"]["applicability"], "current")  # no over-invalidation by revision alone
        self.assertEqual(c["state"], "verified")

    # 1. and 4. changed relevant source state (other revision; uncommitted edit)
    def test_other_source_state_in_the_boundary_is_stale(self):
        prev = self.previous()
        self.write("src/a.py", "a = 2\n")
        git(self.root, "commit", "-qam", "src")
        self.assert_not_carried(self.build(previous=prev), "stale", "inputs")

    def test_uncommitted_edit_in_the_boundary_is_stale(self):
        prev = self.previous()
        self.write("src/a.py", "a = 3\n")
        self.assert_not_carried(self.build(previous=prev), "stale", "inputs")

    def test_new_or_deleted_file_in_the_boundary_is_stale(self):
        prev = self.previous()
        self.write("src/b.py", "b = 1\n")
        self.assert_not_carried(self.build(previous=prev), "stale", "inputs")
        (self.root / "src/b.py").unlink()
        (self.root / "src/a.py").unlink()
        self.assert_not_carried(self.build(previous=prev), "stale", "inputs")

    def test_changed_global_input_is_stale(self):
        prev = self.previous()
        self.write("WORKSPACE", "ws2\n")
        self.assert_not_carried(self.build(previous=prev), "stale", "global")

    # 2. changed check definition
    def test_changed_check_definition_is_stale(self):
        prev = self.previous()
        cfg = parse(tomllib.loads(cfg_text(CHECKS, GLOBAL).replace('argv = ["true"]', 'argv = ["false"]', 1)))
        self.assert_not_carried(self.build(cfg=cfg, previous=prev), "stale", "definition")

    # 3. changed platform or toolchain identity
    def test_changed_platform_release_is_stale(self):
        prev = self.previous()
        doc = self.build(res=Resolution("pinned", "0.2.0", None, "d2"), previous=prev)
        self.assert_not_carried(doc, "stale", "platform")

    def test_changed_toolchain_identity_is_stale(self):
        prev = self.previous()
        self.assert_not_carried(
            self.build(env={**ENV, "identity_digest": "f" * 64}, previous=prev), "stale", "environment"
        )

    # 5. missing identity component
    def test_missing_identity_component_is_unknown(self):
        prev = self.previous()
        for c in prev["checks"]:
            del c["identity"]["components"]["environment"]
        self.assert_not_carried(self.build(previous=prev), "unknown")

    def test_uncomputable_current_component_is_unknown(self):
        prev = self.previous()
        env = {k: v for k, v in ENV.items() if k != "identity_digest"}
        doc = self.build(env=env, previous=prev)
        self.assert_not_carried(doc, "unknown")
        self.assertIsNone(self.lint(doc)["identity"]["digest"])

    # 6. malformed, incompatible or unbound records
    def test_legacy_record_without_identity_carries_nothing(self):
        doc = self.build(previous=LEGACY)
        self.assert_not_carried(doc, "unknown")
        self.assertFalse(doc["previous"]["valid"])

    def test_record_of_another_project_carries_nothing(self):
        prev = self.previous()
        prev["project"]["name"] = "other"
        doc = self.build(previous=prev)
        self.assert_not_carried(doc, "unknown")
        self.assertIn("project", " ".join(doc["previous"]["problems"]))

    def test_malformed_records_carry_nothing_and_do_not_crash(self):
        good = self.previous()
        bad = [
            [],
            {"schema": "other"},
            {**good, "checks": "lint"},
            {**good, "checks": [{"state": "verified"}]},
            {**good, "checks": [{"id": "lint", "state": "nonsense"}]},
            {**good, "checks": good["checks"] + good["checks"][:1]},  # duplicate id
            {**good, "checks": [{**good["checks"][0], "identity": "x"}]},
            {**good, "checks": [{**good["checks"][0], "identity": {"encoding": "v99", "components": {}}}]},
        ]
        for prev in bad:
            with self.subTest(prev=str(prev)[:60]):
                doc = self.build(previous=prev)
                self.assertNotEqual(self.lint(doc)["state"], "verified")
                self.assertEqual(self.lint(doc)["reuse"]["applicability"], "unknown")

    # 7. `verified` without supporting evidence in the record itself
    def test_verified_without_a_pass_or_a_current_carry_is_unknown(self):
        prev = self.previous()
        lint = self.lint(prev)
        lint["outcome"], lint["reuse"] = "not_run", None
        self.assert_not_carried(self.build(previous=prev), "unknown")

    def test_fabricated_matching_record_is_not_authoritative(self):
        # A caller can copy current digests into a forged record: reuse then happens (origin is not
        # authenticated), but it is labelled so and discharges neither admission nor certification.
        cur = self.build(changed=None, execute=False)
        forged = copy.deepcopy(cur)
        for c in forged["checks"]:
            c["outcome"], c["state"] = "passed", "verified"
        doc = self.build(previous=forged, rc=1)
        self.assertEqual(self.lint(doc)["reuse"]["origin"], "unauthenticated")
        self.assertEqual(doc["previous"]["origin"], "caller-supplied, unauthenticated")
        self.assertEqual(doc["admission"], "blocked")  # the forged `verified` of `unit` discharges nothing
        full = self.build(stage=Stage.FULL, previous=forged, execute=False)
        self.assertFalse(full["certification"]["certified"])

    # 8. limitation of a declared boundary
    def test_change_outside_the_declared_boundary_is_not_detected_and_says_so(self):
        prev = self.previous()
        self.write("helpers/h.py", "h = 2\n")  # lint may read this; its declaration does not say so
        c = self.lint(self.build(previous=prev))
        self.assertEqual(c["reuse"]["applicability"], "current")
        self.assertEqual(c["identity"]["boundary"], "declared")  # never presented as complete
        self.assertNotEqual(c["reuse"]["boundary"], "complete")

    def test_always_check_has_no_reusable_boundary(self):
        prev = self.previous()
        doc = self.build(stage=Stage.PRE_COMMIT, previous=prev)  # unit is not defined here: unreached
        u = {c["id"]: c for c in doc["checks"]}["unit"]
        self.assertEqual(u["identity"]["boundary"], "unknown")
        self.assertNotEqual(u["state"], "verified")

    # 10. certification ignores carried evidence
    def test_full_stage_does_not_carry(self):
        cfg = parse(
            tomllib.loads(cfg_text([*CHECKS, ("late", '["pre-merge"]', "change", '["src/**"]')], GLOBAL))
        )
        prev = self.previous(cfg=cfg)
        doc = self.build(stage=Stage.FULL, cfg=cfg, previous=prev)
        late = {c["id"]: c for c in doc["checks"]}["late"]
        self.assertEqual(late["reuse"]["applicability"], "current")
        self.assertFalse(late["reuse"]["carried"])
        self.assertNotEqual(late["state"], "verified")
        self.assertFalse(doc["certification"]["certified"])

    # 11. admission is decided exactly as without a previous record
    def test_pre_merge_admission_is_unchanged_by_previous_records(self):
        prev = self.previous()
        self.write("src/a.py", "a = 9\n")
        for changed in [(), ("src/a.py",), ("docs/d.md",), ("elsewhere/x",), None]:
            for rc in (0, 1):
                with self.subTest(changed=changed, rc=rc):
                    keys = ("admission", "unsatisfied_obligations", "exit")
                    plain = self.build(changed=changed, rc=rc)
                    for p in (prev, LEGACY):
                        withp = self.build(changed=changed, rc=rc, previous=p)
                        self.assertEqual({k: plain[k] for k in keys}, {k: withp[k] for k in keys})
                        self.assertEqual(
                            [(c["id"], c["selected"], c["outcome"]) for c in plain["checks"]],
                            [(c["id"], c["selected"], c["outcome"]) for c in withp["checks"]],
                        )

    def test_regression_is_reported_against_applicable_evidence_only(self):
        prev = self.previous()
        self.assertEqual(
            self.build(changed=("src/a.py",), rc=1, previous=prev)["regressions"], ["lint", "unit"]
        )
        self.assertEqual(self.build(changed=("src/a.py",), rc=1, previous=LEGACY)["regressions"], [])

    # 12. determinism
    def test_identity_is_deterministic_and_order_independent(self):
        a = self.lint(self.build(changed=None))["identity"]
        (self.root / "src/a.py").touch()  # mtime is not identity
        b = self.lint(self.build(changed=None, rc=1))["identity"]  # neither is the outcome
        reordered = parse(tomllib.loads(cfg_text(list(reversed(CHECKS)), GLOBAL)))
        c = self.lint(self.build(changed=None, cfg=reordered))["identity"]
        self.assertEqual(a, b)
        self.assertEqual(a, c)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(c, sort_keys=True))
        self.assertRegex(a["digest"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
