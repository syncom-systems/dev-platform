"""Conformance kit for dev-platform.infra/v1 (contracts/infra/v1): what a private provider must satisfy."""

import json
import unittest

from dev_platform.config import RunnerSpec
from dev_platform.errors import ConfigError
from dev_platform.runners import load_profile, route, validate_profile
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
        on_disk = {p.name for p in KIT.glob("*.json")} - {"cases.json"}
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
                    ),
                    offered,
                    c["event"],
                )
                self.assertEqual((r.ok, r.runner_id), (c["ok"], c["runner"]))

    def test_schema_ids_use_the_real_org(self):
        for p in (ROOT / "schemas").glob("*.json"):
            self.assertIn("syncom-systems/dev-platform", json.loads(p.read_text())["$id"], p.name)


if __name__ == "__main__":
    unittest.main()
