"""Immutable configuration releases: identity, immutability, verification, supported formats (ADR 0023)."""

import json
import os
import unittest

from dev_platform import infra_release as R
from dev_platform.digest import tree_digest
from tests.helpers import tmpdir
from tests.infra_fixtures import OWNER, VERSION, release_files


class Identity(unittest.TestCase):
    def test_release_digest_is_the_platform_tree_digest(self):
        root = tmpdir(self)
        hexd = R.build(root, VERSION, release_files())
        self.assertEqual(hexd, tree_digest(root / "releases" / VERSION))
        self.assertEqual(hexd, R.digest_of(release_files()))  # in memory, any order: the same identity

    def test_in_memory_order_does_not_matter(self):
        files = release_files()
        self.assertEqual(R.digest_of(dict(reversed(list(files.items())))), R.digest_of(files))

    def test_release_tree_digest_differs_from_any_profile_file_digest(self):
        import hashlib

        files = release_files()
        tree = R.digest_of(files)
        for rel, data in files.items():
            self.assertNotEqual(hashlib.sha256(data).hexdigest(), tree, rel)

    def test_refuses_what_tree_digest_would_skip_or_follow(self):
        for rel in ("__pycache__/x.json", "profiles/__pycache__/a.json", "a.pyc"):
            root = tmpdir(self) / "r"
            (root / rel).parent.mkdir(parents=True)
            (root / rel).write_text("{}")
            with self.assertRaises(R.ReleaseError) as cm:
                R.read_tree(root)
            self.assertEqual(cm.exception.code, "release-tampered", rel)

    def test_refuses_symlinks_and_special_files(self):
        root = tmpdir(self) / "r"
        root.mkdir()
        (root / "m.json").write_text("{}")
        os.symlink(root / "m.json", root / "link.json")
        with self.assertRaises(R.ReleaseError):
            R.read_tree(root)
        (root / "link.json").unlink()
        os.mkfifo(root / "fifo")
        with self.assertRaises(R.ReleaseError):
            R.read_tree(root)
        (root / "fifo").unlink()
        os.symlink(root, root.parent / "alias")
        with self.assertRaises(R.ReleaseError):
            R.read_tree(root.parent / "alias")

    def test_calver(self):
        for ok in ("2026.10.1", "2026.01.0", "2027.12.9999"):
            R.version_key(ok)
        for bad in ("2026.10", "2026.13.1", "2026.00.1", "2026.10.01", "1.2.3", "latest", None, 2026):
            with self.assertRaises(R.ReleaseError, msg=bad):
                R.version_key(bad)
        self.assertLess(R.version_key("2026.09.1"), R.version_key("2026.10.0"))


class Build(unittest.TestCase):
    def test_builds_and_indexes(self):
        root = tmpdir(self)
        hexd = R.build(root, VERSION, release_files())
        idx = R.load_index(root / R.INDEX)
        self.assertEqual(
            idx["releases"], [{"version": VERSION, "digest": hexd, "contract": "dev-platform.infra/v1"}]
        )
        self.assertEqual(R.verify(root), [])

    def test_releases_are_immutable_and_only_move_forward(self):
        root = tmpdir(self)
        R.build(root, "2026.02.1", release_files("2026.02.1"))
        for v, code in (("2026.02.1", "release-exists"), ("2026.01.5", "release-not-newer")):
            with self.assertRaises(R.ReleaseError) as cm:
                R.build(root, v, release_files(v))
            self.assertEqual(cm.exception.code, code)
        R.build(root, "2026.02.2", release_files("2026.02.2"))
        self.assertEqual(R.verify(root), [])

    def test_refuses_an_unindexed_directory_in_the_way(self):
        root = tmpdir(self)
        (root / "releases" / VERSION).mkdir(parents=True)
        with self.assertRaises(R.ReleaseError) as cm:
            R.build(root, VERSION, release_files())
        self.assertEqual(cm.exception.code, "release-exists")

    def test_refuses_invalid_content(self):
        files = release_files()
        bad = dict(
            files, **{"profiles/app.json": b'{"schema": "dev-platform.infra/v1", "runners": [{"id": 1}]}'}
        )
        no_profile = {k: v for k, v in files.items() if k != "profiles/tool.json"}
        wrong_version = dict(
            files, **{"manifest.json": files["manifest.json"].replace(VERSION.encode(), b"2026.01.2")}
        )
        for name, f, code in (
            ("invalid profile", bad, "profile-invalid"),
            ("missing profile", no_profile, "unsupported-format"),
            ("manifest names another version", wrong_version, "unsupported-format"),
            ("generated file", dict(files, **{"x.pyc": b""}), "release-tampered"),
        ):
            with self.assertRaises(R.ReleaseError, msg=name) as cm:
                R.build(tmpdir(self), VERSION, f)
            self.assertEqual(cm.exception.code, code, name)


