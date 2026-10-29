"""Guarded `runs-on` expressions: one statically provable shape is read, everything else stays unavailable.

Synthetic workflows and runners only. The guard is never evaluated: the analyzer proves which events can reach
each branch and applies the existing admission and event-trust rules to it."""

import json
import os
import subprocess
import sys
import unittest

from dev_platform import infra_config as C
from dev_platform import prcheck
from tests.helpers import ROOT, tmpdir
from tests.test_infra_config import self_hosted

PRIV = ["self-hosted", "org-trusted"]
PROFILE = {
    "schema": "dev-platform.infra/v1",
    "runners": [
        {"id": "pub", "labels": ["org-public"], "os": "linux", "arch": "x86_64", "isolation": "ephemeral",
         "trust": "public"},
        {"id": "priv", "labels": PRIV, "os": "linux", "arch": "x86_64", "isolation": "persistent",
         "trust": "trusted"},
    ],
    "admission": {"forbidden_triggers": [], "protected_environments": ["org-protected"]},
}  # fmt: skip
GUARD = "github.event.pull_request.head.repo.full_name == github.repository"
SELF_LABELS = 'fromJSON(\'["self-hosted", "org-trusted"]\')'
SENTINEL = "'dp-no-runner'"


def expr(guard=GUARD, a=SELF_LABELS, b=SENTINEL):
    return f"${{{{ {guard} && {a} || {b} }}}}"


def wf(runs_on, on="pull_request", extra=""):
    return f"on: {on}\njobs:\n  a:\n    runs-on: {runs_on}\n{extra}    steps:\n      - run: echo\n"


def check(text, profile=PROFILE, opt_in=True, facts=False):
    return prcheck.check({"w.yml": text}, profile, facts=facts, same_repo_pr_opt_in=opt_in)


class Supported(unittest.TestCase):
    def test_the_guarded_form_is_admitted_for_same_repository_pull_requests_on_opt_in(self):
        out = check(wf(expr()))
        self.assertEqual((out["admission"], out["policy_violations"], out["incomplete"]), ("ok", [], []))

    def test_other_events_cannot_reach_the_privileged_branch(self):
        out = check(wf(expr(), on="[pull_request, push, schedule, workflow_dispatch]"))
        self.assertEqual(out["admission"], "ok")

    def test_branch_facts_say_what_reaches_each_branch(self):
        job = check(wf(expr()), facts=True)["facts"][0]["jobs"][0]
        self.assertEqual(job["runs_on"], [PRIV, ["dp-no-runner"]])
        self.assertEqual(job["non_public_label_sets"], [])
        self.assertEqual(job["guard"]["true_reachable_by"], ["pull_request"])
        self.assertEqual(job["guard"]["true_event_trust"], "trusted")
        self.assertIsNone(job["unresolved"])

    def test_a_public_privileged_branch_needs_no_opt_in(self):
        out = check(wf(expr(a="'org-public'")), opt_in=False)
        self.assertEqual(out["admission"], "ok")

    def test_a_branch_no_trigger_can_reach_is_not_judged(self):
        # workflow_run payloads carry no pull_request: the guard is false, only the fallback is selected
        out = check(wf(expr(), on="workflow_run"), opt_in=False)
        self.assertEqual(out["admission"], "ok")
        job = check(wf(expr(), on="workflow_run"), opt_in=False, facts=True)["facts"][0]["jobs"][0]
        self.assertEqual(job["guard"]["true_reachable_by"], [])

    def test_the_yaml_may_quote_the_expression_and_vary_the_spacing(self):
        e = expr().replace("&&", " &&  ").replace("||", "  ||")
        self.assertEqual(check(wf(f'"{e}"'))["admission"], "ok")

    def test_static_runs_on_lists_are_unchanged(self):
        for opt_in in (False, True):
            self.assertEqual(check(wf("ubuntu-24.04"), opt_in=opt_in)["admission"], "ok")
            self.assertEqual(check(wf("org-public"), opt_in=opt_in)["admission"], "ok")
            self.assertEqual(check(wf("[self-hosted, org-trusted]"), opt_in=opt_in)["admission"], "failed")
            self.assertEqual(check(wf("${{ inputs.r }}"), opt_in=opt_in)["admission"], "unavailable")
            self.assertEqual(
                check(wf("${{ matrix.os }}", extra=""), opt_in=opt_in)["admission"], "unavailable"
            )


