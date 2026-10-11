import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from dev_platform import lifecycle, planning
from dev_platform.errors import ConfigError

ROOT = Path(__file__).resolve().parent.parent
POLICY = planning.load_policy(ROOT / "planning" / "release-policy.json")
D = "a" * 64


def rec(state="verified-unaccepted", digest=D, status="passed"):
    return {
        "schema": "dev-platform.verification/v1",
        "subject": {"archive_sha256": digest},
        "checks": [{"id": "x", "status": status}],
        "acceptance": {"state": state, "reasons": ["no authenticated, authorized, in-force approval"]},
    }


def facts(**kw):
    f = {
        "planning": {"ready": True},
        "archive_sha256": D,
        "ci_verification": rec(),
        "independent_verification": rec(),
        "published": {"immutable": True},
        "notices": [],
    }
    f.update(kw)
    return f


def verifier_result(record):
    return lifecycle.VerifierResult(record, lifecycle.VerifierResult._token)


class States(unittest.TestCase):
    def test_progression(self):
        self.assertEqual(lifecycle.derive({"planning": {"ready": False}}).state, "planned")
        self.assertEqual(lifecycle.derive({"planning": {"ready": True}}).state, "implementation-complete")
        self.assertEqual(lifecycle.derive(facts(independent_verification=None)).state, "candidate-built")
        self.assertEqual(
            lifecycle.derive(facts(published={"immutable": False})).state, "independently-verified"
        )
        self.assertEqual(lifecycle.derive(facts()).state, "verified-unaccepted")

    def test_planning_cannot_skip_ahead(self):
        # a complete milestone with no artifact is only implementation-complete
        self.assertEqual(
            lifecycle.derive({"planning": {"ready": True}, "archive_sha256": D}).state,
            "implementation-complete",
        )

    def test_digest_mismatch_blocks(self):
        f = facts(independent_verification=rec(digest="b" * 64))
        self.assertEqual(lifecycle.derive(f).state, "candidate-built")
        f = facts(ci_verification=rec(digest="b" * 64))
        self.assertEqual(lifecycle.derive(f).state, "implementation-complete")

    def test_failed_check_blocks(self):
        f = facts(independent_verification=rec(status="failed"))
        self.assertEqual(lifecycle.derive(f).state, "candidate-built")

    def test_independent_must_be_a_separate_record(self):
        r = rec()
        self.assertEqual(
            lifecycle.derive(facts(ci_verification=r, independent_verification=r)).state, "candidate-built"
        )

    def test_prerelease_never_past_independently_verified(self):
        f = facts(independent_verification=rec("pre-release"))
        d = lifecycle.derive(f)
        self.assertEqual(d.state, "independently-verified")

    def test_accepted_claim_in_a_record_is_not_authority(self):
        d = lifecycle.derive(facts(independent_verification=rec("accepted")))
        self.assertEqual(d.state, "verified-unaccepted")
        self.assertTrue(any("not authority" in r for r in d.reasons))

    def test_milestone_closure_label_or_merge_cannot_accept(self):
        f = facts(milestone={"state": "closed"}, labels=["accepted"], merged=True, workflow="success")
        self.assertEqual(lifecycle.derive(f).state, "verified-unaccepted")

    def test_accepted_only_from_verifier_result(self):
        d = lifecycle.derive(facts(verifier=verifier_result(rec("accepted"))))
        self.assertEqual(d.state, "accepted")

    def test_verifier_result_cannot_be_forged(self):
        with self.assertRaises(TypeError):
            lifecycle.VerifierResult(rec("accepted"))
        d = lifecycle.derive(facts(verifier={"record": rec("accepted")}))
        self.assertEqual(d.state, "verified-unaccepted")

    def test_verifier_result_for_another_digest_does_not_accept(self):
        d = lifecycle.derive(facts(verifier=verifier_result(rec("accepted", digest="c" * 64))))
        self.assertEqual(d.state, "verified-unaccepted")

    def test_verifier_not_accepting_keeps_unaccepted(self):
        d = lifecycle.derive(facts(verifier=verifier_result(rec("verified-unaccepted"))))
        self.assertEqual(d.state, "verified-unaccepted")

    def test_unauthenticated_notice_suspends_but_is_not_a_governance_decision(self):
        for kind in ("revoked", "superseded", "advisory"):
            d = lifecycle.derive(facts(notices=[{"kind": kind, "digest": D, "reference": "someone said so"}]))
            doc = d.doc()
            self.assertEqual(
                (doc["state"], doc["usable"], doc["governance_decision"]), ("suspended", False, False)
            )
            self.assertEqual(doc["decisions"], [])
            self.assertEqual(
                doc["base_state"], "verified-unaccepted"
            )  # the authorization outcome is untouched
        d = lifecycle.derive(facts(notices=[{"kind": "revoked", "digest": "d" * 64}]))
        self.assertIsNone(d.overlay)

    def test_unauthenticated_revocation_cannot_unaccept(self):
        d = lifecycle.derive(
            facts(verifier=verifier_result(rec("accepted")), notices=[{"kind": "revoked", "digest": D}])
        )
        self.assertEqual(d.base_state if hasattr(d, "base_state") else d.state, "accepted")
        self.assertEqual((d.overlay, d.governance_decision), ("suspended", False))

    def test_authenticated_revocation_is_a_governance_decision(self):
        r = rec("verified-unaccepted")
        r["acceptance"]["authorization_evidence"] = [
            {
                "id": "a1",
                "status": "authentic",
                "decision": "approved",
                "decided_at": "2026-10-10T00:00:00Z",
                "approver": "o",
            },
            {
                "id": "a2",
                "status": "authentic",
                "decision": "revoked",
                "decided_at": "2026-10-11T00:00:00Z",
                "approver": "o",
                "supersedes": ["a1"],
            },
        ]
        d = lifecycle.derive(facts(verifier=verifier_result(r)))
        self.assertEqual((d.doc()["state"], d.usable, d.governance_decision), ("revoked", False, True))
        self.assertEqual([x["id"] for x in d.decisions], ["a1", "a2"])

    def test_ignored_records_never_revoke(self):
        r = rec("verified-unaccepted")
        r["acceptance"]["authorization_evidence"] = [
            {"id": "x", "status": "ignored", "decision": "revoked", "decided_at": "2026-10-11T00:00:00Z"}
        ]
        d = lifecycle.derive(facts(verifier=verifier_result(r)))
        self.assertEqual((d.overlay, d.governance_decision, d.usable), (None, False, True))

    def test_a_later_authentic_approval_overrides_an_earlier_revocation(self):
        r = rec("verified-unaccepted")
        r["acceptance"]["authorization_evidence"] = [
            {"id": "a", "status": "authentic", "decision": "revoked", "decided_at": "2026-10-10T00:00:00Z"},
            {
                "id": "b",
                "status": "authentic",
                "decision": "approved",
                "decided_at": "2026-10-11T00:00:00Z",
                "supersedes": ["a"],
            },
        ]
        self.assertIsNone(lifecycle.derive(facts(verifier=verifier_result(r))).overlay)

    def test_no_transition_targets_accepted(self):
        for cur in lifecycle.STATES:
            with self.assertRaises(ConfigError):
                lifecycle.advance(cur, "accepted", facts(verifier=verifier_result(rec("accepted"))))

    def test_advance_requires_evidence_and_adjacent_edge(self):
        with self.assertRaises(ConfigError):
            lifecycle.advance("planned", "candidate-built", facts())
        with self.assertRaises(ConfigError):
            lifecycle.advance(
                "candidate-built", "independently-verified", facts(independent_verification=None)
            )
        lifecycle.advance("candidate-built", "independently-verified", facts())
        with self.assertRaises(ConfigError):
            lifecycle.advance("verified-unaccepted", "planned", facts())

    def test_run_verifier_checks_pin_before_running(self):
        with tempfile.TemporaryDirectory() as td:
            v = Path(td) / "v.py"
            v.write_text("raise SystemExit(0)")
            with self.assertRaises(ConfigError):
                lifecycle.run_verifier(v, hashlib.sha256(b"other").hexdigest(), [])

    def test_only_lifecycle_run_verifier_constructs_results(self):
        # static: no other module in the platform constructs VerifierResult
        for p in (ROOT / "src" / "dev_platform").glob("*.py"):
            if p.name != "lifecycle.py":
                self.assertNotIn("VerifierResult(", p.read_text(), p.name)

    def test_lifecycle_names_accepted_only_after_a_verifier_result(self):
        src = (ROOT / "src/dev_platform/lifecycle.py").read_text()
        self.assertEqual(src.count('state = "accepted"'), 1)
        before = src[: src.index('state = "accepted"')]
        self.assertIn("isinstance(v, VerifierResult)", before[-600:])


