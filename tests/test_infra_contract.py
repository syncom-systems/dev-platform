"""Conformance kit for dev-platform.infra/v1 (contracts/infra/v1): what a private provider must satisfy."""

import json
import unittest

from dev_platform.config import RunnerSpec
from dev_platform.errors import ConfigError
from dev_platform.runners import event_trust, load_profile, route, validate_profile
from tests.helpers import ROOT

KIT = ROOT / "contracts" / "infra" / "v1"
CASES = json.loads((KIT / "cases.json").read_text())


class InfraContract(unittest.TestCase):
    def test_profiles(self):
        for c in CASES["profiles"]:
            with self.subTest(c["file"]):
                errs = validate_profile(json.loads((KIT / c["file"]).read_text()))
                if c["valid"]:
                    self.assertEqual(errs, [])
                    load_profile(KIT / c["file"])
                else:
                    self.assertTrue(any(c["error"] in e for e in errs), errs)
                    with self.assertRaises(ConfigError):
                        load_profile(KIT / c["file"])

    def test_every_kit_file_is_covered(self):
        listed = {c["file"] for c in CASES["profiles"]}
        on_disk = {p.name for p in KIT.glob("*.json")} - {"cases.json", "resolution-cases.json"}
        self.assertEqual(listed, on_disk)

    def test_routing_fails_closed(self):
        for i, c in enumerate(CASES["routing"]):
            with self.subTest(i):
                offered = load_profile(KIT / c["profile"])
                spec = c["spec"]
                r = route(
                    RunnerSpec(
                        "r",
                        os=spec.get("os", "any"),
                        credentials=tuple(spec.get("credentials", ())),
                        fallback=spec.get("fallback", "hosted"),
                        arch=spec.get("arch", "any"),
                        capabilities=tuple(spec.get("capabilities", ())),
                        cache=spec.get("cache", "any"),
                    ),
                    offered,
                    c["event"],
                )
                self.assertEqual((r.ok, r.runner_id), (c["ok"], c["runner"]))

    def test_denial_names_every_offered_runner_and_why(self):
        offered = load_profile(KIT / "valid-capabilities.json")
        r = route(RunnerSpec("r", capabilities=("gpu",), fallback="none"), offered, "trusted")
        self.assertFalse(r.ok)
        self.assertIn("qemu-box: capability: runner lacks ['gpu']", r.reason)
        self.assertIn("public-box: capability", r.reason)
        r = route(RunnerSpec("r", cache="read-write", fallback="none"), offered, "untrusted")
        self.assertIn("public-box: cache: needs read-write, runner offers read-only", r.reason)
        self.assertIn("qemu-box: trust: not offered to untrusted events", r.reason)

    def test_event_trust_derivation_is_normative(self):
        for c in CASES["event_trust"]:
            with self.subTest(c):
                self.assertEqual(event_trust(c["event"], **c["context"]), c["trust"])

    def test_pr_check_admission(self):
        from dev_platform import prcheck

        for c in CASES["pr_check"]:
            with self.subTest(c["workflow"]):
                profile = json.loads((KIT / c["profile"]).read_text())
                r = prcheck.check({"w.yml": c["workflow"]}, profile)
                self.assertEqual(r["admission"], c["admission"])

    def test_schema_ids_use_the_real_org(self):
        for p in (ROOT / "schemas").glob("*.json"):
            self.assertIn("syncom-systems/dev-platform", json.loads(p.read_text())["$id"], p.name)


if __name__ == "__main__":
    unittest.main()


class InfraCli(unittest.TestCase):
    def run_cli(self, *argv):
        import contextlib
        import io

        from dev_platform import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["infra", *argv])
        return code, json.loads(out.getvalue())

    def test_check_valid_and_invalid_profiles(self):
        code, out = self.run_cli("check", str(KIT / "valid-trusted-credentials.json"))
        self.assertEqual((code, out["valid"]), (0, True))
        code, out = self.run_cli("check", str(KIT / "invalid-duplicate-id.json"))
        self.assertEqual((code, out["valid"]), (1, False))

    def test_persistent_runners_warn_for_public_repositories(self):
        import tempfile
        from pathlib import Path

        prof = {
            "schema": "dev-platform.infra/v1",
            "runners": [
                {
                    "id": "p",
                    "labels": ["x"],
                    "os": "linux",
                    "arch": "x86_64",
                    "isolation": "persistent",
                    "trust": "trusted",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "p.json"
            f.write_text(json.dumps(prof))
            _, out = self.run_cli("check", str(f), "--repo-visibility", "public")
            self.assertEqual(len(out["warnings"]), 1)
            _, out = self.run_cli("check", str(f), "--repo-visibility", "private")
            self.assertEqual(out["warnings"], [])

    def test_workflows_are_checked_against_the_profile(self):
        code, out = self.run_cli(
            "check", str(KIT / "valid-admission.json"), "--workflows", str(ROOT / ".github" / "workflows")
        )
        self.assertEqual((code, out["pr_check"]["admission"]), (0, "ok"))

    def test_event_trust_cli(self):
        import contextlib
        import io

        from dev_platform import cli

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["infra", "event-trust", "--event", "pull_request_target", "--protected-ref"])
        self.assertEqual(json.loads(out.getvalue())["event_trust"], "untrusted")
