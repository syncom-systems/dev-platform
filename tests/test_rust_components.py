"""`rust-components` sources: individually pinned official Rust component archives, assembled on the host."""

import io
import json
import tarfile
import unittest
from unittest import mock

from dev_platform import provision as P
from dev_platform import release as R
from dev_platform import toolchain as T
from dev_platform.errors import ConfigError
from tests.helpers import ROOT, tmpdir

SHA = "a" * 64


def component_archive(top: str, parts: dict[str, dict[str, bytes]]) -> bytes:
    """An official-style dist tarball: <top>/<component>/manifest.in plus the files it lists."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:

        def add(name: str, data: bytes) -> None:
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))

        for comp, files in parts.items():
            add(f"{comp}/manifest.in", "".join(f"file:{rel}\n" for rel in sorted(files)).encode())
            for rel, data in files.items():
                add(f"{comp}/{rel}", data)
    return buf.getvalue()


def source(**over):
    comp = {"archive": "rustc-1.0.0-k.tar.xz", "url": "https://example.invalid/rustc.tar.xz", "sha256": SHA}
    base = {
        "type": "rust-components",
        "components": [
            {**comp, "install": ["rustc"]},
            {**comp, "archive": "cargo-1.0.0-k.tar.xz", "bazel_only": True},
        ],
    }
    return {**base, **over}


def manifest(src):
    return {
        "schema": T.SCHEMA,
        "profiles": {
            "p": {
                "tools": {
                    "rust-dev": {
                        "version": "1.0.0",
                        "executable": "rustc",
                        "probe": {"argv": ["rustc", "--version"], "pattern": r"rustc (\S+)"},
                        "source": {"k": src},
                    }
                }
            }
        },
    }


class Validation(unittest.TestCase):
    def test_a_well_formed_source_is_accepted(self):
        T.validate(manifest(source()))

    def test_bad_sources_are_refused(self):
        good = source()["components"][0]
        for bad, why in (
            (source(components=[]), "non-empty list"),
            (source(components=[{**good, "url": "http://x/y.tar.xz"}]), "https"),
            (source(components=[{**good, "sha256": "zz"}]), "64 hex"),
            (source(components=[{**good, "archive": "../x.tar.xz"}]), "bare .tar.xz"),
            (source(components=[{**good, "install": []}]), "install"),
            (source(components=[good, good]), "listed twice"),
        ):
            with self.subTest(why), self.assertRaises(ConfigError) as e:
                T.validate(manifest(bad))
            self.assertIn(why, "\n".join(e.exception.problems))


class Install(unittest.TestCase):
    def test_host_components_are_installed_and_bazel_only_ones_are_not_fetched(self):
        fetched = []
        data = component_archive("rustc-1.0.0-k", {"rustc": {"bin/rustc": b"#!/bin/sh\n"}})

        def fake_fetch(url, sha256, dest):
            fetched.append(dest.name)
            dest.write_bytes(data)

        dev = tmpdir(self)
        (dev / "dl").mkdir()
        with mock.patch.object(P, "fetch", fake_fetch):
            P.install_rust_components(source(), dev / "prefix", dev / "dl")
        self.assertEqual(fetched, ["rustc-1.0.0-k.tar.xz"])
        self.assertTrue((dev / "prefix" / "bin" / "rustc").is_file())

    def test_provision_selects_the_components_installer(self):
        data = component_archive("rustc-1.0.0-k", {"rustc": {"bin/rustc": b"#!/bin/sh\n"}})
        dev = tmpdir(self)
        with mock.patch.object(P, "fetch", lambda url, sha, dest: dest.write_bytes(data)):
            done = P.provision(manifest(source()), "p", dev, key="k")
        self.assertEqual(done, ["rust-dev"])
        self.assertTrue((dev / "rust-dev" / "bin" / "rustc").exists())

    def test_a_component_whose_hash_differs_is_refused_by_the_real_fetch(self):
        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        dev = tmpdir(self)
        with (
            mock.patch.object(P.urllib.request, "urlopen", lambda *a, **k: Resp(b"other bytes")),
            self.assertRaises(ConfigError) as e,
        ):
            P.provision(manifest(source()), "p", dev, key="k")
        self.assertIn("hash mismatch", str(e.exception.problems))
        self.assertFalse((dev / "dl" / "rustc-1.0.0-k.tar.xz").exists())

    def test_into_cannot_leave_the_version_directory(self):
        for into in ("../bin", "/abs", "a/../../b"):
            src = {"url": "https://x/t.tar.gz", "sha256": SHA, "into": into}
            m = {
                "schema": T.SCHEMA,
                "profiles": {
                    "p": {
                        "tools": {
                            "t": {
                                "version": "1",
                                "probe": {"argv": ["t"], "pattern": "(1)"},
                                "source": {"k": src},
                            }
                        }
                    }
                },
            }
            with self.subTest(into), self.assertRaises(ConfigError):
                T.validate(m)
            tools = {"t": {"version": "1", "source": {"k": src}}}
            with (
                self.subTest(f"provision {into}"),
                mock.patch.object(P, "fetch", lambda u, s, d: d.write_bytes(b"")),
                self.assertRaises(ConfigError),
            ):
                P.provision({"profiles": {"p": {"tools": tools}}}, "p", tmpdir(self), key="k")

    def test_archive_extraction_honours_into(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("tool-k/tool")
            info.size = 3
            tar.addfile(info, io.BytesIO(b"bin"))
        m = {
            "profiles": {
                "p": {
                    "tools": {
                        "tool": {
                            "version": "1",
                            "source": {
                                "k": {
                                    "url": "https://x/t.tar.gz",
                                    "sha256": SHA,
                                    "strip": "tool-k",
                                    "into": "bin",
                                }
                            },
                        }
                    }
                }
            }
        }
        dev = tmpdir(self)
        with mock.patch.object(P, "fetch", lambda url, sha, dest: dest.write_bytes(buf.getvalue())):
            P.provision(m, "p", dev, key="k")
        self.assertEqual((dev / "tool" / "bin" / "tool").read_bytes(), b"bin")


class Sbom(unittest.TestCase):
    def test_the_real_manifest_still_yields_an_sbom_the_verifier_accepts(self):
        """`rust-dist` sources also have a `components` key (a list of names): only the source kind selects."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_release", ROOT / "tools" / "verify_release.py")
        V = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(V)
        tc = T.validate(json.loads((ROOT / "toolchains" / "manifest.json").read_text()))
        sbom = R.make_sbom("1.0.0", "c" * 64, tc)
        self.assertEqual(V.sbom_matches_manifest(sbom, tc), [])

    def test_every_component_archive_is_a_pinned_distribution_the_verifier_recomputes(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("verify_release", ROOT / "tools" / "verify_release.py")
        V = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(V)
        tc = manifest(source())
        sbom = R.make_sbom("1.0.0", "c" * 64, tc)
        refs = sbom["components"][0]["externalReferences"]
        self.assertEqual([r["comment"] for r in refs], ["k/cargo-1.0.0-k.tar.xz", "k/rustc-1.0.0-k.tar.xz"])
        self.assertEqual(V.sbom_matches_manifest(sbom, tc), [])
        sbom["components"][0]["externalReferences"][0]["hashes"][0]["content"] = "e" * 64
        self.assertTrue(V.sbom_matches_manifest(sbom, tc))


if __name__ == "__main__":
    unittest.main()
