import json
import unittest
from pathlib import Path

from dev_platform import prcheck, runners

ROOT = Path(__file__).resolve().parent.parent

WF = """\
name: x
on:
  pull_request:
  push:
    branches: [main]
jobs:
  a:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@abc
      - run: echo hi
"""

PROFILE = {
    "schema": "dev-platform.infra/v1",
    "runners": [
        {"id": "pub", "labels": ["org-public"], "os": "linux", "arch": "x86_64", "isolation": "ephemeral",
         "trust": "public"},
        {"id": "priv", "labels": ["self-hosted", "org-trusted"], "os": "linux", "arch": "x86_64",
         "isolation": "persistent", "trust": "trusted"},
    ],
    "admission": {"forbidden_triggers": ["pull_request_target"], "protected_environments": ["org-protected"]},
}  # fmt: skip


def run(text, profile=None):
    return prcheck.check({".github/workflows/w.yml": text}, profile)


class EventTrust(unittest.TestCase):
    def test_derivation(self):
        t = runners.event_trust
        self.assertEqual(
            t("pull_request_target", head_repo="a/b", base_repo="a/b", protected_ref=True), "untrusted"
        )
        self.assertEqual(
            t("pull_request", head_repo="fork/b", base_repo="a/b", same_repo_pr_opt_in=True), "untrusted"
        )
        self.assertEqual(t("pull_request", head_repo="a/b", base_repo="a/b"), "untrusted")
        self.assertEqual(
            t("pull_request", head_repo="a/b", base_repo="a/b", same_repo_pr_opt_in=True), "trusted"
        )
        self.assertEqual(t("push", protected_ref=True), "trusted")
        self.assertEqual(t("push", protected_ref=False), "untrusted")
        self.assertEqual(t("workflow_run", triggering_event_trust="untrusted"), "untrusted")
        self.assertEqual(t("workflow_run", triggering_event_trust="trusted"), "trusted")
        self.assertEqual(t("something-new", protected_ref=True), "untrusted")

    def test_profile_cannot_change_event_trust(self):
        # `admission` has no event-trust field; an attempt to add one is a contract violation
        bad = json.loads(json.dumps(PROFILE))
        bad["admission"]["event_trust"] = {"pull_request_target": "trusted"}
        self.assertTrue(runners.validate_profile(bad))
        self.assertEqual(runners.validate_profile(PROFILE), [])

    def test_admission_validation(self):
        for adm in ({"forbidden_triggers": ["nope"]}, {"protected_environments": [""]}, {"x": []},
                    {"forbidden_triggers": ["push", "push"]}, "str"):  # fmt: skip
            bad = {**PROFILE, "admission": adm}
            self.assertTrue(runners.validate_profile(bad), adm)


