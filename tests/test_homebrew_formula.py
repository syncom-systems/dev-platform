"""The Homebrew formula is a deterministic function of a release identity and names nothing private."""

import importlib.util
import json
import re
import unittest

from tests.helpers import ROOT, tmpdir

spec = importlib.util.spec_from_file_location("homebrew_formula", ROOT / "tools" / "homebrew_formula.py")
H = importlib.util.module_from_spec(spec)
spec.loader.exec_module(H)

IDENTITY = {"version": "0.9.0", "archive": "dev-platform-0.9.0.tar.gz", "archive_sha256": "a" * 64,
            "tree_digest_pin": "b" * 64, "source_revision": "c" * 40}  # fmt: skip


class Render(unittest.TestCase):
    def identity(self, **over):
        f = tmpdir(self) / "identity.json"
        f.write_text(json.dumps({**IDENTITY, **over}))
        return f

    def test_values_come_from_the_identity_and_rendering_is_deterministic(self):
        text = H.from_identity(self.identity())
        self.assertEqual(text, H.from_identity(self.identity()))
        self.assertIn('url "https://github.com/syncom-systems/dev-platform/releases/download/v0.9.0/'
                      'dev-platform-0.9.0.tar.gz"', text)  # fmt: skip
        self.assertIn(f'sha256 "{"a" * 64}"', text)
        self.assertIn(f'assert_equal "{"b" * 64}"', text)  # the installed tree must equal the release's pin
        self.assertIn("c" * 40, text)
        self.assertIn('depends_on "gh"', text)

    def test_the_formula_names_only_the_public_platform(self):
        text = H.from_identity(self.identity())
        hosts = set(re.findall(r"https://([^/\s\"]+/[^/\s\"]+/[^/\s\"]+)", text))
        self.assertEqual(hosts, {"github.com/syncom-systems/dev-platform"})
        for word in ("infra", "token", "secret", "runner", "internal"):
            self.assertNotIn(word, text.lower())

    def test_malformed_identities_are_refused(self):
        for over in ({"archive_sha256": "x"}, {"tree_digest_pin": "B" * 64}, {"version": "latest"},
                     {"source_revision": "main"}, {"archive": "other.tar.gz"}):  # fmt: skip
            with self.assertRaises(H.Invalid, msg=over):
                H.from_identity(self.identity(**over))

    def test_only_the_release_asset_or_a_local_test_archive(self):
        ok = H.render("9.0.0", "a" * 64, "b" * 64, url="file:///tmp/x/dev-platform-9.0.0.tar.gz")
        self.assertIn('url "file:///tmp/x/dev-platform-9.0.0.tar.gz"', ok)
        for url in ("http://example/dev-platform-9.0.0.tar.gz", "https://example/dev-platform-9.0.1.tar.gz"):
            with self.assertRaises(H.Invalid, msg=url):
                H.render("9.0.0", "a" * 64, "b" * 64, url=url)

    def test_check_mode(self):
        ident = self.identity()
        out = tmpdir(self) / "dev-platform.rb"
        self.assertEqual(H.main(["--identity", str(ident), "--out", str(out)]), 0)
        self.assertEqual(H.main(["--identity", str(ident), "--check", str(out)]), 0)
        out.write_text(out.read_text().replace("a" * 64, "0" * 64))
        self.assertEqual(H.main(["--identity", str(ident), "--check", str(out)]), 1)
        self.assertEqual(H.main(["--identity", str(ident), "--version", "1.0.0"]), 2)

    def test_retained_formulas_equal_the_rendering_of_their_release_identity(self):
        for rb in sorted(ROOT.glob("releases/*/homebrew/dev-platform.rb")):
            ident = rb.parent.parent / "identity.json"
            self.assertEqual(rb.read_text(), H.from_identity(ident), rb)
