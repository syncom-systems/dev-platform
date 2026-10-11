import json
import unittest

from tests.helpers import ROOT


class Pilot(unittest.TestCase):
    def test_plan_matches_the_workflow_and_release_records(self):
        plan = json.loads((ROOT / "pilot" / "consumers.json").read_text())
        wf = (ROOT / ".github" / "workflows" / "pilot.yml").read_text()
        ident = json.loads((ROOT / "releases" / plan["release"]["version"] / "identity.json").read_text())
        self.assertTrue(ident["archive_sha256"] and ident["verifier_pins"])
        for c in plan["consumers"]:
            self.assertRegex(c["commit"], r"^[0-9a-f]{40}$")
            self.assertIn(c["commit"], wf)  # one pinned commit, stated in both places
            self.assertIn(c["repo"], wf)
            self.assertIn(c["profile"], wf)

    def test_pilot_is_read_only_and_cannot_accept(self):
        wf = (ROOT / ".github" / "workflows" / "pilot.yml").read_text()
        self.assertIn("contents: read", wf)
        self.assertNotIn("write", wf.replace("persist-credentials", ""))
        self.assertNotIn("gh release", wf)
        src = (ROOT / "tools" / "pilot.py").read_text()
        for bad in ("git push", '"push"', "--authorization"):
            self.assertNotIn(bad, src)

    def test_pilot_installs_only_via_the_trusted_installer_with_pins(self):
        src = (ROOT / "tools" / "pilot.py").read_text()
        for needle in ("--verifier-sha256", "--policy-sha256", "--archive-sha256", "--tree-sha256"):
            self.assertIn(needle, src)


if __name__ == "__main__":
    unittest.main()