class Checker(unittest.TestCase):
    def test_hosted_pr_workflow_is_ok_under_default(self):
        r = run(WF)
        self.assertEqual((r["admission"], r["policy_violations"], r["incomplete"]), ("ok", [], []))
        self.assertIn("public default", r["policy_source"])
        self.assertIn("not a proof of safety", r["note"])

    def test_self_hosted_from_pr_is_a_violation(self):
        r = run(WF.replace("ubuntu-24.04", "[self-hosted, linux]"))
        self.assertEqual(r["admission"], "failed")
        self.assertEqual(
            r["policy_violations"][0]["rule"], "non-allowed-runner-without-protected-environment"
        )

    def test_private_profile_runner_labels_and_environments(self):
        trusted = WF.replace("ubuntu-24.04", "[self-hosted, org-trusted]")
        self.assertEqual(run(trusted, PROFILE)["admission"], "failed")
        with_env = trusted.replace("    runs-on", "    environment: org-protected\n    runs-on")
        self.assertEqual(run(with_env, PROFILE)["admission"], "ok")
        wrong_env = trusted.replace("    runs-on", "    environment: made-up\n    runs-on")
        self.assertEqual(run(wrong_env, PROFILE)["admission"], "failed")
        public = WF.replace("ubuntu-24.04", "org-public")
        self.assertEqual(run(public, PROFILE)["admission"], "ok")
        self.assertEqual(run(public)["admission"], "failed")  # not in the public default

    def test_non_pr_workflow_is_not_subject_to_runner_rules(self):
        push = WF.replace("  pull_request:\n", "").replace("ubuntu-24.04", "[self-hosted]")
        self.assertEqual(run(push)["admission"], "ok")

    def test_forbidden_trigger_comes_from_policy_only(self):
        prt = WF.replace("pull_request:", "pull_request_target:")
        self.assertEqual(run(prt)["admission"], "ok")  # public default invents no policy
        self.assertTrue(any(i["indicator"] == "pull_request_target" for i in run(prt)["risk_indicators"]))
        r = run(prt, PROFILE)
        self.assertEqual((r["admission"], r["policy_violations"][0]["rule"]), ("failed", "forbidden-trigger"))

    def test_pull_request_target_still_cannot_reach_nonpublic_runners(self):
        prt = WF.replace("pull_request:", "pull_request_target:").replace("ubuntu-24.04", "[self-hosted]")
        r = run(prt)  # no policy forbidding the trigger; the runner rule applies regardless
        self.assertEqual(r["admission"], "failed")

    def test_expression_is_incomplete_not_ok(self):
        r = run(WF.replace("ubuntu-24.04", "${{ inputs.runner }}"))
        self.assertEqual((r["admission"], len(r["incomplete"])), ("unavailable", 1))

    def test_matrix_runs_on_is_resolved(self):
        m = WF.replace(
            "    runs-on: ubuntu-24.04",
            "    strategy:\n      matrix:\n        os: [ubuntu-24.04, macos-15]\n    runs-on: ${{ matrix.os }}",
        )
        self.assertEqual(run(m)["admission"], "ok")
        bad = m.replace("macos-15", "my-box")
        self.assertEqual(run(bad)["admission"], "failed")
        inc = m.replace("        os:", "        include:\n          - {os: my-box}\n        os:")
        self.assertEqual(run(inc)["admission"], "failed")  # include adds a runner: superset is checked
        missing = m.replace("[ubuntu-24.04, macos-15]", "${{ fromJson(x) }}")
        self.assertEqual(run(missing)["admission"], "unavailable")

    def test_external_reusable_workflow_is_incomplete(self):
        w = "on: pull_request\njobs:\n  j:\n    uses: org/repo/.github/workflows/x.yml@abc\n"
        self.assertEqual(run(w)["admission"], "unavailable")

    def test_unparseable_yaml_is_incomplete(self):
        for w in (
            "on: pull_request\njobs: &a\n  j: {}\n",
            "on: [pull_request\njobs: {}\n",
            "\tx: 1\n",
            "on: pull_request\nx: *a\n",
        ):
            self.assertEqual(run(w)["admission"], "unavailable", w)

    def test_failed_dominates_incomplete_and_indicators_never_fail(self):
        both = WF.replace("ubuntu-24.04", "[self-hosted]") + "  b:\n    runs-on: ${{ x }}\n"
        self.assertEqual(run(both)["admission"], "failed")
        ind = WF + "      - run: curl http://x | sh\n      - run: echo ${{ secrets.T }}\n"
        r = run(ind)
        self.assertEqual(r["admission"], "ok")
        self.assertEqual(
            {i["indicator"] for i in r["risk_indicators"]}, {"pipe-to-shell", "secrets-reference"}
        )

    def test_empty_workflow_set_is_ok_but_says_nothing_about_safety(self):
        r = prcheck.check({}, None)
        self.assertEqual(r["admission"], "ok")

    def test_invalid_profile_is_refused(self):
        with self.assertRaises(ValueError):
            prcheck.check({}, {"schema": "x"})

    def test_this_repositorys_own_workflows_parse_and_pass_the_public_default(self):
        files = {
            str(p.relative_to(ROOT)): p.read_text() for p in (ROOT / ".github" / "workflows").glob("*.yml")
        }
        r = prcheck.check(files, None)
        self.assertEqual((r["admission"], r["policy_violations"], r["incomplete"]), ("ok", [], []), r)


