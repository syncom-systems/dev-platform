import unittest

from dev_platform import advisories, planning, records
from dev_platform.errors import ConfigError
from tests.helpers import ROOT

POLICY = planning.load_policy(ROOT / "planning" / "release-policy.json")


def rel(ruff="0.17.0", pre=False):
    return {"sbom_doc": {"components": [{"name": "ruff", "version": ruff}]}, "prerelease": pre}


def adv(**over):
    d = {
        "schema": "dev-platform.advisory/v1",
        "id": "ADV-1",
        "summary": "s",
        "severity": "high",
        "affected": [{"component": "ruff", "ranges": [">=0.17.0,<0.17.2"]}],
    }
    d.update(over)
    return d


class Ranges(unittest.TestCase):
    def test_range_semantics(self):
        r = records.in_range
        self.assertTrue(r("0.17.0", ">=0.17.0,<0.17.2"))
        self.assertTrue(r("0.17.1", ">=0.17.0,<0.17.2"))
        self.assertFalse(r("0.17.2", ">=0.17.0,<0.17.2"))
        self.assertFalse(r("0.16.9", ">=0.17.0"))
        self.assertTrue(r("3.14", "==3.14.0"))
        self.assertTrue(r("weird", "<1.0"))  # unparsable: fail closed
        self.assertTrue(r("3.14.7+20260807", ">=3.14.0,<3.15"))

    def test_validation(self):
        self.assertEqual(records.validate_advisory(adv()), [])
        self.assertTrue(records.validate_advisory(adv(severity="meh")))
        self.assertTrue(records.validate_advisory(adv(affected=[{"component": "x"}])))
        self.assertTrue(records.validate_advisory(adv(affected=[{"component": "x", "ranges": ["~1.0"]}])))
        self.assertEqual(records.validate_advisory(adv(affected=[{"component": "x", "versions": ["1"]}])), [])

    def test_releases_affected_uses_ranges_and_versions(self):
        rels = {"0.1.0": rel("0.17.1"), "0.1.2": rel("0.17.2")}
        self.assertEqual(records.releases_affected(adv(), rels), {"0.1.0": ["ruff@0.17.1"]})


class Impact(unittest.TestCase):
    def run_impact(self, releases, advisory=None, pins=None):
        return advisories.impact(advisory or adv(), releases, pins or {}, POLICY)

    def test_upgrade_when_a_later_release_is_unaffected(self):
        out = self.run_impact(
            {"0.1.0": rel("0.17.0"), "0.2.0": rel("0.17.2")}, pins={"c": "0.1.0", "d": "0.2.0"}
        )
        e = out["releases"][0]
        self.assertEqual((e["version"], e["action"], e["to"]), ("0.1.0", "upgrade", "0.2.0"))
        self.assertEqual(out["consumers"], {"c": "0.1.0"})
        self.assertEqual(out["patch_proposals"], [])

    def test_patch_on_the_supported_line_when_nothing_fixed(self):
        out = self.run_impact({"0.1.0": rel("0.17.0"), "0.1.2": rel("0.17.0")})
        proposals = {p["version"]: p for p in out["patch_proposals"]}
        self.assertEqual(list(proposals), ["0.1.3"])
        e = {x["version"]: x for x in out["releases"]}
        self.assertEqual(e["0.1.2"]["action"], "patch-release")
        self.assertEqual(e["0.1.2"]["change_kinds"], ["security-fix", "toolchain-patch"])
        self.assertEqual(out["supported_lines"], ["0.1"])

    def test_old_line_is_upgrade_only(self):
        out = self.run_impact({"0.1.2": rel("0.17.0"), "0.2.0": rel("0.17.0")})
        e = {x["version"]: x for x in out["releases"]}
        self.assertEqual(e["0.1.2"]["action"], "no-patch-upgrade")
        self.assertEqual(e["0.2.0"]["action"], "patch-release")
        self.assertEqual(e["0.2.0"]["patch_version"], "0.2.1")

    def test_prereleases_and_unaffected(self):
        out = self.run_impact({"0.1.2": rel("0.17.2"), "0.2.0-rc.1": rel("0.17.0", pre=True)})
        self.assertEqual(out["releases"][0]["action"], "ignore-prerelease")
        self.assertEqual(out["unaffected_releases"], ["0.1.2"])

    def test_platform_itself(self):
        a = adv(affected=[{"component": "dev-platform", "versions": ["0.1.2"]}])
        out = self.run_impact({"0.1.2": rel()}, advisory=a)
        self.assertEqual(out["releases"][0]["change_kinds"], ["security-fix"])

    def test_invalid_advisory_is_refused(self):
        with self.assertRaises(ConfigError):
            self.run_impact({}, advisory=adv(severity="x"))

    def test_output_is_descriptive_only(self):
        out = self.run_impact({"0.1.2": rel()})
        self.assertIn("approves anything", out["note"])


if __name__ == "__main__":
    unittest.main()
