"""Assurance evaluator prototype (draft ADR A): synthetic projections only, no execution, no MCP-RE.

Cases N1-N9, N17, N19-N23 of docs/assurance/evaluation-plan.md §5 that are data-only are named in the test names.
Agreement here is with the draft ADR text, not with MCP-RE (no equivalence is claimed).
"""

import copy
import json
import unittest

from dev_platform import assurance as A
from dev_platform.records import canonical_digest
from tests.helpers import tmpdir

S1, S2, P1 = (canonical_digest(t) for t in ("parse rejects unknown keys", "loader is total", "TOML is UTF-8"))
ID = "1" * 64


def item(i="unit-tests", **kw):
    return {
        "id": i,
        "kind": "test",
        "outcome": "passed",
        "provenance": "observed",
        "applicability": "current",
        "boundary": "declared",
        "identity": ID,
    } | kw


def reviewed(c):
    c["review"] = {"encoding": A.ARGUMENT_ENCODING, "statement_digest": c["statement_digest"]}
    c["review"]["argument_digest"] = A.argument_digest(c)
    return c


def claim(cid="C1", units=("U1",), statement=S1, **kw):
    c = {
        "id": cid,
        "statement_digest": statement,
        "argument": "declared",
        "support": {"form": "all", "units": list(units)},
    }
    return reviewed(c | kw)


def projection(claims=None, units=None, premises=(), scope=None, **kw):
    return {
        "schema": A.PROJECTION,
        "producer": {"name": "synthetic"},
        "scope": scope if scope is not None else {"closure": "roots", "roots": ["C1"]},
        "claims": [claim()] if claims is None else claims,
        "units": [{"id": "U1", "evidence": [item()]}] if units is None else units,
        "premises": list(premises),
    } | kw


def premise(pid="P1", accepted=True, **kw):
    p = {"id": pid, "statement_digest": P1, "class": "assumed"}
    if accepted:
        p["review"] = {"statement_digest": P1}
    return p | kw


def run(doc):
    problems = A.validate(doc)
    assert not problems, problems
    return A.evaluate(copy.deepcopy(doc))


def codes(rec):
    return sorted({b["code"] for b in rec["closure"]["blockers"]})


class PositiveTest(unittest.TestCase):
    def test_supported_reviewed_claim_is_established_and_closure_passes(self):
        rec = run(projection())
        self.assertEqual(rec["closure"]["verdict"], "PASS")
        c = rec["claims"][0]
        self.assertEqual((c["state"], c["review"]["state"]), ("established", "current"))
        self.assertEqual(c["basis"]["kinds"], ["test"])
        self.assertEqual(c["basis"]["boundaries"], ["declared"])  # the pass says what it rests on
        self.assertEqual(rec["closure"]["basis"]["evidence"][0]["identity"], ID)

    def test_pass_is_informational_and_states_its_limits(self):
        rec = run(projection())
        self.assertEqual(rec["authority"], "informational")
        self.assertIn(
            "satisfies no admission, certification, release or owner-acceptance obligation",
            rec["limitations"],
        )

    def test_prerequisites_and_accepted_premises_establish_and_are_listed(self):
        doc = projection(
            claims=[claim(depends_on=["C2"], premises=["P1"]), claim("C2", ["U2"], S2)],
            units=[
                {"id": "U1", "evidence": [item()]},
                {"id": "U2", "premises": ["P2"], "evidence": [item("proof", kind="proof")]},
            ],
            premises=[premise(), premise("P2")],
        )
        rec = run(doc)
        self.assertEqual(rec["closure"]["verdict"], "PASS")
        self.assertEqual(rec["closure"]["scope"]["claims"], ["C1", "C2"])  # roots scope follows depends_on
        basis = rec["closure"]["basis"]
        self.assertEqual(basis["premises"], ["P1", "P2"])  # "established under P" is never unconditional
        self.assertEqual(basis["kinds"], ["proof", "test"])

    def test_all_active_scope_covers_every_claim(self):
        doc = projection(claims=[claim(), claim("C2", ["U2"], S2)], scope={"closure": "all-active"})
        rec = run(doc)
        self.assertEqual(rec["closure"]["verdict"], "INCOMPLETE")
        self.assertEqual(
            rec["closure"]["blockers"][0] | {},
            {"claim": "C2", "state": "not-established", "code": "unresolved-unit", "unit": "U2"},
        )


