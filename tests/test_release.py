import json
import unittest

from dev_platform import release
from dev_platform.digest import tree_digest
from dev_platform.errors import ConfigError
from tests.helpers import ROOT, tmpdir
from tests.test_toolchain import MANIFEST


def build(test, version="1.0.0", out=None, **kw):
    out = out or tmpdir(test)
    tc = out / "tc.json"
    tc.write_text(json.dumps(MANIFEST))
    return release.build(ROOT / "src", tc, out / "store", version, **kw)


class ReleaseTest(unittest.TestCase):
    def test_build_is_reproducible(self):
        a, b = build(self), build(self)
        self.assertEqual(tree_digest(a), tree_digest(b))

    def test_release_binds_toolchains_sbom_and_source(self):
        doc = release.load(build(self, source_revision="abc", source_uri="https://example/x"))
        self.assertEqual(doc["toolchains"], MANIFEST)
        self.assertEqual(doc["provenance"]["source_revision"], "abc")
        sbom = json.loads((build(self).parent / "1.0.0" / "sbom.cdx.json").read_text())
        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertIn(("tool", "1.2.3"), {(c["name"], c["version"]) for c in sbom["components"]})

    def test_releases_are_write_once(self):
        out = tmpdir(self)
        build(self, out=out)
        with self.assertRaisesRegex(ConfigError, "immutable"):
            build(self, out=out)

    def test_tampering_detected_in_source_and_sbom(self):
        d = build(self)
        (d / "src" / "dev_platform" / "cli.py").write_text("# x\n")
        with self.assertRaisesRegex(ConfigError, "source_digest"):
            release.load(d)
        d = build(self)
        (d / "sbom.cdx.json").write_text("{}")
        with self.assertRaisesRegex(ConfigError, "SBOM"):
            release.load(d)

    def test_toolchain_change_is_a_new_release_identity(self):
        out = tmpdir(self)
        a = build(self, "1.0.0", out)
        tc = out / "tc2.json"
        newer = json.loads(json.dumps(MANIFEST))
        newer["profiles"]["p"]["tools"]["tool"]["version"] = "1.2.4"  # e.g. a security-fix toolchain bump
        tc.write_text(json.dumps(newer))
        b = release.build(ROOT / "src", tc, out / "store", "1.0.1")
        self.assertNotEqual(tree_digest(a), tree_digest(b))
        self.assertTrue(a.exists())  # the old release is untouched


if __name__ == "__main__":
    unittest.main()
