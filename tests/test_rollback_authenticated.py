"""Rollback selection over approved application releases, authenticated by the independent verifier (#52, #14)."""

import contextlib
import io
import unittest
from pathlib import Path

from dev_platform import appverify, cli, provenance, records
from dev_platform.errors import ConfigError
from tests.helpers import ROOT
from tests.test_app_release_verifier import (
    OTHER,
    PV_PATH,
    PV_SHA,
    REV,
    TREE,
    A,
    Case,
    V,
    approval,
)
from tests.test_authorization import NOW  # noqa: F401
from tests.test_provenance import result

VERIFIER = ROOT / "tools" / "verify_app_release.py"


class Select(Case):
    def setUp(self):
        super().setUp()
        self.releases = {}
        self.results = {records.canonical_digest(self.res): self.res}
        self.paths = []
        self.add("1.0.0", rev=REV)

    def add(self, version, rev):
        """A distinct certified release of 'app' (its own result, so a distinct evidence digest)."""
        res = result(rev=rev, tree=TREE)
        rel = provenance.assemble(
            res,
            name="app",
            version=version,
            source_uri="https://example.invalid/app",
            artifacts=[{"name": "app.tar", "sha256": "b" * 64}],
            resolution="c" * 64,
        )
        self.results[records.canonical_digest(res)] = res
        self.releases[version] = rel
        return rel

    def sign(self, rel, name, **over):
        self.paths.append(self.signed(approval(rel, name=name, **over)))

    def auth(self, rel):
        from datetime import UTC, datetime

        now = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)

        def run(r):
            res = []
            for i, doc in enumerate(self.results.values()):
                res.append(self.w(f"res-{i}.json", doc))
            return A.verify(
                self.w("rel.json", r),
                self.policy,
                V,
                mode="select",
                results=res,
                authorizations=self.paths,
                gh=self.gh,
                now=now,
            )

        return run

    def select(self, current="9.9.9"):
        return provenance.select_rollback(
            "app", current, list(self.releases.values()), self.results, [], authenticate=self.auth(None)
        )

    def test_only_authenticated_approved_releases_are_eligible(self):
        r1, r2 = self.releases["1.0.0"], self.add("1.1.0", "b" * 40)
        self.sign(r1, "a1")
        # r2: approved by someone who is not an approver -> never eligible
        self.paths.append(self.signed(approval(r2, name="a2", login=OTHER), author=OTHER, committer=OTHER))
        out = self.select()
        self.assertEqual(out["approval_authentication"], "verified")
        self.assertEqual([e["version"] for e in out["eligible"]], ["1.0.0"])
        self.assertEqual(out["eligible"][0]["approver"], "rm")
        self.assertEqual([r["version"] for r in out["rejected"]], ["1.1.0"])

    def test_forged_unsigned_approval_makes_nothing_eligible(self):
        r1 = self.releases["1.0.0"]
        self.paths.append(self.w("forged.json", approval(r1, name="forged")))
        out = self.select()
        self.assertEqual(out["eligible"], [])

    def test_revoked_release_is_not_a_rollback_target(self):
        r1 = self.releases["1.0.0"]
        self.sign(r1, "a1")
        self.sign(r1, "rev", decision="revoked", decided_at="2026-10-11T10:00:00Z")
        self.assertEqual(self.select()["eligible"], [])

    def test_current_release_is_never_selected_and_order_is_by_approval_time(self):
        r1, r2 = self.releases["1.0.0"], self.add("1.1.0", "b" * 40)
        self.sign(r1, "a1", decided_at="2026-10-01T00:00:00Z")
        self.sign(r2, "a2", decided_at="2026-10-05T00:00:00Z")
        out = self.select(current="1.1.0")
        self.assertEqual([e["version"] for e in out["eligible"]], ["1.0.0"])
        out = self.select()
        self.assertEqual([e["version"] for e in out["eligible"]], ["1.1.0", "1.0.0"])

    def test_missing_evidence_makes_a_release_ineligible_with_the_reason(self):
        r1 = self.releases["1.0.0"]
        self.sign(r1, "a1")
        self.results.clear()
        out = self.select()
        self.assertEqual(out["eligible"], [])
        self.assertIn("verification-evidence", out["rejected"][0]["reasons"][0])

    def test_unauthenticated_mode_is_labelled(self):
        out = provenance.select_rollback("app", "9.9.9", [], {}, [])
        self.assertEqual(out["approval_authentication"], "unverified")