class NonVacuityTest(unittest.TestCase):
    def test_n1_no_claims_is_undeclared(self):
        rec = run(projection(claims=[], units=[]))
        self.assertEqual((rec["closure"]["verdict"], codes(rec)), ("UNDECLARED", ["no-claims"]))

    def test_n2_empty_roots_is_undeclared(self):
        for scope in ({"closure": "roots", "roots": []}, {"closure": "roots"}):
            with self.subTest(scope=scope):
                self.assertEqual(run(projection(scope=scope))["closure"]["verdict"], "UNDECLARED")

    def test_missing_scope_is_undeclared(self):
        doc = projection()
        del doc["scope"]
        rec = run(doc)
        self.assertEqual((rec["closure"]["verdict"], codes(rec)), ("UNDECLARED", ["scope-undeclared"]))

    def test_unresolved_root_is_incomplete(self):
        rec = run(projection(scope={"closure": "roots", "roots": ["C1", "C9"]}))
        self.assertEqual((rec["closure"]["verdict"], codes(rec)), ("INCOMPLETE", ["unresolved-root"]))

    def test_n3_empty_support_is_no_support(self):
        rec = run(projection(claims=[claim(units=())]))
        self.assertEqual((rec["closure"]["verdict"], codes(rec)), ("INCOMPLETE", ["no-support"]))

    def test_unit_without_evidence_does_not_support(self):
        rec = run(projection(units=[{"id": "U1", "evidence": []}]))
        self.assertEqual(codes(rec), ["unit-no-evidence"])

    def test_n4_only_not_run_or_unavailable_evidence_is_incomplete_not_failed(self):
        for outcome in ("not_run", "unavailable"):
            with self.subTest(outcome=outcome):
                rec = run(projection(units=[{"id": "U1", "evidence": [item(outcome=outcome)]}]))
                self.assertEqual(
                    rec["closure"]["verdict"], "INCOMPLETE"
                )  # a missing tool is not counterevidence
                self.assertEqual(rec["units"][0]["evidence"][0]["reasons"], [f"outcome-{outcome}"])

    def test_n5_missing_unit_is_incomplete(self):
        rec = run(projection(units=[]))
        self.assertEqual((rec["closure"]["verdict"], codes(rec)), ("INCOMPLETE", ["unresolved-unit"]))

    def test_n6_changed_statement_stales_the_review_and_blocks_dependants(self):
        doc = projection(claims=[claim(depends_on=["C2"]), claim("C2", ["U1"], S2)])
        doc["claims"][1]["statement_digest"] = canonical_digest("loader is total, and fast")
        rec = run(doc)
        by = {c["id"]: c for c in rec["claims"]}
        self.assertEqual(by["C2"]["review"], {"state": "stale", "cause": "statement"})
        self.assertIn({"code": "dependency-not-established", "claim": "C2"}, by["C1"]["reasons"])
        self.assertEqual(rec["closure"]["verdict"], "INCOMPLETE")

    def test_changed_argument_stales_the_review(self):
        for change in (
            lambda c: c["support"]["units"].append("U2"),
            lambda c: c.update(depends_on=["C2"]),
            lambda c: c.update(premises=["P1"]),
            lambda c: c.update(argument="incomplete"),
        ):
            doc = projection(units=[{"id": "U1", "evidence": [item()]}, {"id": "U2", "evidence": [item()]}])
            change(doc["claims"][0])
            c = run(doc)["claims"][0]
            self.assertEqual(c["review"], {"state": "stale", "cause": "argument"})
            self.assertNotEqual(c["state"], "established")

    def test_argument_digest_ignores_list_order(self):
        a = claim(units=("U1", "U2"), depends_on=["C2", "C3"])
        b = claim(units=("U2", "U1"), depends_on=["C3", "C2"])
        self.assertEqual(A.argument_digest(a), A.argument_digest(b))

    def test_missing_or_incompatible_review_does_not_establish(self):
        doc = projection()
        del doc["claims"][0]["review"]
        self.assertEqual(codes(run(doc)), ["review-absent"])
        doc = projection()
        doc["claims"][0]["review"]["encoding"] = "dev-platform.assurance-argument/2"
        self.assertEqual(codes(run(doc)), ["review-incompatible"])

    def test_n7_stale_and_unknown_evidence_does_not_support(self):
        for kw, reason in (
            ({"applicability": "stale", "cause": "provider"}, "stale(provider)"),
            ({"applicability": "unknown"}, "applicability-unknown"),
            ({"boundary": "unknown"}, "boundary-unknown"),
            ({"identity": None}, "identity-unknown"),
        ):
            with self.subTest(reason=reason):
                rec = run(projection(units=[{"id": "U1", "evidence": [item(**kw)]}]))
                self.assertEqual(rec["closure"]["verdict"], "INCOMPLETE")
                self.assertEqual(rec["units"][0]["evidence"][0]["reasons"], [reason])

    def test_n18_toolchain_bump_stales_evidence_not_reviews(self):
        doc = projection(claims=[claim(depends_on=["C2"]), claim("C2", ["U2"], S2)],
                         units=[{"id": u, "evidence": [item(applicability="stale", cause="environment")]} for u in ("U1", "U2")])  # fmt: skip
        rec = run(doc)
        self.assertEqual({c["review"]["state"] for c in rec["claims"]}, {"current"})
        self.assertEqual({u["state"] for u in rec["units"]}, {"not-established"})
        self.assertEqual(rec["closure"]["verdict"], "INCOMPLETE")

    def test_stale_or_unknown_failure_is_not_counterevidence(self):
        for kw in ({"applicability": "stale"}, {"applicability": "unknown"}, {"provenance": "inferred"}):
            with self.subTest(kw=kw):
                rec = run(projection(units=[{"id": "U1", "evidence": [item(outcome="failed", **kw)]}]))
                self.assertEqual(rec["closure"]["verdict"], "INCOMPLETE")

    def test_declared_or_inferred_provenance_does_not_support(self):
        for p in ("declared", "inferred"):
            rec = run(projection(units=[{"id": "U1", "evidence": [item(provenance=p)]}]))
            self.assertEqual(rec["units"][0]["evidence"][0]["reasons"], [f"provenance-{p}"])
            self.assertEqual(rec["closure"]["verdict"], "INCOMPLETE")

    def test_n8_omitted_result_is_incomplete(self):
        doc = projection(
            units=[{"id": "U1", "evidence": [item(), item("proof", kind="proof", outcome="not_run")]}]
        )
        rec = run(doc)
        self.assertEqual(rec["units"][0]["state"], "not-established")  # every item of a unit must support
        self.assertEqual(rec["closure"]["verdict"], "INCOMPLETE")

    def test_n9_current_failure_fails_the_claim_and_blocks_dependants(self):
        doc = projection(
            claims=[claim(depends_on=["C2"]), claim("C2", ["U2"], S2)],
            units=[{"id": "U1", "evidence": [item()]}, {"id": "U2", "evidence": [item(outcome="failed")]}],
        )
        rec = run(doc)
        by = {c["id"]: c for c in rec["claims"]}
        self.assertEqual(by["C2"]["state"], "failed")
        self.assertEqual(by["C1"]["state"], "not-established")
        self.assertIn({"code": "dependency-failed", "claim": "C2"}, by["C1"]["reasons"])
        self.assertEqual(rec["closure"]["verdict"], "FAILED")

    def test_missing_prerequisite_claim_is_incomplete(self):
        rec = run(projection(claims=[claim(depends_on=["C9"])]))
        self.assertEqual((rec["closure"]["verdict"], codes(rec)), ("INCOMPLETE", ["unresolved-claim"]))

    def test_cycles_are_never_established(self):
        for claims in (
            [claim(depends_on=["C1"])],
            [claim(depends_on=["C2"]), claim("C2", depends_on=["C1"])],
            [claim(depends_on=["C2"]), claim("C2", depends_on=["C3"]), claim("C3", depends_on=["C2"])],
        ):
            with self.subTest(n=len(claims)):
                rec = run(projection(claims=claims))
                self.assertEqual(rec["closure"]["verdict"], "INCOMPLETE")
                self.assertTrue(all(c["state"] == "not-established" for c in rec["claims"]))
                self.assertIn("cyclic-dependency", codes(rec))

    def test_n22_missing_or_unaccepted_premise_does_not_establish(self):
        cases = (
            ([], "unresolved-premise", None),
            ([premise(accepted=False)], "premise-unaccepted", "unreviewed"),
            ([premise(review={"statement_digest": S2})], "premise-unaccepted", "stale"),
        )
        for premises, code, state in cases:
            for where in ("claim", "unit"):
                with self.subTest(code=code, state=state, where=where):
                    doc = projection(premises=premises)
                    if where == "claim":
                        doc["claims"] = [claim(premises=["P1"])]
                    else:
                        doc["units"][0]["premises"] = ["P1"]
                    rec = run(doc)
                    self.assertEqual((rec["closure"]["verdict"], codes(rec)), ("INCOMPLETE", [code]))
                    if state:
                        self.assertEqual(rec["closure"]["blockers"][0]["state"], state)

    def test_n21_incomplete_or_unknown_argument_is_not_established(self):
        for arg in ("incomplete", "unknown"):
            rec = run(projection(claims=[claim(argument=arg)]))
            self.assertEqual((rec["closure"]["verdict"], codes(rec)), ("INCOMPLETE", [f"argument-{arg}"]))

    def test_n19_n20_n23_any_of_is_unsupported_never_reinterpreted_or_failed(self):
        for groups in ([["U1"], ["U2"]], [[], ["U1"]], [["U1"]]):
            with self.subTest(groups=groups):
                doc = projection(
                    claims=[claim(support={"form": "any-of", "groups": groups})],
                    units=[
                        {"id": "U1", "evidence": [item()]},
                        {"id": "U2", "evidence": [item(outcome="failed")]},
                    ],
                )
                rec = run(doc)
                self.assertEqual(
                    (rec["closure"]["verdict"], codes(rec)), ("INCOMPLETE", ["unsupported-form"])
                )
                self.assertEqual(rec["claims"][0]["support"], {"form": "any-of"})

    def test_unknown_support_form_is_unsupported(self):
        rec = run(projection(claims=[claim(support={"form": "weighted", "units": ["U1"]})]))
        self.assertEqual(codes(rec), ["unsupported-form"])