class Verify(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        R.build(self.root, VERSION, release_files())
        self.base = R.load_index(self.root / R.INDEX)

    def test_modified_release_is_reported(self):
        p = self.root / "releases" / VERSION / "profiles" / "app.json"
        p.write_bytes(p.read_bytes().replace(b'"deploy"', b'"deploy-all"'))
        self.assertIn("release modified", "\n".join(R.verify(self.root)))

    def test_added_file_is_reported(self):
        (self.root / "releases" / VERSION / "extra.json").write_text("{}")
        self.assertTrue(R.verify(self.root))

    def test_unindexed_release_is_reported(self):
        (self.root / "releases" / "2026.02.1").mkdir()
        self.assertIn("not in the index", "\n".join(R.verify(self.root)))

    def test_index_may_only_grow_relative_to_the_base(self):
        R.build(self.root, "2026.02.1", release_files("2026.02.1"))
        self.assertEqual(R.verify(self.root, self.base), [])
        idx = R.load_index(self.root / R.INDEX)
        idx["releases"] = idx["releases"][1:]  # removing the base's entry (and its directory)
        (self.root / R.INDEX).write_bytes(R.index_bytes(idx))
        os.rename(self.root / "releases" / VERSION, self.root / "gone")
        self.assertIn("changed or removed", "\n".join(R.verify(self.root, self.base)))

    def test_rewritten_index_entry_is_reported(self):
        idx = R.load_index(self.root / R.INDEX)
        idx["releases"][0]["digest"] = "0" * 64
        (self.root / R.INDEX).write_bytes(R.index_bytes(idx))
        out = "\n".join(R.verify(self.root, self.base))
        self.assertIn("release modified", out)
        self.assertIn("changed or removed", out)

    def test_malformed_index_is_a_problem_not_a_crash(self):
        for doc in (
            {"schema_version": 2, "releases": []},
            {"releases": []},
            [],
            {"schema_version": 1, "releases": [{}]},
        ):
            (self.root / R.INDEX).write_text(json.dumps(doc))
            self.assertTrue(R.verify(self.root), doc)


class Formats(unittest.TestCase):
    def test_public_format_owner_is_in_the_manifest(self):
        files = release_files()
        self.assertEqual(R.manifest_of(files, VERSION, "dev-platform.infra/v1")[1], OWNER)

    def test_legacy_layout_resolves_unchanged(self):
        files = release_files(fmt="dpinfra.config-release/v1")
        self.assertNotIn(b'"owner"', files["manifest.json"])
        self.assertEqual(R.manifest_of(files, VERSION, "dev-platform.infra/v1")[1], OWNER)

    def test_unknown_format_or_contract_is_refused(self):
        for fmt in ("acme.config-release/v9", None):
            files = release_files(fmt=fmt or "x")
            if fmt is None:
                files["manifest.json"] = b"[]"
            with self.assertRaises(R.ReleaseError) as cm:
                R.manifest_of(files, VERSION, "dev-platform.infra/v1")
            self.assertEqual(cm.exception.code, "unsupported-format")
        with self.assertRaises(R.ReleaseError):
            R.manifest_of(release_files(), VERSION, "dev-platform.infra/v2")

    def test_formats_are_only_ever_added(self):
        # A newer platform must resolve every release format an older one did (immutable releases never change).
        for fmt in ("dev-platform.infra-config-release/v1", "dpinfra.config-release/v1"):
            self.assertEqual(R.FORMATS.get(fmt), "dev-platform.infra/v1", fmt)


if __name__ == "__main__":
    unittest.main()
