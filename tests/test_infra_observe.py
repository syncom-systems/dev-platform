"""Discovery is read-only; audit and drift report, never repair; unreadable is unknown, never compliant."""

import json
import subprocess
import unittest

from dev_platform import infra_observe as O
from tests.test_infra_config import self_hosted

API = {
    "/orgs/example-org/actions/runner-groups": {
        "runner_groups": [
            {
                "id": 1,
                "name": "trusted-builds",
                "visibility": "selected",
                "allows_public_repositories": False,
                "restricted_to_workflows": True,
            }
        ]
    },
    "/orgs/example-org/actions/runner-groups/1/runners": {
        "runners": [
            {
                "name": "builder-1",
                "os": "Linux",
                "status": "online",
                "labels": [{"name": n} for n in ("self-hosted", "linux", "x64", "build")],
            }
        ]
    },
    "/orgs/example-org/actions/runner-groups/1/repositories": {"repositories": [{"name": "app"}]},
    "/repos/example-org/app": {"private": True},
    "/repos/example-org/app/actions/runners": {"runners": []},
    "/repos/example-org/app/actions/permissions/workflow": {"default_workflow_permissions": "read"},
    "/repos/example-org/app/rulesets": [{"name": "main", "enforcement": "active"}],
    "/repos/example-org/app/actions/permissions/fork-pr-contributor-approval": {
        "approval_policy": "first_time_contributors"
    },
    "/repos/example-org/site": {"private": False},
    "/repos/example-org/site/actions/runners": {"runners": []},
    "/repos/example-org/site/actions/permissions/workflow": {"default_workflow_permissions": "read"},
    "/repos/example-org/site/rulesets": [],
    "/repos/example-org/site/actions/permissions/fork-pr-contributor-approval": {
        "approval_policy": "all_external_contributors"
    },
}


def paged(doc):
    if isinstance(doc, list):
        return [doc[:1], doc[1:]]
    (key,) = [k for k, v in doc.items() if isinstance(v, list)]
    return [{**doc, key: doc[key][:1]}, {**doc, key: doc[key][1:]}]


def fake(api, calls):
    def runner(argv, **kw):
        calls.append(argv)
        path = argv[-1].split("?")[0]
        if path in api:
            doc = api[path]
            if "--slurp" in argv:  # every list endpoint is read to its last page (here: two pages)
                doc = paged(doc)
            return subprocess.CompletedProcess(argv, 0, json.dumps(doc), "")
        return subprocess.CompletedProcess(argv, 1, "", "HTTP 403: Resource not accessible by integration")

    return runner


class Discover(unittest.TestCase):
    def test_get_only_and_no_secrets(self):
        calls = []
        snap = O.discover("example-org", ["app", "site"], fake(API, calls))
        self.assertEqual(snap["errors"], [])
        for argv in calls:
            self.assertEqual(argv[:4], ["gh", "api", "--method", "GET"])
            self.assertIn(argv[4:-1], ([], ["--paginate", "--slurp"]))
            self.assertNotIn("secret", argv[-1])
            if "--paginate" in argv:
                self.assertTrue(argv[-1].endswith("per_page=100"))
        self.assertEqual(
            sum("--paginate" in a for a in calls), 7
        )  # groups, members, repositories, 2x(runners, rulesets)
        self.assertEqual(snap["runner_groups"][0]["repositories"], ["app"])

    def test_unreadable_is_recorded_as_unknown(self):
        calls = []
        api = {k: v for k, v in API.items() if "runner-groups" not in k}
        snap = O.discover("example-org", ["app"], fake(api, calls))
        self.assertIsNone(snap["runner_groups"])
        self.assertTrue(snap["errors"])
        rows = O.drift(self_hosted(), snap)
        self.assertIn("unknown", {r["status"] for r in rows if r["runner_group"] == "trusted-builds"})

    def test_refuses_anything_but_plain_paths(self):
        for path in ("/repos/a/b -X DELETE", "/graphql", "repos/a/b", "/repos/../x", "/repos/a/b --input f"):
            with self.assertRaises(ValueError, msg=path):
                O._get(path, runner=lambda *a, **k: self.fail("must not run"))
        with self.assertRaises(ValueError):
            O.discover("a b", [], runner=lambda *a, **k: self.fail("must not run"))