class Refused(unittest.TestCase):
    def failed(self, text, **kw):
        out = check(text, **kw)
        self.assertEqual(out["admission"], "failed", out)
        self.assertTrue(out["policy_violations"])
        return out

    def unavailable(self, text, **kw):
        out = check(text, **kw)
        self.assertEqual(out["admission"], "unavailable", out)
        self.assertEqual(out["policy_violations"], [])
        return out

    def test_without_the_operators_opt_in_same_repository_origin_confers_no_trust(self):
        self.failed(wf(expr()), opt_in=False)
        self.failed(wf(expr(), on="[pull_request, push]"), opt_in=False)

    def test_pull_request_target_is_untrusted_whatever_the_opt_in(self):
        self.failed(wf(expr(), on="pull_request_target"))
        self.failed(wf(expr(), on="[pull_request, pull_request_target]"))

    def test_fork_pull_requests_only_ever_reach_the_fallback(self):
        out = check(wf(expr()), facts=True)
        self.assertEqual(out["facts"][0]["jobs"][0]["guard"]["on_false"], ["dp-no-runner"])
        # a fallback that would run a fork's code on a privileged runner is refused
        self.failed(wf(expr(b=SELF_LABELS)))
        self.failed(wf(expr(b="'org-trusted'")))

    def test_the_fallback_must_select_no_runner_or_an_admitted_one(self):
        self.assertEqual(check(wf(expr(b="'org-public'")))["admission"], "ok")
        self.assertEqual(check(wf(expr(b="'ubuntu-24.04'")))["admission"], "ok")
        self.failed(wf(expr(b="'linux'")))  # every self-hosted Linux runner carries it
        self.failed(wf(expr(b="'self-hosted'")))
        self.failed(wf(expr(b="'x64'")))
        self.failed(wf(expr(b='fromJSON(\'["dp-no-runner", "second"]\')')))  # not a lone sentinel

    def test_the_privileged_branch_must_be_a_runner_the_profile_declares(self):
        self.failed(wf(expr(a='fromJSON(\'["self-hosted", "undeclared"]\')')))
        self.failed(wf(expr(a="'undeclared'")))
        self.failed(wf(expr()), profile=None)  # no profile: no runner is declared
        group_less = json.loads(json.dumps(PROFILE))
        group_less["runners"] = group_less["runners"][:1]  # the repository was not given the trusted runner
        self.failed(wf(expr()), profile=group_less)

    def test_a_protected_environment_is_the_existing_exemption_and_nothing_more(self):
        self.assertEqual(
            check(wf(expr(), extra="    environment: org-protected\n"), opt_in=False)["admission"], "ok"
        )
        self.failed(wf(expr(), extra="    environment: other\n"), opt_in=False)

    def test_reversed_or_weakened_conditions_are_not_interpreted(self):
        for guard in (
            "github.event.pull_request.head.repo.full_name != github.repository",
            "github.event.pull_request.head.repo.fork == false",
            "github.event.pull_request.head.repo.fork != true",
            "github.event.pull_request.head.repo.full_name == github.event.repository.full_name",
            "github.repository == github.event.pull_request.head.repo.full_name",
            "github.event.pull_request.head.repo.full_name == 'example-org/app'",
            "github.event.pull_request.head.repo.full_name == github.repository_owner",
            "github.event_name == 'pull_request'",
            "true",
            "!(github.event.pull_request.head.repo.full_name != github.repository)",
        ):
            self.unavailable(wf(expr(guard=guard)))

    def test_conditions_widened_by_or_or_and_are_not_interpreted(self):
        for guard in (
            f"{GUARD} || github.actor == 'someone'",
            f"{GUARD} || true",
            f"github.actor == 'someone' || {GUARD}",
            f"({GUARD} || github.event_name == 'push')",
            f"{GUARD} && github.actor == 'someone'",
        ):
            self.unavailable(wf(expr(guard=guard)))
        self.unavailable(wf(f"${{{{ {GUARD} && {SELF_LABELS} || {SENTINEL} || {SELF_LABELS} }}}}"))

    def test_nested_computed_and_user_controlled_expressions_are_not_interpreted(self):
        inner = f"{GUARD} && {SELF_LABELS} || {SENTINEL}"
        for e in (
            f"${{{{ {GUARD} && ({GUARD} && {SELF_LABELS} || {SENTINEL}) || {SENTINEL} }}}}",
            f"${{{{ {GUARD} && {GUARD} && {SELF_LABELS} || {SENTINEL} || {SENTINEL} }}}}",
            f"${{{{ {GUARD} && {SELF_LABELS} || ({inner}) }}}}",
            expr(a='fromJSON(format(\'["self-hosted", "{0}"]\', github.head_ref))'),
            expr(a="fromJSON(github.event.pull_request.title)"),
            expr(a="fromJSON(vars.RUNNERS)"),
            expr(a="fromJSON(inputs.runners)"),
            expr(a="github.event.pull_request.head.ref"),
            expr(a="matrix.os"),
            expr(b="inputs.fallback"),
            expr(a="'${{ github.head_ref }}'"),
            expr(a='fromJSON(\'["self-hosted", "${{ github.head_ref }}"]\')'),
            expr(a="fromJSON('[\"self-hosted\", 1]')"),
            expr(a='fromJSON(\'["self-hosted", "a b"]\')'),
            expr(a="fromJSON('[]')"),
            expr(a="fromJSON('not json')"),
            expr(a='fromJSON(\'{"labels": ["x"]}\')'),
            expr(a="toJSON(github)"),
            expr(a="format('{0}', github.actor)"),
            "${{ " + GUARD + " && " + SELF_LABELS + " }}",
            "${{ " + GUARD + " ? 'a' : 'b' }}",
            "${{ " + GUARD + " && " + SELF_LABELS + " || " + SENTINEL + " }} extra",
            "extra ${{ " + GUARD + " && " + SELF_LABELS + " || " + SENTINEL + " }}",
        ):
            self.unavailable(wf(e))

    def test_a_group_mapping_is_not_guarded_syntax(self):
        self.unavailable(wf(f"{{group: {expr()}}}"))
        self.unavailable(wf("\n      group: trusted\n      labels: [x]"))

    def test_triggers_that_may_carry_a_pull_request_payload_leave_the_guard_unproved(self):
        for on in (
            "[pull_request, issue_comment]",
            "[pull_request, pull_request_review]",
            "[pull_request, repository_dispatch]",
        ):
            out = self.unavailable(wf(expr(), on=on))
            self.assertIn("not proved", out["incomplete"][0]["detail"])

    def test_nothing_is_ever_evaluated_or_executed(self):
        # a guard that would be true for everyone by GitHub's coercion rules is still just text
        self.unavailable(wf(expr(guard="github.event.pull_request.head.repo.fork == null")))
        self.unavailable(wf(expr(guard="null == null")))


