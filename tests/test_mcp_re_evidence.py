"""E2 follow-up tooling (tools/mcp_re_evidence.py): synthetic MCP-RE-shaped evidence records only.

The real artifacts are not vendored; docs/assurance/e2-evidence-artifacts.md names them by run, digest and manifest.
"""

import copy
import importlib.util
import json
import unittest

from dev_platform import assurance as A
from tests.helpers import ROOT, tmpdir
from tests.test_mcp_re_projection import TARGET, write_tree

_spec = importlib.util.spec_from_file_location("mcp_re_evidence", ROOT / "tools" / "mcp_re_evidence.py")
E = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(E)

LOAD, PARSE = "sha256:" + "1" * 64, "sha256:" + "2" * 64  # the unit fingerprints write_tree's record asserts


def write_artifact(base, records=None, bundle=None):
    """An extracted verification-evidence artifact: bundle.json and <lane>/<unit>.json records."""
    art = base / "artifact"
    art.mkdir()
    if records is None:
        records = [
            ("test", "core.load", "pass", LOAD),
            ("test", "core.parse", "pass", PARSE),
            ("mutation", "core.parse", "pass", PARSE),
        ]
    for lane, unit, result, fp in records:
        (art / lane).mkdir(exist_ok=True)
        body = {"unit_id": unit, "lane": lane, "result": result, "fingerprint": fp, "detail": "d"}
        (art / lane / f"{unit}.json").write_text(json.dumps(body))
    body = (
        bundle
        if bundle is not None
        else {"aggregate": "PASS", "lanes": {"test": "PASS"}, "policy_revision": "p-1"}
    )
    (art / "bundle.json").write_text(json.dumps(body))
    return art


class Base(unittest.TestCase):
    def setUp(self):
        self.base = tmpdir(self)
        self.inp = write_tree(self.base)

    def run_(self, applicability="record-bound", **kw):
        art = E.read_artifact(write_artifact(self.base, **kw))
        doc, losses = E.attach(self.inp, art, applicability)
        self.assertEqual(A.validate(doc), [])
        return art, doc, losses, A.evaluate(doc)


def reasons(rec, cid):
    return {r["code"] for c in rec["claims"] if c["id"] == cid for r in c["reasons"]}


def items(rec):
    return {i["id"]: i for u in rec["units"] for i in u["evidence"]}