class Runner(unittest.TestCase):
    def mk(self, **kw):
        args = dict(
            verifier=VERIFIER,
            verifier_sha256=A.sha256_file(VERIFIER),
            platform_verifier=PV_PATH,
            platform_verifier_sha256=PV_SHA,
            policy=ROOT / "trust" / "policy.json",
            results={},
            authorizations=[],
        )
        args.update(kw)
        return appverify.AppVerifier(**args)

    def test_audit_state_is_passed_to_every_candidate_verification(self):
        v = self.mk(audit_state=Path("/audit"))
        i = v.argv_base.index("--audit-state")
        self.assertEqual(v.argv_base[i + 1], "/audit")
        self.assertNotIn("--audit-state", self.mk().argv_base)

    def test_rejections_say_whether_nobody_authorizes_or_it_could_not_be_established(self):
        class Rec:
            def __init__(self, state, auth):
                self.d = {
                    "approval": {"state": state, "authorization_state": auth, "reasons": ["r"],
                                 "authorization_evidence": []},
                    "checks": [], "coverage": {}, "currency": {},
                }  # fmt: skip

            def __call__(self, rel):
                return self.d

        rel = {"application": {"name": "app", "version": "1.0.0"}}
        for state, auth in (("unapproved", "unauthorized"), ("indeterminate", "indeterminate")):
            out = provenance.select_rollback("app", "2.0.0", [rel], {}, [], authenticate=Rec(state, auth))
            self.assertEqual(out["eligible"], [])
            self.assertEqual(out["rejected"][0]["authorization_state"], auth)

    def test_pins_are_enforced(self):
        with self.assertRaises(ConfigError):
            self.mk(verifier_sha256="0" * 64)
        with self.assertRaises(ConfigError):
            self.mk(platform_verifier_sha256="0" * 64)

    def test_cli_requires_the_pins_unless_explicitly_diagnostic(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["rollback", "select", "--application", "app", "--current", "1"])
        self.assertNotEqual(code, 0)
        self.assertIn("authenticated by the pinned independent verifier", err.getvalue())

    def current_rec(self, **cur):
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        c = {"purpose": "operational", "status": "current", "observed_at": now.isoformat(),
             "valid_until": (now + timedelta(seconds=300)).isoformat()}  # fmt: skip
        c.update(cur)
        return {"approval": {"state": "approved"}, "currency": c}

    def test_an_approval_is_usable_only_with_a_fresh_current_state_verification(self):
        from datetime import UTC, datetime, timedelta

        appverify.AppVerifier._current(self.current_rec())  # fresh: accepted
        old = datetime.now(UTC) - timedelta(hours=1)
        for bad in (
            {"purpose": "historical"},
            {"status": "unverifiable"},
            {"observed_at": old.isoformat(), "valid_until": (old + timedelta(seconds=300)).isoformat()},
            {"observed_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()},
            {"observed_at": None},
        ):
            with self.assertRaises(ConfigError, msg=bad):
                appverify.AppVerifier._current(self.current_rec(**bad))
        rec = self.current_rec()
        del rec["currency"]  # a record with no currency block at all
        with self.assertRaises(ConfigError):
            appverify.AppVerifier._current(rec)

    def test_non_approvals_need_no_currency(self):
        appverify.AppVerifier._current({"approval": {"state": "unapproved"}})

    def test_subprocess_verifier_end_to_end_without_authorizations(self):
        c = Select("setUp")
        c.setUp()
        try:
            rel = c.releases["1.0.0"]
            pol = c.w("policy.json", c.policy)
            rec = self.mk(policy=pol, results=c.results)(rel)
            # current-state decision with an evidence repository that cannot be read here: fails closed
            self.assertEqual(rec["approval"]["state"], "indeterminate")
            self.assertIn(
                "authorization-currency", {x["id"] for x in rec["checks"] if x["status"] == "failed"}
            )
            self.assertEqual(rec["subject"]["release_sha256"], records.canonical_digest(rel))
        finally:
            c.doCleanups()


if __name__ == "__main__":
    unittest.main()
