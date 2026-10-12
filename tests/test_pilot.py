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
        for bad in ("git push", '"push"', "install_release.py --authorization"):
            self.assertNotIn(bad, src)
        # The only authorization a pilot ever offers is a forged one, to the application verifier, to see it refused;
        # it never reaches the platform verifier (acceptance).
        self.assertEqual(src.count("--authorization"), 1)
        self.assertIn("forged on purpose", src)

    def test_pilot_installs_only_via_the_trusted_installer_with_pins(self):
        src = (ROOT / "tools" / "pilot.py").read_text()
        for needle in ("--verifier-sha256", "--policy-sha256", "--archive-sha256", "--tree-sha256"):
            self.assertIn(needle, src)

    def test_app_release_step_is_unapproved_even_with_a_forged_approval(self):
        import importlib.util
        import os
        import subprocess

        from tests.helpers import tmpdir
        from tests.test_provenance import result

        spec = importlib.util.spec_from_file_location("pilot_tool", ROOT / "tools" / "pilot.py")
        P = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(P)
        d = tmpdir(self)
        cd = d / "consumer"
        cd.mkdir()
        (cd / "Cargo.lock").write_text("lock\n")
        for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "c"]):
            subprocess.run(
                ["git", "-c", "user.name=p", "-c", "user.email=p@x.invalid", *cmd],
                cwd=cd,
                check=True,
                capture_output=True,
            )
        rev = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cd, capture_output=True, text=True
        ).stdout.strip()
        res = d / "result.json"
        res.write_text(json.dumps(result(rev=rev)))
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        c = {"id": "demo", "repo": "example/demo"}
        out = P.app_release_step(c, cd, d, res, env, "0.1.0", "1" * 64)
        self.assertEqual(out["app_release"], "assembled", out)
        # current-state decision: `unapproved` when the evidence repository is readable, `failed` when it is not
        # (no network here); never `approved`, also when a forged approval is offered
        self.assertIn(out["app_release_state"], ("unapproved", "failed", "indeterminate"))
        self.assertIn(out["app_release_forged_state"], ("unapproved", "failed", "indeterminate"))
        res.write_text(json.dumps(result(rev=rev, certification={"certified": False, "blockers": ["x"]})))
        self.assertEqual(P.app_release_step(c, cd, d, res, env, "0.1.0", "1" * 64)["app_release"], "refused")


if __name__ == "__main__":
    unittest.main()