class AttachTest(Base):
    def test_bound_records_support_units_and_review_remains_the_only_blocker(self):
        art, doc, losses, rec = self.run_()
        self.assertEqual(E.bind(self.inp, art)["counts"], {"fingerprint-matches/pass": 3})
        self.assertEqual({i["state"] for i in items(rec).values()}, {"supports"})
        self.assertEqual({u["state"] for u in rec["units"]}, {"established"})
        self.assertEqual(reasons(rec, "THM-0001"), {"review-incompatible"})
        self.assertEqual(
            rec["closure"]["verdict"], "INCOMPLETE"
        )  # the producer's PASS and bundle never decide
        self.assertEqual(rec["consistency"]["state"], "projection-inconsistent")
        self.assertNotIn("evidence outcomes", {x["concept"] for x in losses})
        item = next(i for u in doc["units"] for i in u["evidence"] if i["id"] == "mutation:core.parse")
        self.assertEqual((item["kind"], item["identity"]), ("control", "2" * 64))

    def test_deterministic_and_the_projection_is_convert_plus_evidence_only(self):
        art = E.read_artifact(write_artifact(self.base))
        doc, losses = E.attach(self.inp, art, "record-bound")
        self.assertEqual((doc, losses), E.attach(copy.deepcopy(self.inp), art, "record-bound"))
        base, _ = E.M.convert(self.inp)
        for d in (doc, base):
            for u in d["units"]:
                u["evidence"] = []
            d["producer"].pop("converter")
            d["extensions"]["mcp-re"].pop("evidence_artifact", None)
        self.assertEqual(doc, base)

    def test_unknown_applicability_supports_nothing(self):
        _, _, _, rec = self.run_(applicability="unknown")
        self.assertEqual({i["applicability"] for i in items(rec).values()}, {"unknown"})
        self.assertEqual({i["state"] for i in items(rec).values()}, {"does-not-support"})
        self.assertIn("unit-not-established", reasons(rec, "THM-0001"))

    def test_a_record_at_another_fingerprint_is_stale(self):
        art, _, _, rec = self.run_(
            records=[
                ("test", "core.load", "pass", LOAD),
                ("test", "core.parse", "pass", LOAD),
                ("mutation", "core.parse", "pass", PARSE),
            ]
        )
        self.assertEqual(E.bind(self.inp, art)["counts"]["fingerprint-differs/pass"], 1)
        self.assertEqual(items(rec)["test:core.parse"]["applicability"], "stale")
        self.assertIn("unit-not-established", reasons(rec, "THM-0001"))

    def test_a_failed_record_is_counterevidence(self):
        _, _, _, rec = self.run_(
            records=[
                ("test", "core.load", "pass", LOAD),
                ("test", "core.parse", "fail", PARSE),
                ("mutation", "core.parse", "pass", PARSE),
            ]
        )
        self.assertEqual(items(rec)["test:core.parse"]["state"], "counterevidence")
        self.assertEqual(rec["closure"]["verdict"], "FAILED")

    def test_a_missing_record_is_no_item_and_a_listed_loss(self):
        art, _, losses, rec = self.run_(
            records=[("test", "core.load", "pass", LOAD), ("test", "core.parse", "pass", PARSE)]
        )
        self.assertEqual(E.bind(self.inp, art)["counts"]["missing/-"], 1)
        self.assertNotIn("mutation:core.parse", items(rec))
        self.assertIn(
            "mutation/core.parse",
            next(x for x in losses if x["concept"] == "missing evidence record")["subjects"],
        )

    def test_undeclared_and_malformed_records_are_not_attached(self):
        base = [
            ("test", "core.load", "pass", LOAD),
            ("test", "core.parse", "pass", PARSE),
            ("mutation", "core.parse", "pass", PARSE),
            ("lean", "core.parse", "pass", PARSE),
        ]
        art_dir = write_artifact(self.base, records=base)
        (art_dir / "test" / "core.other.json").write_text(
            json.dumps({"unit_id": "core.load", "lane": "test", "result": "pass", "fingerprint": LOAD})
        )
        art = E.read_artifact(art_dir)
        self.assertEqual(art["dropped"], ["test/core.other.json"])
        self.assertEqual(E.bind(self.inp, art)["unclaimed_records"], ["lean/core.parse"])
        doc, losses = E.attach(self.inp, art, "record-bound")
        self.assertNotIn("lean:core.parse", {i["id"] for u in doc["units"] for i in u["evidence"]})
        self.assertEqual(
            {"record no unit declares", "malformed record"} - {x["concept"] for x in losses}, set()
        )

    def test_run_link_reports_a_scoped_bundle_and_upgrades_nothing(self):
        art, _, _, rec = self.run_(
            applicability="unknown",
            bundle={"aggregate": "INCOMPLETE", "scope": ["core.load"], "lanes": {}, "policy_revision": "p-1"},
        )
        link = E.run_link(self.inp, art, "1", "1")
        self.assertTrue(link["bundle_scoped"] and link["record_run_id_matches"])
        self.assertFalse(E.run_link(self.inp, art, "2", "1")["record_run_id_matches"])
        self.assertNotEqual(rec["closure"]["verdict"], "PASS")


class CliTest(Base):
    def test_cli_writes_only_its_three_outputs_and_leaves_the_artifact_alone(self):
        art = write_artifact(self.base)
        before = {p: p.read_bytes() for p in art.rglob("*") if p.is_file()}
        out = self.base / "out"
        rc = E.main(
            [
                "--tree",
                str(self.base / "tree"),
                "--record",
                str(self.base / "record.json"),
                "--target",
                TARGET,
                "--record-revision",
                "c" * 40,
                "--artifact",
                str(art),
                "--artifact-name",
                "verification-evidence-1-1",
                "--artifact-sha256",
                "0" * 64,
                "--run-id",
                "1",
                "--run-attempt",
                "1",
                "--out",
                str(out),
            ]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(
            sorted(p.name for p in out.iterdir()), ["binding.json", "mapping-loss.json", "projection.json"]
        )
        self.assertEqual(before, {p: p.read_bytes() for p in art.rglob("*") if p.is_file()})
        binding = json.loads((out / "binding.json").read_text())
        self.assertEqual(binding["artifact"]["records"], 3)
        self.assertTrue(binding["run"]["record_run_id_matches"])


if __name__ == "__main__":
    unittest.main()
