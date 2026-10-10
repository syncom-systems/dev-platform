import json
import os
import shutil
import tarfile
import unittest

from dev_platform import pack, release
from dev_platform.digest import tree_digest
from dev_platform.errors import ConfigError
from tests.helpers import ROOT, tmpdir
from tests.test_toolchain import MANIFEST


def rmtree_rw(path):
    for dirpath, _d, _f in os.walk(path):
        os.chmod(dirpath, 0o700)
    shutil.rmtree(path, ignore_errors=True)


def make_release(test, version="1.0.0"):
    out = tmpdir(test)
    test.addCleanup(rmtree_rw, out)
    tc = out / "tc.json"
    tc.write_text(json.dumps(MANIFEST))
    d = release.build(ROOT / "src", tc, out / "rel", version, strict_version=False)
    arc = out / f"dev-platform-{version}.tar.gz"
    sha = pack.pack(d, arc)
    return d, arc, sha


class PackTest(unittest.TestCase):
    def test_pack_is_deterministic(self):
        d, arc, sha = make_release(self)
        again = arc.parent / "again.tar.gz"
        self.assertEqual(pack.pack(d, again), sha)
        self.assertEqual(arc.read_bytes(), again.read_bytes())

    def test_install_roundtrip_preserves_pin_digest(self):
        d, arc, sha = make_release(self)
        store = tmpdir(self)
        self.addCleanup(rmtree_rw, store)
        dest = pack.install(arc, store, expect_archive_sha256=sha, expect_tree_sha256=tree_digest(d))
        self.assertEqual(tree_digest(dest), tree_digest(d))
        self.assertEqual(os.stat(dest / "release.json").st_mode & 0o222, 0)  # read-only
        self.assertEqual([p.name for p in store.iterdir()], ["1.0.0"])  # no staging leftovers

    def test_install_is_idempotent_and_write_once(self):
        _d, arc, sha = make_release(self)
        store = tmpdir(self)
        self.addCleanup(rmtree_rw, store)
        pack.install(arc, store, expect_archive_sha256=sha)
        pack.install(arc, store, expect_archive_sha256=sha)  # same bytes: ok
        # a different release under the same version number must be refused
        out = tmpdir(self)
        self.addCleanup(rmtree_rw, out)
        tc = out / "tc.json"
        tc.write_text(json.dumps(MANIFEST))
        other = release.build(ROOT / "src", tc, out / "rel2", "1.0.0", strict_version=False)
        (other / "src" / "dev_platform" / "extra.txt").write_text("x")
        doc = json.loads((other / "release.json").read_text())
        doc["platform"]["source_digest"] = tree_digest(other / "src")
        (other / "release.json").write_text(json.dumps(doc))
        arc3 = out / "o.tar.gz"
        sha3 = pack.pack(other, arc3)
        with self.assertRaisesRegex(ConfigError, "write-once"):
            pack.install(arc3, store, expect_archive_sha256=sha3)

    def test_wrong_digests_rejected_before_anything_is_installed(self):
        _d, arc, sha = make_release(self)
        store = tmpdir(self)
        with self.assertRaisesRegex(ConfigError, "archive sha256"):
            pack.install(arc, store, expect_archive_sha256="0" * 64)
        with self.assertRaisesRegex(ConfigError, "tree digest"):
            pack.install(arc, store, expect_archive_sha256=sha, expect_tree_sha256="0" * 64)
        self.assertEqual(list(store.iterdir()), [])

    def test_hostile_archives_are_rejected(self):
        import io

        def archive(members):
            p = tmpdir(self) / "evil.tar.gz"
            with tarfile.open(p, "w:gz") as t:
                for name, kind, data in members:
                    ti = tarfile.TarInfo(name)
                    if kind == "sym":
                        ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
                    ti.size = len(data) if kind == "file" else 0
                    t.addfile(ti, io.BytesIO(data) if kind == "file" else None)
            return p

        cases = {
            "traversal": [("1.0.0/../../x", "file", b"x")],
            "absolute": [("/etc/x", "file", b"x")],
            "symlink": [("1.0.0/l", "sym", b"")],
            "two roots": [("1.0.0/a", "file", b"x"), ("2.0.0/b", "file", b"x")],
            "non-version root": [("evil/a", "file", b"x")],
        }
        for name, members in cases.items():
            p = archive(members)
            with self.assertRaises(ConfigError, msg=name):
                pack.safe_extract(p, tmpdir(self))

    def test_installed_release_is_usable_as_a_pin(self):
        from dev_platform import resolve as R
        from dev_platform.config import PlatformPin

        _d, arc, sha = make_release(self)
        store = tmpdir(self)
        self.addCleanup(rmtree_rw, store)
        dest = pack.install(arc, store, expect_archive_sha256=sha)
        res = R.resolve(
            type("C", (), {"platform": PlatformPin("1.0.0", tree_digest(dest), False, "p")})(),
            env={R.STORE_ENV: str(store)},
        )
        self.addCleanup(res.dispose)
        self.assertEqual(res.mode, "pinned")

    def test_build_binds_source_version(self):
        out = tmpdir(self)
        tc = out / "tc.json"
        tc.write_text(json.dumps(MANIFEST))
        with self.assertRaisesRegex(ConfigError, "__version__"):
            release.build(ROOT / "src", tc, out / "r", "9.9.9")


if __name__ == "__main__":
    unittest.main()