class ProjectionConsistencyTest(unittest.TestCase):
    def test_n17_producer_pass_with_failing_unit_is_inconsistent_never_pass(self):
        doc = projection(
            units=[{"id": "U1", "evidence": [item(outcome="failed")]}],
            producer_verdicts={"claims": {"C1": "established"}, "closure": "PASS"},
        )
        rec = run(doc)
        self.assertEqual(rec["consistency"]["state"], "projection-inconsistent")
        self.assertEqual(rec["closure"]["verdict"], "FAILED")
        self.assertEqual(
            rec["consistency"]["disagreements"],
            [
                {"subject": "claim:C1", "producer": "established", "recomputed": "failed"},
                {"subject": "closure", "producer": "PASS", "recomputed": "FAILED"},
            ],
        )

    def test_disagreement_on_an_otherwise_passing_projection_is_not_pass(self):
        for pv in (
            {"closure": "INCOMPLETE"},
            {"claims": {"C1": "established", "C9": "established"}},
            {"claims": {}},
        ):
            with self.subTest(pv=pv):
                rec = run(projection(producer_verdicts=pv))
                self.assertEqual(rec["closure"]["recomputed_verdict"], "PASS")
                self.assertEqual(rec["closure"]["verdict"], "INCOMPLETE")
                self.assertIn("projection-inconsistent", codes(rec))

    def test_agreement_is_consistent(self):
        rec = run(projection(producer_verdicts={"claims": {"C1": "established"}, "closure": "PASS"}))
        self.assertEqual((rec["consistency"]["state"], rec["closure"]["verdict"]), ("consistent", "PASS"))
        self.assertEqual(run(projection())["consistency"]["state"], "not-compared")