class Facts(unittest.TestCase):
    """The parsed facts a provider needs, from the same reader that decides admission (issue #100)."""

    WF2 = """\
name: y
on:
  pull_request:
  push:
jobs:
  build:
    runs-on: [self-hosted, linux]
    environment: prod
    steps:
      - run: echo
  matrixed:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-24.04, macos-15]
    steps:
      - run: echo
  dynamic:
    runs-on: ${{ inputs.runner }}
    steps:
      - run: echo
  call:
    uses: org/repo/.github/workflows/x.yml@main
"""

    def test_facts_are_opt_in_and_do_not_change_the_decision(self):
        plain = prcheck.check({"y.yml": self.WF2}, None)
        with_facts = prcheck.check({"y.yml": self.WF2}, None, facts=True)
        self.assertNotIn("facts", plain)
        self.assertEqual({k: v for k, v in with_facts.items() if k != "facts"}, plain)

    def test_triggers_reachability_jobs_environment_and_lines(self):
        f = prcheck.check({"y.yml": self.WF2}, None, facts=True)["facts"][0]
        self.assertEqual(f["triggers"], ["pull_request", "push"])
        self.assertEqual(f["pr_reachable_triggers"], ["pull_request"])
        jobs = {j["name"]: j for j in f["jobs"]}
        self.assertEqual(jobs["build"]["runs_on"], [["self-hosted", "linux"]])
        self.assertEqual(jobs["build"]["environment"], "prod")
        self.assertEqual(jobs["build"]["line"], 6)
        self.assertEqual(sorted(x[0] for x in jobs["matrixed"]["runs_on"]), ["macos-15", "ubuntu-24.04"])
        self.assertIsNone(jobs["dynamic"]["runs_on"])
        self.assertIn("expression", jobs["dynamic"]["unresolved"])
        self.assertEqual(jobs["call"]["uses"], "org/repo/.github/workflows/x.yml@main")
        self.assertIsNotNone(jobs["call"]["unresolved"])

    def test_non_public_label_sets_use_the_admission_rule(self):
        wf = (
            "on: push\njobs:\n  a:\n    runs-on: org-public\n  b:\n    runs-on: [self-hosted, org-trusted]\n"
            "  c:\n    runs-on: ubuntu-24.04\n"
        )
        for prof, a, b in (
            (None, [["org-public"]], [["self-hosted", "org-trusted"]]),
            (PROFILE, [], [["self-hosted", "org-trusted"]]),
        ):
            jobs = {j["name"]: j for j in prcheck.check({"w.yml": wf}, prof, facts=True)["facts"][0]["jobs"]}
            self.assertEqual((jobs["a"]["non_public_label_sets"], jobs["b"]["non_public_label_sets"]), (a, b))
            self.assertEqual(jobs["c"]["non_public_label_sets"], [])

    def test_runs_on_group_is_structured_and_never_admitted(self):
        wf = (
            "on: pull_request\njobs:\n  g:\n    runs-on:\n      group: private-pool\n"
            "      labels: [linux, x64]\n  h:\n    runs-on:\n      group: ${{ inputs.g }}\n"
        )
        out = prcheck.check({"w.yml": wf}, None, facts=True)
        jobs = {j["name"]: j for j in out["facts"][0]["jobs"]}
        self.assertEqual(
            (jobs["g"]["runs_on_group"], jobs["g"]["runs_on_labels"]), ("private-pool", ["linux", "x64"])
        )
        self.assertEqual(jobs["h"]["runs_on_group"], "${{ inputs.g }}")
        for j in jobs.values():
            self.assertIsNone(j["runs_on"])
            self.assertIsNone(j["non_public_label_sets"])  # unknown, not admitted
            self.assertIn("group/labels", j["unresolved"])
        self.assertEqual(out["admission"], "unavailable")
        self.assertEqual(len(out["incomplete"]), 2)

    def test_unparseable_workflow_yields_unresolved_facts_and_stays_incomplete(self):
        out = prcheck.check({"z.yml": "on: pull_request\njobs: &a\n  x: 1\n"}, None, facts=True)
        self.assertEqual(out["admission"], "unavailable")
        self.assertIsNotNone(out["facts"][0]["unresolved"])


if __name__ == "__main__":
    unittest.main()