class Pagination(unittest.TestCase):
    def test_every_page_is_merged(self):
        api = dict(API)
        many = [
            {"name": f"r{i}", "os": "Linux", "status": "online", "labels": [{"name": "self-hosted"}]}
            for i in range(3)
        ]
        api["/repos/example-org/app/actions/runners"] = {"total_count": 3, "runners": many}
        snap = O.discover("example-org", ["app"], fake(api, []))
        self.assertEqual([r["name"] for r in snap["repos"]["app"]["repo_level_runners"]], ["r0", "r1", "r2"])

    def test_an_unexpected_page_shape_is_an_error(self):
        def runner(argv, **kw):
            return subprocess.CompletedProcess(argv, 0, json.dumps({"runners": []}), "")

        self.assertIn("_error", O._get("/repos/a/b/actions/runners", runner, "runners"))


class Drift(unittest.TestCase):
    def snap(self, **over):
        snap = O.discover("example-org", ["app", "site"], fake(API, []))
        snap.update(over)
        return snap

    def test_matching_infrastructure_has_only_known_differences(self):
        rows = O.drift(self_hosted(), self.snap())
        self.assertEqual(rows, [])

    def test_differences_and_who_may_act(self):
        snap = self.snap()
        snap["runner_groups"][0]["allows_public_repositories"] = True
        snap["runner_groups"][0]["runners"] = []
        snap["repos"]["app"]["default_workflow_permissions"] = "write"
        snap["repos"]["app"]["repo_level_runners"] = [{"name": "stray", "labels": ["self-hosted"]}]
        rows = {(r["field"], r["scope"]) for r in O.drift(self_hosted(), snap)}
        self.assertIn(("allows_public_repositories", "infra"), rows)
        self.assertIn(
            ("runner linux-build", "infra"), rows
        )  # declared, but no registered runner has its labels
        self.assertIn(("default_token", "repository"), rows)
        self.assertIn(("runner_registration", "infra"), rows)

    def test_missing_group_and_repository(self):
        snap = self.snap(runner_groups=[])
        del snap["repos"]["site"]
        rows = O.drift(self_hosted(), snap)
        self.assertIn(("runner_group", "absent"), {(r["field"], r["observed"]) for r in rows})
        self.assertIn(("site", "unknown"), {(r["repo"], r["status"]) for r in rows})


class AuditUnknowns(unittest.TestCase):
    def test_a_snapshot_nobody_could_read_is_not_clean(self):
        snap = O.discover("example-org", ["app"], fake({}, []))
        findings = O.audit(snap)
        self.assertTrue(findings)
        self.assertEqual({f["id"] for f in findings}, {"UNKNOWN"})
        self.assertTrue(all(f["severity"] == "high" for f in findings))

    def test_unreadable_group_members_and_visibility_are_judged_conservatively(self):
        snap = O.discover("example-org", ["app", "site"], fake(API, []))
        snap["runner_groups"][0].update(runners=None, allows_public_repositories=None)
        snap["repos"]["site"].update(
            private=None, repo_level_runners=[{"name": "box", "labels": ["self-hosted"]}]
        )
        ids = {f["id"] for f in O.audit(snap)}
        for fid in ("UNKNOWN", "GRP-PUBLIC", "PUBLIC-PERSISTENT"):
            self.assertIn(fid, ids)


class Audit(unittest.TestCase):
    def test_findings(self):
        snap = O.discover("example-org", ["app", "site"], fake(API, []))
        self.assertEqual([f["id"] for f in O.audit(snap)], [])
        snap["runner_groups"][0].update(
            allows_public_repositories=True, visibility="all", restricted_to_workflows=False
        )
        snap["repos"]["site"]["repo_level_runners"] = [{"name": "box", "labels": ["self-hosted"]}]
        snap["repos"]["site"]["fork_pr_approval"] = "first_time_contributors"
        ids = [f["id"] for f in O.audit(snap)]
        for fid in (
            "GRP-PUBLIC",
            "GRP-ALL",
            "GRP-NO-WORKFLOW-RESTRICTION",
            "RUN-UNGROUPED",
            "PUBLIC-PERSISTENT",
            "PUBLIC-FORK-APPROVAL",
        ):
            self.assertIn(fid, ids)
        self.assertEqual(ids[0], "GRP-PUBLIC")  # critical first
        for f in O.audit(snap):
            self.assertIn("requires", f["remediation"])


if __name__ == "__main__":
    unittest.main()