class ContractTest(unittest.TestCase):
    def test_other_versions_and_unknown_fields_are_refused(self):
        bad = {
            "v2": projection(schema="dev-platform.assurance-projection/v2"),
            "no schema": {k: v for k, v in projection().items() if k != "schema"},
            "unknown top field": projection(verdict="PASS"),
            "status boolean on claim": projection(claims=[claim() | {"established": True}]),
            "unknown outcome": projection(units=[{"id": "U1", "evidence": [item(outcome="skipped")]}]),
            "unknown applicability": projection(
                units=[{"id": "U1", "evidence": [item(applicability="fresh")]}]
            ),
            "unknown kind": projection(units=[{"id": "U1", "evidence": [item(kind="vibe")]}]),
            "unknown boundary": projection(units=[{"id": "U1", "evidence": [item(boundary="assumed")]}]),
            "bad identity": projection(units=[{"id": "U1", "evidence": [item(identity="abc")]}]),
            "duplicate claim": projection(claims=[claim(), claim()]),
            "duplicate evidence": projection(units=[{"id": "U1", "evidence": [item(), item()]}]),
            "duplicate support unit": projection(claims=[claim(units=("U1", "U1"))]),
            "unknown scope": projection(scope={"closure": "everything"}),
            "unknown argument": projection(claims=[claim(argument="probably")]),
            "producer without name": projection(producer={}),
            "producer not an object": projection(producer="x"),
            "claims not a list": projection(claims={}),
            "unknown producer verdict": projection(producer_verdicts={"closure": "COMPLETE"}),
            "null producer verdicts": projection(producer_verdicts=None),
            "not an object": [],
        }
        for name, doc in bad.items():
            with self.subTest(name):
                self.assertTrue(A.validate(doc))

    def test_all_support_without_units_is_a_validation_error_not_an_exception(self):
        doc = projection()
        doc["claims"][0]["support"] = {"form": "all"}
        self.assertEqual(A.validate(doc), ["claims[0].support.units: required"])

    def test_every_missing_required_field_is_reported_never_raised(self):
        full = projection(
            claims=[claim(premises=["P1"])],
            units=[{"id": "U1", "premises": ["P1"], "evidence": [item()]}],
            premises=[premise()],
            producer_verdicts={"claims": {"C1": "established"}, "closure": "PASS"},
        )
        paths = {(): A._TOP, ("scope",): A._SCOPE, ("claims", 0): A._CLAIM,
                 ("claims", 0, "support"): ({"form", "units"}, set()), ("claims", 0, "review"): A._REVIEW,
                 ("units", 0): A._UNIT, ("units", 0, "evidence", 0): A._ITEM, ("premises", 0): A._PREMISE,
                 ("premises", 0, "review"): A._PREMISE_REVIEW}  # fmt: skip
        n = 0
        for path, (required, _) in paths.items():
            obj = full
            for k in path:
                obj = obj[k]
            for key in list(obj):
                doc = copy.deepcopy(full)
                target = doc
                for k in path:
                    target = target[k]
                del target[key]
                with self.subTest(path=path, key=key):
                    try:
                        problems = A.validate(doc)
                    except Exception as ex:  # the regression: validation must not raise
                        self.fail(f"validate raised {ex!r}")
                    if key in required:
                        self.assertTrue(problems)
                    elif key not in (
                        "scope",
                        "producer_verdicts",
                    ):  # removing these changes the verdict, not validity
                        self.assertEqual(problems, [])
                n += 1
        self.assertGreaterEqual(n, 35)  # every field of every object kind above

    def test_optional_fields_have_the_schema_types(self):
        def with_(where, key, value):
            doc = projection(premises=[premise()])
            target = {
                "claim": doc["claims"][0],
                "claim review": doc["claims"][0]["review"],
                "unit": doc["units"][0],
                "evidence": doc["units"][0]["evidence"][0],
                "premise": doc["premises"][0],
                "premise review": doc["premises"][0]["review"],
            }[where]
            target[key] = value
            return doc

        for where in ("claim", "premise"):
            for bad in (7, None, ["text"], {"text": 1}):
                with self.subTest(where=where, statement=bad):
                    self.assertEqual(A.validate(with_(where, "statement", bad)), [
                        f"{'claims' if where == 'claim' else 'premises'}[0].statement: string required"])  # fmt: skip
            self.assertEqual(A.validate(with_(where, "statement", "")), [])  # the schema allows empty text
        for where in ("claim", "claim review", "unit", "evidence", "premise", "premise review"):
            for bad in ("x", [], None, 1):
                with self.subTest(where=where, extensions=bad):
                    problems = A.validate(with_(where, "extensions", bad))
                    self.assertEqual(len(problems), 1)
                    self.assertTrue(problems[0].endswith(".extensions: object required"), problems)
            self.assertEqual(A.validate(with_(where, "extensions", {"any": ["thing"]})), [])

    def test_unsupported_form_contents_stay_uninterpreted(self):
        for support in (
            {"form": "any-of", "groups": "not even a list"},
            {"form": "any-of"},
            {"form": "x", "y": 1},
        ):
            with self.subTest(support=support):
                doc = projection(claims=[claim(support=support)])
                self.assertEqual(A.validate(doc), [])
                self.assertEqual(codes(run(doc)), ["unsupported-form"])

    def test_extensions_never_influence_the_verdict(self):
        plain = run(projection())
        doc = projection(extensions={"x": {"verdict": "FAILED"}})
        doc["claims"][0]["extensions"] = {"severity": "critical", "established": False}
        doc["units"][0]["evidence"][0]["extensions"] = {"outcome": "failed"}
        rec = run(doc)
        for k in ("closure", "claims", "units", "consistency"):
            self.assertEqual(rec[k], plain[k])
        self.assertNotEqual(rec["projection"]["digest"], plain["projection"]["digest"])

    def test_evaluation_is_deterministic_and_order_independent(self):
        doc = projection(
            claims=[claim(depends_on=["C2"]), claim("C2", ["U2", "U1"], S2)],
            units=[
                {"id": "U1", "evidence": [item(), item("b", kind="proof")]},
                {"id": "U2", "evidence": [item()]},
            ],
        )
        shuffled = copy.deepcopy(doc)
        shuffled["claims"].reverse()
        shuffled["units"].reverse()
        shuffled["units"][1]["evidence"].reverse()
        a, b = run(doc), run(doc)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        c = run(shuffled)
        del a["projection"], c["projection"]
        self.assertEqual(a, c)

    def test_evaluate_does_not_modify_its_input(self):
        doc = projection(producer_verdicts={"closure": "PASS"})
        before = copy.deepcopy(doc)
        A.evaluate(doc)
        self.assertEqual(doc, before)

    def test_load_reports_unreadable_and_invalid_files(self):
        d = tmpdir(self)
        (d / "bad.json").write_text("{")
        (d / "v2.json").write_text(json.dumps(projection(schema="dev-platform.assurance-projection/v2")))
        for name in ("bad.json", "v2.json", "missing.json"):
            doc, problems = A.load(d / name)
            self.assertIsNone(doc)
            self.assertTrue(problems)