class Cli(unittest.TestCase):
    def run_cli(self, *a):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        return subprocess.run(
            [sys.executable, "-m", "dev_platform", *a], capture_output=True, text=True, env=env
        )

    def test_the_opt_in_is_an_explicit_operator_flag_and_the_default_is_untrusted(self):
        root = tmpdir(self)
        cfg = self_hosted()
        profile = C.profile_for(cfg, "app")
        trusted = ["self-hosted", "linux", "x64", "build"]  # the template's trusted runner
        self.assertIn(trusted, [r["labels"] for r in profile["runners"] if r["trust"] == "trusted"])
        a = 'fromJSON(\'["self-hosted", "linux", "x64", "build"]\')'
        (root / "c.json").write_text(json.dumps(cfg))
        (root / "p.json").write_text(json.dumps(profile))
        wfs = root / "wf"
        wfs.mkdir()
        (wfs / "a.yml").write_text(wf(expr(a=a)))
        for argv, flag in (
            (
                ("infra", "validate", str(root / "c.json"), "--workflows", str(wfs), "--repo", "app"),
                "workflows",
            ),
            (("pr-check", "--workflows", str(wfs), "--infra-profile", str(root / "p.json")), None),
            (("infra", "check", str(root / "p.json"), "--workflows", str(wfs)), "pr_check"),
        ):

            def verdict(*extra):
                p = self.run_cli(*argv, *extra)
                out = json.loads(p.stdout)
                return p.returncode, (out[flag] if flag else out)["admission"]

            self.assertEqual(verdict(), (1, "failed"), argv)
            self.assertEqual(verdict("--same-repo-pr-opt-in"), (0, "ok"), argv)
            (wfs / "a.yml").write_text(wf(expr(a=a), on="pull_request_target"))
            self.assertEqual(verdict("--same-repo-pr-opt-in"), (1, "failed"), argv)
            (wfs / "a.yml").write_text(wf(expr(a=a)))


if __name__ == "__main__":
    unittest.main()
