"""E2 tooling (tools/mcp_re_projection.py, tools/mcp_re_e2_controls.py): synthetic MCP-RE-shaped records only.

The real E2 inputs are not vendored; docs/assurance/e2-projection-equivalence.md names them by revision and blob id.
One known answer below is MCP-RE's own: ASM-0002 as committed at 4e3ffbb6 and its review record's digests.
"""

import copy
import hashlib
import importlib.util
import json
import unittest

from dev_platform import assurance as A
from tests.helpers import ROOT, tmpdir
from tests.test_assurance import projection

_spec = importlib.util.spec_from_file_location("mcp_re_projection", ROOT / "tools" / "mcp_re_projection.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
_spec = importlib.util.spec_from_file_location("mcp_re_e2_controls", ROOT / "tools" / "mcp_re_e2_controls.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

TARGET = "a" * 40

# verification/policy/assumptions.toml @ syncom-systems/mcp-re 4e3ffbb630ab49109a30961275217734a705a212 (Apache-2.0),
# the ASM-0002 entry; verification/reviews/assumption/ASM-0002.json there records the two digests asserted below.
ASM_0002 = '''[[assumption]]
id = "ASM-0002"
description = "`u8::is_ascii_digit` is true exactly on 0x30..=0x39."
justification = """
The Rust standard library's documented behaviour, which vstd does not currently specify.
A wrong specification here would let a non-digit byte through the parser's digit test, so
it is stated as the exact code-point range rather than as an opaque boolean.
"""
scope = ["unit://core.time_rfc3339", "boundary://boundary.rust_std"]
owner = "mats@sundvall.name"
introduced_by = "ADR-MCPRE-059 Phase 2 pilot"
review_requirement = "Owner review; discharge if vstd gains a specification for it."
premise_class = "external-boundary"
boundary_owner = """
The Rust standard library, across `u8::is_ascii_digit`: its documented predicate is true on exactly the ASCII digit code points 0x30..=0x39, which vstd does not currently specify.
"""
affected_contracts = ["contract://core/time/parse_rfc3339_utc"]
sites = [
  "mcp-re-core/src/verus_std_specs.rs#u8::is_ascii_digit",
]
tool_specific_mechanism = "verus:assume_specification"
'''

THEOREMS = """schema_version = 2
root_theorems = ["THM-0002"]

[[theorem]]
id = "THM-0001"
title = "leaf"
statement = "Parsing rejects unknown keys."
security_consequence = "No silent acceptance."
scope = "The parser."
direct_consequence_severity = "high"
owner = "core.parse"
review_requirement = "Owner security-specification review"
supported_by = ["unit://core.parse"]
depends_on = []

[[theorem]]
id = "THM-0002"
title = "root"
statement = "The loader is total."
security_consequence = "No crash on input."
scope = "The loader."
direct_consequence_severity = "high"
owner = "core.load"
review_requirement = "Owner security-specification review"
supported_by = ["unit://core.load", "unit://core.parse"]
depends_on = ["THM-0001"]
"""

ASSUMPTIONS = """schema_version = 2

[[assumption]]
id = "ASM-0001"
description = "TOML is UTF-8."
justification = "Specified."
scope = ["unit://core.parse"]
owner = "owner"
introduced_by = "test"
review_requirement = "Owner review"
premise_class = "assumed"
affected_contracts = []
tool_specific_mechanism = "none"
"""

POLICY = """schema_version = 1
policy_revision = "p-1"
unknown_is_dirty = true

[[unit]]
id = "core.load"
class = "V0"
evidence = ["test://core/load/total"]

[[unit]]
id = "core.parse"
class = "V0"
evidence = ["test://core/parse/unknown_keys", "mutation://core/parse/unknown_keys"]
"""


def write_tree(base, theorems=THEOREMS, assumptions=ASSUMPTIONS, ledger=True, review_digest_shift=()):
    """A consistent MCP-RE-shaped target tree and its closure record."""
    tree = base / "tree"
    pol = tree / "verification" / "policy"
    pol.mkdir(parents=True)
    (pol / "theorems.toml").write_text(theorems)
    (pol / "assumptions.toml").write_text(assumptions)
    (pol / "verification.toml").write_text(POLICY)
    inp = {"theorems": M.tomllib.loads(theorems), "assumptions": M.tomllib.loads(assumptions)}
    by_id = {e["id"]: e for e in inp["theorems"]["theorem"]}
    asm = {a["id"]: a for a in inp["assumptions"]["assumption"]}
    spec_dir = tree / "verification" / "reviews" / "specification"
    asm_dir = tree / "verification" / "reviews" / "assumption"
    spec_dir.mkdir(parents=True)
    asm_dir.mkdir(parents=True)
    theorems_rows, units = [], {"core.load": "sha256:" + "1" * 64, "core.parse": "sha256:" + "2" * 64}
    for tid in sorted(by_id):
        fp = M.theorem_fingerprint(by_id[tid], by_id)
        prem = (
            {"ASM-0001": M.mcp_digest(asm["ASM-0001"])}
            if "unit://core.parse" in by_id[tid]["supported_by"]
            else {}
        )
        rc = {
            "encoding_version": 1,
            **{
                k: fp["components"][k]
                for k in ("theorem_claim", "theorem_dependencies", "theorem_review_requirement")
            },
            "premises": prem,
            "supporting_semantics": {"core.parse": {"source_inputs": "sha256:" + "3" * 64}},
        }
        rd = M.mcp_digest(rc)
        (spec_dir / f"{tid}.json").write_text(
            json.dumps(
                {
                    "axis": "specification",
                    "subject": tid,
                    "reviewed_fingerprint": fp["fingerprint"],
                    "components": fp["components"],
                    "review_digest": rd,
                    "review_components": rc,
                    "reviewer": "owner",
                }
            )
        )
        recorded = "sha256:" + "9" * 64 if tid in review_digest_shift else rd
        theorems_rows.append({"theorem": tid, "fingerprint": fp["fingerprint"], "review_digest": recorded})
    (asm_dir / "ASM-0001.json").write_text(
        json.dumps(
            {
                "axis": "assumption",
                "subject": "ASM-0001",
                "reviewed_fingerprint": M.mcp_digest(asm["ASM-0001"]),
                "components": {"assumption_entry": M.mcp_digest(asm["ASM-0001"])},
                "reviewer": "owner",
            }
        )
    )
    files = []
    if ledger:
        text = M.entry_text(assumptions, "ASM-0001")
        line = {
            "ruling": "r1",
            "approved_by": "owner",
            "approved": "2026-10-01",
            "text": text,
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source": 'verification/policy/assumptions.toml [[assumption]] id = "ASM-0001"',
        }
        sec = tree / "docs" / "security"
        sec.mkdir(parents=True)
        (sec / "owner-approvals-2026-10-01.jsonl").write_text(json.dumps(line) + "\n")
        files = [
            (
                "docs/security/owner-approvals-2026-10-01.jsonl",
                (sec / "owner-approvals-2026-10-01.jsonl").read_bytes(),
            )
        ]
    unit_rows = [{"unit": u, "fingerprint": f} for u, f in sorted(units.items())]
    record = {
        "schema_version": 1,
        "kind": "mcp-re.assurance-closure-record",
        "subject": "repository assurance closure",
        "verdict": "PASS",
        "target": {"commit": TARGET, "tree": "b" * 40},
        "run": {"id": "1", "attempt": "1", "event": "workflow_dispatch", "evidence_commit": TARGET},
        "policy_revision": "p-1",
        "review_ledger": M.ledger_identity(files),
        "units": unit_rows,
        "units_digest": M.record_digest(unit_rows),
        "theorems": theorems_rows,
        "theorems_digest": M.record_digest(theorems_rows),
        "roots": {"declared": ["THM-0002"], "verdict": "COMPLETE"},
        "counts": {
            "active": 2,
            "review_current": 2,
            "evidence_established": 2,
            "currently_verified": 2,
            "roots": 1,
            "roots_established": 1,
        },
    }
    (base / "record.json").write_text(json.dumps(record))
    return M.read(tree, base / "record.json", TARGET, "c" * 40)


class Base(unittest.TestCase):
    def inp(self, **kw):
        return write_tree(tmpdir(self), **kw)


class EncodingTest(unittest.TestCase):
    def test_assumption_digest_and_entry_text_reproduce_mcp_re_committed_values(self):
        entry = M.entry_text(ASM_0002 + "\n# next entry\n", "ASM-0002")
        self.assertEqual(
            M.mcp_digest(M.tomllib.loads(entry)["assumption"][0]),
            "sha256:26f2de75c39022f40138018a60a1e636b2b2535b985275e68b7cc5e39ce58375",
        )
        self.assertEqual(
            hashlib.sha256(entry.encode()).hexdigest(),
            "2132b1aa3c688bcb667a6338ca37d2f621708ec3906fc249eb4befefc48d3b9b",
        )

    def test_the_two_mcp_re_encodings_differ_on_non_ascii(self):
        self.assertNotEqual(M.mcp_digest(["é"]), M.record_digest(["é"]))
        self.assertEqual(M.mcp_digest(["e"]), M.record_digest(["e"]))


class DeriveTest(Base):
    def test_consistent_records_agree_on_every_check(self):
        d = M.derive(self.inp())
        self.assertTrue(all(d["checks"].values()), d["checks"])
        self.assertEqual(d["counts"]["review_independent"], 2)
        self.assertEqual(d["counts"]["review_current_given_record"], 2)
        self.assertIsNone(d["counts"]["evidence_established"])  # never derived from the record's counts

    def test_a_changed_leaf_claim_moves_itself_and_its_dependant(self):
        inp = self.inp()
        inp["theorems"]["theorem"][0]["statement"] = "weakened"
        d = M.derive(inp)
        self.assertEqual(
            {t for t, x in d["theorems"].items() if not x["fingerprint_matches_record"]},
            {"THM-0001", "THM-0002"},
        )
        self.assertEqual(d["counts"]["review_independent"], 0)

    def test_changed_premise_and_unbacked_premise_are_not_current(self):
        inp = self.inp()
        inp["assumptions"]["assumption"][0]["description"] = "TOML is usually UTF-8."
        self.assertEqual(M.derive(inp)["theorems"]["THM-0001"]["premises_not_current"], ["ASM-0001"])
        d = M.derive(self.inp(ledger=False))
        self.assertEqual(d["theorems"]["THM-0001"]["premises_not_current"], ["ASM-0001"])
        self.assertTrue(d["checks"]["review_ledger_identity"])  # an empty ledger is still an identity

    def test_a_corrupted_ledger_line_is_refused(self):
        inp = self.inp()
        rel, data = inp["ledger_files"][0]
        inp["ledger_files"][0] = (rel, data.replace(b"UTF-8", b"UTF-16", 1))
        d = M.derive(inp)
        self.assertFalse(d["checks"]["ledger_lines_verify"])
        self.assertFalse(d["checks"]["review_ledger_identity"])
        self.assertEqual(M.convert(inp)[0]["premises"][0].get("review"), None)

    def test_semantic_digest_moved_is_reported_against_the_record(self):
        d = M.derive(self.inp(review_digest_shift=("THM-0002",)))
        self.assertFalse(d["theorems"]["THM-0002"]["semantic_digest_matches_record"])
        self.assertTrue(d["theorems"]["THM-0002"]["review_independent"])
        self.assertFalse(d["theorems"]["THM-0002"]["review_current_given_record"])


class ConvertTest(Base):
    def test_projection_is_valid_deterministic_and_keeps_mcp_re_identifiers(self):
        inp = self.inp()
        doc, losses = M.convert(inp)
        self.assertEqual(A.validate(doc), [])
        self.assertEqual((doc, losses), M.convert(copy.deepcopy(inp)))
        self.assertEqual([c["id"] for c in doc["claims"]], ["THM-0001", "THM-0002"])
        self.assertEqual([u["id"] for u in doc["units"]], ["core.load", "core.parse"])
        self.assertEqual(doc["claims"][1]["depends_on"], ["THM-0001"])
        self.assertEqual(doc["scope"], {"closure": "all-active", "roots": ["THM-0002"]})
        self.assertEqual(doc["subject"]["commit"], TARGET)
        paths = {s["path"]: s for s in doc["extensions"]["mcp-re"]["sources"]}
        self.assertEqual(paths[f"verification/closures/{TARGET}.json"]["revision"], "c" * 40)
        self.assertEqual(paths["verification/policy/theorems.toml"]["revision"], TARGET)
        data = THEOREMS.encode()
        self.assertEqual(
            paths["verification/policy/theorems.toml"]["git_blob"],
            hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest(),
        )

    def test_nothing_is_invented_or_upgraded(self):
        doc, losses = M.convert(self.inp())
        self.assertTrue(all(u["evidence"] == [] for u in doc["units"]))
        self.assertEqual({c["review"]["encoding"] for c in doc["claims"]}, {M.REVIEW_ENCODING})
        rec = A.evaluate(doc)
        self.assertEqual(rec["closure"]["verdict"], "INCOMPLETE")
        self.assertEqual(rec["consistency"]["state"], "projection-inconsistent")
        self.assertEqual({c["review"]["state"] for c in rec["claims"]}, {"incompatible"})
        concepts = {x["concept"] for x in losses}
        for c in (
            "evidence outcomes",
            "specification review binding",
            "semantic review components",
            "owner-approval ledger backing",
            "unit edges",
            "premise closure",
        ):
            self.assertIn(c, concepts)

    def test_unbacked_premise_review_is_withheld(self):
        doc, losses = M.convert(self.inp(ledger=False))
        self.assertNotIn("review", doc["premises"][0])
        self.assertEqual(
            next(x for x in losses if x["concept"] == "owner-approval ledger backing")["subjects"],
            ["ASM-0001"],
        )
        self.assertEqual({p["state"] for p in A.evaluate(doc)["premises"]}, {"unreviewed"})

    def test_premise_closure_not_attested_by_the_record_is_unknown(self):
        doc, losses = M.convert(self.inp(review_digest_shift=("THM-0001",)))
        c = doc["claims"][0]
        self.assertEqual((c["argument"], c["premises"]), ("unknown", []))
        self.assertEqual(
            next(x for x in losses if x["concept"] == "premise closure")["subjects"], ["THM-0001"]
        )

    def test_missing_review_record_gives_no_review(self):
        inp = self.inp()
        del inp["reviews"][("specification", "THM-0002")]
        doc, losses = M.convert(inp)
        self.assertNotIn("review", doc["claims"][1])
        self.assertIn("missing specification review", {x["concept"] for x in losses})

    def test_cli_writes_only_its_three_outputs_and_reads_without_writing(self):
        base = tmpdir(self)
        write_tree(base)
        before = {p: p.read_bytes() for p in (base / "tree").rglob("*") if p.is_file()}
        out = base / "out"
        M.main(
            [
                "--tree",
                str(base / "tree"),
                "--record",
                str(base / "record.json"),
                "--target",
                TARGET,
                "--record-revision",
                "c" * 40,
                "--out",
                str(out),
            ]
        )
        self.assertEqual(
            sorted(p.name for p in out.iterdir()), ["derivation.json", "mapping-loss.json", "projection.json"]
        )
        self.assertEqual({p: p.read_bytes() for p in (base / "tree").rglob("*") if p.is_file()}, before)


class ControlsTest(Base):
    def test_every_control_agrees_except_the_two_classified_discrepancies(self):
        rows = C.controls(self.inp(), None)
        diff = sorted((r["control"], r["applied_to"]) for r in rows if not r["agrees"])
        self.assertEqual(
            diff,
            [("N2", "projection, scope all-active"), ("N6", "projection, THM-0001 statement digest moved")],
        )

    def test_all_active_with_empty_roots_passes_in_v1_where_mcp_re_never_closes(self):
        # E2 finding (specification ambiguity, not changed here): MCP-RE fails a closure with no declared root.
        rec = A.evaluate(projection(scope={"closure": "all-active", "roots": []}))
        self.assertEqual(rec["closure"]["verdict"], "PASS")


if __name__ == "__main__":
    unittest.main()