class SchemaTest(unittest.TestCase):
    """The schema files mirror the validator and the evaluator output (the validator is authoritative)."""

    def schema(self, name):
        from tests.helpers import ROOT

        return json.loads((ROOT / "schemas" / f"{name}-v1.schema.json").read_text())

    def test_projection_schema_matches_validator(self):
        s = self.schema("assurance-projection")
        self.assertEqual(s["properties"]["schema"]["const"], A.PROJECTION)
        p = s["properties"]
        for obj, spec in (
            (s, A._TOP),
            (p["claims"]["items"], A._CLAIM),
            (p["claims"]["items"]["properties"]["review"], A._REVIEW),
            (p["units"]["items"], A._UNIT),
            (p["units"]["items"]["properties"]["evidence"]["items"], A._ITEM),
            (p["premises"]["items"], A._PREMISE),
            (p["premises"]["items"]["properties"]["review"], A._PREMISE_REVIEW),
            (p["scope"], A._SCOPE),
        ):
            self.assertEqual(set(obj["required"]), spec[0])
            self.assertEqual(set(obj["properties"]), spec[0] | spec[1])
        ev = p["units"]["items"]["properties"]["evidence"]["items"]["properties"]
        for field, values in (("kind", A.KINDS), ("outcome", A.OUTCOMES), ("provenance", A.PROVENANCE),
                              ("applicability", A.APPLICABILITY), ("boundary", A.BOUNDARIES)):  # fmt: skip
            self.assertEqual(tuple(ev[field]["enum"]), tuple(values), field)

    def test_evaluation_matches_schema(self):
        s = self.schema("assurance-evaluation")
        doc = projection(
            claims=[claim(premises=["P1"])], premises=[premise()], producer_verdicts={"closure": "PASS"}
        )
        rec = run(doc)
        self.assertEqual(set(rec), set(s["required"]))
        self.assertEqual(rec["schema"], s["properties"]["schema"]["const"])
        p = s["properties"]
        self.assertTrue(set(rec["closure"]) <= set(p["closure"]["properties"]))
        self.assertTrue(
            set(p["claims"]["items"]["required"])
            <= set(rec["claims"][0])
            <= set(p["claims"]["items"]["properties"])
        )
        self.assertEqual(set(rec["units"][0]), set(p["units"]["items"]["required"]))
        self.assertEqual(
            set(rec["units"][0]["evidence"][0]),
            set(p["units"]["items"]["properties"]["evidence"]["items"]["required"]),
        )
        self.assertEqual(set(rec["premises"][0]), set(p["premises"]["items"]["required"]))


class KnownLimitTest(unittest.TestCase):
    def test_review_binds_unit_ids_not_unit_contents(self):
        """Documented limitation (docs/assurance-evaluation.md, Limits): not a guarantee to rely on."""
        before = projection()
        after = projection(units=[{"id": "U1", "premises": [], "evidence": [item("other", kind="analysis")]}])
        self.assertEqual(before["claims"][0]["review"], after["claims"][0]["review"])
        self.assertEqual(run(after)["claims"][0]["review"], {"state": "current"})
