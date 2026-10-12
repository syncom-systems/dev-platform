"""Regression tests for the reusable consumer workflows (v0.8.1 shipped three defects found by the first NGA pilot):

1. `gh attestation verify` got no token, so every install was refused;
2. `attest: false` still required the caller to grant id-token/attestations write (the workflow failed at startup);
3. the platform checkout and the evidence directory were inside the consumer's working tree, so its certification failed
   with "working tree has uncommitted changes".
"""

import re
import unittest

from tests.helpers import ROOT

PILOT = (ROOT / ".github" / "workflows" / "consumer-pilot.yml").read_text()
ATTEST = (ROOT / ".github" / "workflows" / "consumer-pilot-attest.yml").read_text()


def code(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


class Token(unittest.TestCase):
    def test_the_run_step_gets_the_read_only_job_token_as_gh_token(self):
        self.assertRegex(code(PILOT), r"GH_TOKEN: \$\{\{ github\.token \}\}")

    def test_the_token_is_a_step_variable_only_never_a_persisted_credential(self):
        c = code(PILOT)
        # not at workflow or job level: the variable sits under the step that runs consumer_run.py
        step = c[c.index("- name: Select, provision, execute, verify") :]
        step = step[: step.index("- name: Summary")]
        self.assertIn("GH_TOKEN", step)
        self.assertEqual(c.count("GH_TOKEN"), 1)
        # every checkout discards its credentials
        self.assertEqual(c.count("actions/checkout@"), c.count("persist-credentials: false"))
        self.assertNotIn("persist-credentials: true", c)

    def test_the_token_is_never_printed_or_written(self):
        c = code(PILOT)
        for bad in (
            "echo $GH_TOKEN",
            'echo "$GH_TOKEN"',
            "secrets.",
            'github.token }}" >',
            "set -x",
            "ACTIONS_STEP_DEBUG",
        ):
            self.assertNotIn(bad, c)
        self.assertEqual(len(re.findall(r"github\.token", c)), 1)


class Permissions(unittest.TestCase):
    def test_the_pilot_workflow_needs_no_oidc_or_write_permission(self):
        c = code(PILOT)
        self.assertNotIn(
            "write", c
        )  # also no `attest` input: nothing here is elevated, so a caller grants nothing
        self.assertNotIn("id-token", c)
        self.assertNotIn("attestations", c)
        self.assertNotIn("attest:", c)
        self.assertEqual(re.findall(r"^\s*contents: (\w+)", c, re.M), ["read"])

    def test_attestation_is_a_separate_workflow_with_the_elevated_permissions(self):
        c = code(ATTEST)
        self.assertIn("id-token: write", c)
        self.assertIn("attestations: write", c)
        self.assertNotIn("contents: write", c)
        # it attests the files the read-only job uploaded: no checkout, no code of its own
        self.assertNotIn("actions/checkout", c)
        self.assertNotIn("run:", c)
        self.assertIn("name: dp-evidence", c)


class Layout(unittest.TestCase):
    def test_consumer_platform_and_evidence_are_sibling_directories(self):
        c = code(PILOT)
        self.assertIn("path: consumer", c)
        self.assertIn("path: platform", c)
        self.assertRegex(c, r"--consumer-dir consumer\b")
        self.assertRegex(c, r"--evidence-dir evidence\b")
        self.assertRegex(c, r"--dev-platform-checkout platform\b")
        self.assertIn('--work "$RUNNER_TEMP/dp"', c)
        self.assertIn("path: evidence", c)

    def test_nothing_is_placed_inside_the_consumer_tree_and_no_exclude_is_needed(self):
        c = code(PILOT)
        self.assertNotIn(".dev-platform-src", c)
        self.assertNotIn("dp-evidence/", c)
        self.assertNotIn("info/exclude", c)
        self.assertNotIn("--consumer-dir .", c)
        for m in re.finditer(r"path: (\S+)", c):
            self.assertFalse(m.group(1).startswith("consumer/"), m.group(1))


if __name__ == "__main__":
    unittest.main()