class Versions(unittest.TestCase):
    def check(self, prev, new, kinds, **kw):
        return lifecycle.check_version(prev, new, kinds, POLICY, **kw)

    def test_patch_and_security(self):
        self.assertEqual(self.check("0.1.2", "0.1.3", ["security-fix"]), [])
        self.assertEqual(self.check("0.1.2", "0.1.3-rc.1", ["bugfix"]), [])

    def test_feature_needs_minor(self):
        self.assertTrue(self.check("0.1.2", "0.1.3", ["feature"]))
        self.assertEqual(self.check("0.1.2", "0.2.0", ["feature"]), [])

    def test_zero_x_breaking_is_minor(self):
        self.assertEqual(self.check("0.1.2", "0.2.0", ["breaking-evidence-schema"]), [])
        self.assertTrue(self.check("0.1.2", "0.1.3", ["breaking-config"]))

    def test_not_after_previous(self):
        self.assertTrue(self.check("0.1.2", "0.1.2", []))
        self.assertTrue(self.check("0.1.2", "0.1.1", []))
        self.assertTrue(self.check("0.1.2", "0.1.2-rc.1", []))

    def test_unknown_kind_and_identifier_fail_closed(self):
        with self.assertRaises(ConfigError):
            self.check("0.1.2", "0.1.3", ["whatever"])
        self.assertTrue(self.check("0.1.2", "0.1.3-snapshot.1", []))
        with self.assertRaises(ConfigError):
            self.check("0.1.2", "v0.1.3", [])

    def test_one_zero_needs_criteria(self):
        self.assertTrue(self.check("0.9.0", "1.0.0", ["feature"]))
        crit = POLICY["versioning"]["one_zero_criteria"]
        self.assertEqual(self.check("0.9.0", "1.0.0", ["breaking-config"], criteria_met=crit), [])

    def test_manifest_diff(self):
        old = {
            "schema": "s1",
            "profiles": {"p": {"tools": {"t": {"version": "1.2.3"}, "u": {"version": "1.0.0"}}}},
        }
        new = copy.deepcopy(old)
        self.assertEqual(lifecycle.diff_manifests(old, new), [])
        new["profiles"]["p"]["tools"]["t"]["version"] = "1.2.4"
        self.assertEqual(lifecycle.diff_manifests(old, new), ["toolchain-patch"])
        new["profiles"]["p"]["tools"]["t"]["version"] = "1.3.0"
        self.assertEqual(lifecycle.diff_manifests(old, new), ["toolchain-minor"])
        new["profiles"]["p"]["tools"]["t"]["version"] = "2.0.0"
        del new["profiles"]["p"]["tools"]["u"]
        self.assertEqual(lifecycle.diff_manifests(old, new), ["tool-removed", "toolchain-major"])
        # a pin change always requires a new release: it can never be "no change" at patch level hidden
        self.assertTrue(self.check("0.1.2", "0.1.3", lifecycle.diff_manifests(old, new)))

    def test_schema_diff(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            (Path(a) / "x.json").write_text(json.dumps({"$id": "x/v1"}))
            (Path(b) / "x.json").write_text(json.dumps({"$id": "x/v2"}))
            (Path(b) / "y.json").write_text("{}")
            self.assertEqual(
                lifecycle.diff_schemas(Path(a), Path(b)), ["breaking-evidence-schema", "schema-added"]
            )

    def test_patch_plan(self):
        out = lifecycle.patch_plan(["0.1.0", "0.1.2"], ["0.1.0", "0.1.2"], POLICY)
        self.assertEqual(
            out, [{"line": "0.1", "action": "patch", "version": "0.1.3", "kind": "security-fix"}]
        )
        out = lifecycle.patch_plan(["0.1.2"], ["0.1.2", "0.2.0"], POLICY)
        self.assertEqual(out[0]["action"], "no-patch")


SECTIONS = "\n".join(f"## {s}\nx" for s in POLICY["milestone"]["required_sections"])


def snap(items=(), desc=SECTIONS, external=None):
    return {
        "milestone": {"title": "v0.2.0", "state": "open", "description": desc},
        "items": list(items),
        "external": external or {},
    }


def issue(n, state="closed", ms="v0.2.0"):
    return {
        "number": n,
        "title": f"i{n}",
        "state": state,
        "is_pr": False,
        "merged": False,
        "body": "",
        "labels": [],
        "milestone": ms,
    }


def pr(n, body="", state="closed", merged=True, ms="v0.2.0"):
    return {
        "number": n,
        "title": f"p{n}",
        "state": state,
        "is_pr": True,
        "merged": merged,
        "body": body,
        "labels": [],
        "milestone": ms,
    }


class Readiness(unittest.TestCase):
    def test_ready(self):
        r = planning.readiness(snap([issue(1), pr(2, "Closes #1")]), POLICY)
        self.assertTrue(r["ready"])
        self.assertEqual(r["implies"], "implementation-complete")
        self.assertIn("not verification evidence", r["disclaimer"])

    def test_open_work_blocks(self):
        r = planning.readiness(snap([issue(1, "open"), pr(2, state="open", merged=False)]), POLICY)
        self.assertEqual({b["code"] for b in r["blockers"]}, {"open-issue", "open-pull-request"})

    def test_empty_and_incomplete_description_block(self):
        r = planning.readiness(snap([], desc="## Objective\nx"), POLICY)
        codes = [b["code"] for b in r["blockers"]]
        self.assertIn("milestone-empty", codes)
        self.assertEqual(
            codes.count("milestone-section-missing"), len(POLICY["milestone"]["required_sections"]) - 1
        )

    def test_closed_milestone_state_is_not_an_input(self):
        s = snap([issue(1, "open")])
        s["milestone"]["state"] = "closed"
        self.assertFalse(planning.readiness(s, POLICY)["ready"])

    def test_trace_is_warning_in_open_source_blocker_in_regulated(self):
        s = snap([issue(1)])
        self.assertEqual(
            planning.readiness(s, POLICY)["warnings"][0]["code"], "closed-issue-without-merged-pr"
        )
        reg = copy.deepcopy(POLICY)
        reg["assurance"] = "regulated"
        codes = {b["code"] for b in planning.readiness(s, reg)["blockers"]}
        self.assertIn("closed-issue-without-merged-pr", codes)
        self.assertIn("external-attestation-missing", codes)

    def test_regulated_requires_named_external_attestations(self):
        reg = copy.deepcopy(POLICY)
        reg["assurance"] = "regulated"
        ext = {n: {"ok": True, "reference": "r"} for n in reg["profiles"]["regulated"]["requires_external"]}
        self.assertTrue(planning.readiness(snap([issue(1), pr(2, "fixes #1")], external=ext), reg)["ready"])
        ext["change-authorization"] = {"ok": False, "reference": "r"}
        self.assertFalse(planning.readiness(snap([issue(1), pr(2, "fixes #1")], external=ext), reg)["ready"])

    def test_policy_must_define_profile(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "p.json"
            bad = copy.deepcopy(POLICY)
            bad["assurance"] = "nope"
            p.write_text(json.dumps(bad))
            with self.assertRaises(ConfigError):
                planning.load_policy(p)

    def test_assignment_follows_closed_issue(self):
        s = snap([issue(1, ms="v0.3.0"), pr(2, "Closes #1", ms=None), pr(3, "no link", ms=None)])
        self.assertEqual(planning.plan_assignments(s), [{"number": 2, "milestone": "v0.3.0"}])
        s = snap([issue(1, ms="v0.3.0"), issue(5, ms="v0.2.0"), pr(2, "Closes #1, fixes #5", ms=None)])
        self.assertIsNone(planning.plan_assignments(s)[0]["milestone"])

    def test_notes_are_descriptive_not_evidence(self):
        text = planning.release_notes(
            snap([issue(1), pr(2, "Closes #1")]), "0.2.0", rec("verified-unaccepted")
        )
        self.assertIn("p2 (#2)", text)
        self.assertIn("not replaced by this text", text)
        self.assertNotIn("accepted by", text.lower())

    def test_manifest_carries_no_authority(self):
        s = snap([issue(1), pr(2, "Closes #1")])
        rd = planning.readiness(s, POLICY)
        m = planning.release_manifest("0.2.0", s, rd, {"state": "planned"}, {"archive_sha256": D}, rec(), [])
        self.assertEqual(m["verification"]["acceptance_state"], "verified-unaccepted")
        self.assertTrue(m["authority"].startswith("none"))


class Cli(unittest.TestCase):
    """Dry runs through the CLI over an offline snapshot and the real v0.1.2 records."""

    def run_cli(self, *argv):
        import contextlib
        import io

        from dev_platform import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["plan", *argv])
        return code, out.getvalue()

    def snapshot(self, td, open_issue=False):
        p = Path(td) / "snap.json"
        p.write_text(json.dumps(snap([issue(1, "open" if open_issue else "closed"), pr(2, "Closes #1")])))
        return str(p)

    def test_readiness_exit_codes(self):
        with tempfile.TemporaryDirectory() as td:
            code, out = self.run_cli("readiness", "--milestone", "v0.2.0", "--snapshot", self.snapshot(td))
            self.assertEqual((code, json.loads(out)["ready"]), (0, True))
            code, out = self.run_cli(
                "readiness", "--milestone", "v0.2.0", "--snapshot", self.snapshot(td, True)
            )
            self.assertEqual((code, json.loads(out)["ready"]), (1, False))

    def test_real_v012_records_stay_verified_unaccepted(self):
        r = ROOT / "releases" / "0.1.2"
        with tempfile.TemporaryDirectory() as td:
            code, out = self.run_cli(
                "state", "--milestone", "v0.2.0", "--snapshot", self.snapshot(td),
                "--archive-sha256", "d8aee29970935783889b33c89c10ed5c017357a105a227db1bd90390b654a24d",
                "--ci-verification", str(r / "verification.ci.json"),
                "--independent-verification", str(r / "verification.independent.json"),
                "--immutable",
            )  # fmt: skip
            d = json.loads(out)
            self.assertEqual((code, d["state"], d["usable"]), (0, "verified-unaccepted", True))
            self.assertTrue(any("no authenticated authorization" in x for x in d["reasons"]))

    def test_not_immutable_stops_before_verified_unaccepted(self):
        r = ROOT / "releases" / "0.1.2"
        with tempfile.TemporaryDirectory() as td:
            _, out = self.run_cli(
                "state", "--milestone", "v0.2.0", "--snapshot", self.snapshot(td),
                "--archive-sha256", "d8aee29970935783889b33c89c10ed5c017357a105a227db1bd90390b654a24d",
                "--ci-verification", str(r / "verification.ci.json"),
                "--independent-verification", str(r / "verification.independent.json"),
            )  # fmt: skip
            self.assertEqual(json.loads(out)["state"], "independently-verified")

    def test_verifier_requires_an_operator_pin(self):
        v = str(ROOT / "tools" / "verify_release.py")
        with tempfile.TemporaryDirectory() as td:
            snapf = self.snapshot(td)
            for extra in ([], ["--verifier-sha256", "0" * 64]):
                code, _ = self.run_cli(
                    "state", "--milestone", "v0.2.0", "--snapshot", snapf,
                    "--archive-sha256", D, "--verifier", v, *extra,
                )  # fmt: skip
                self.assertEqual(code, 2)

    def test_version_check_cli_rejects_toolchain_change_as_patch(self):
        with tempfile.TemporaryDirectory() as td:
            old = Path(td) / "old.json"
            new = Path(td) / "new.json"
            old.write_text(
                json.dumps({"schema": "s", "profiles": {"p": {"tools": {"t": {"version": "1.0.0"}}}}})
            )
            new.write_text(
                json.dumps({"schema": "s", "profiles": {"p": {"tools": {"t": {"version": "2.0.0"}}}}})
            )
            code, out = self.run_cli(
                "version-check", "--previous", "0.1.2", "--new", "0.1.3",
                "--old-manifest", str(old), "--new-manifest", str(new),
            )  # fmt: skip
            self.assertEqual(code, 1)
            self.assertIn("toolchain-major", json.loads(out)["kinds"])
            code, _ = self.run_cli(
                "version-check", "--previous", "0.1.2", "--new", "0.2.0",
                "--old-manifest", str(old), "--new-manifest", str(new),
            )  # fmt: skip
            self.assertEqual(code, 0)

    def test_policy_in_repo_is_loadable_and_assurance_is_open_source(self):
        self.assertEqual(POLICY["assurance"], "open-source")
        self.assertIn("regulated", POLICY["profiles"])


class NoSecondAuthority(unittest.TestCase):
    def test_planning_code_never_emits_accepted(self):
        src = (ROOT / "src/dev_platform/planning.py").read_text()
        self.assertNotIn('"accepted"', src)

    def test_release_workflow_unchanged_publisher(self):
        # the single publisher stays release.yml; planning adds no workflow that creates releases
        for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
            if wf.name != "release.yml":
                self.assertNotIn("gh release create", wf.read_text(), wf.name)


if __name__ == "__main__":
    unittest.main()


class Queue(unittest.TestCase):
    def test_priority_not_exclusivity(self):
        def it(n, ms, labels=(), body=""):
            return {"number": n, "title": f"t{n}", "state": "open", "is_pr": False, "merged": False,
                    "body": body, "labels": list(labels), "milestone": ms}  # fmt: skip

        items = [
            it(1, "v0.3.0"),
            it(2, "v0.2.0"),
            it(3, "v0.1.3", ["owner-decision"]),
            it(4, None),
            it(5, "v0.2.0", body="Blocked by #2"),
            it(6, "v0.2.0", ["proposal"]),
        ]
        q = planning.work_queue(items)
        self.assertEqual(
            [r["number"] for r in q["eligible"]], [2, 1, 4]
        )  # held v0.1.3 does not block v0.2.0/v0.3.0
        self.assertEqual([r["number"] for r in q["held"]], [3, 6])
        self.assertEqual(q["blocked"][0]["blocked_by"], [2])
