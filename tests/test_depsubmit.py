import json
import unittest

from dev_platform import depsubmit
from tests.helpers import ROOT

M = json.loads((ROOT / "toolchains" / "manifest.json").read_text())


class Snapshot(unittest.TestCase):
    def snap(self, **kw):
        return depsubmit.snapshot(M, platform_version="0.3.0", sha="a" * 40, ref="refs/heads/main",
                                  scanned="2026-10-12T00:00:00Z", job_id="1", **kw)  # fmt: skip

    def test_shape_matches_the_submission_api(self):
        s = self.snap()
        self.assertEqual(s["version"], 0)
        self.assertEqual(set(s) >= {"sha", "ref", "job", "detector", "scanned", "manifests"}, True)
        res = s["manifests"]["dev-platform-toolchain"]["resolved"]
        self.assertIn("pkg:pypi/ruff@0.17.0", res)
        for purl, d in res.items():
            self.assertEqual(d["package_url"], purl)
            self.assertIn("@", purl)

    def test_only_supported_ecosystems_are_marked_alert_capable(self):
        comps = depsubmit.components(M)
        self.assertTrue(comps["pkg:pypi/ruff@0.17.0"]["alert_capable"])
        self.assertFalse(comps["pkg:generic/cpython@3.14.7"]["alert_capable"])
        self.assertFalse(comps["pkg:github/bazelbuild/bazel@8.4.2"]["alert_capable"])
        # PyPI packages: uv, ruff 0.17.0 and 0.17.2 (Bazel baseline), pytest, pytest-cov, coverage, ty
        self.assertEqual(self.snap()["metadata"]["alert_capable_components"], 7)

    def test_profile_filter_and_unversioned_purls(self):
        s = self.snap(profiles=["rust-cargo"])
        self.assertNotIn("pkg:pypi/ruff@0.17.0", s["manifests"]["dev-platform-toolchain"]["resolved"])
        m = {"profiles": {"p": {"tools": {"t": {"version": "1", "purl": "pkg:pypi/t"}}}}}
        self.assertEqual(depsubmit.components(m), {})


if __name__ == "__main__":
    unittest.main()
