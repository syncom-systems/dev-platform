"""Bazel must compile with the declared Rust toolchain, not a host rustc (issue #111).

Bazel is faked at the process boundary; the proof logic under test is the real one. The real run is part of the
qualification (tools/qualify.py) on both platforms.
"""

import json
import unittest
from pathlib import Path

from dev_platform import bazel_rust
from tests.helpers import tmpdir

REL = "bazel-out/k8-fastbuild/bin/external/rules_rust++rust+rust_linux__stable_tools/rust_toolchain/bin/rustc"


def aquery(*rustc):
    return json.dumps(
        {
            "actions": [
                {"mnemonic": "Rustc", "arguments": ["process_wrapper", "--", p, "--edition=2024"]}
                for p in rustc
            ]
        }
    )


class Fake:
    def __init__(self, ob, *, paths=(REL,), version="1.97.1", build_code=0, decoy_hit=False, install=True):
        self.ob, self.paths, self.version, self.build_code = ob, paths, version, build_code
        self.decoy_hit, self.calls = decoy_hit, []
        if install:
            for p in paths:
                f = ob / p if not p.startswith("/") else Path("/nonexistent")
                if p.startswith("/"):
                    continue
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text("rustc")

    def __call__(self, argv, env, cwd):
        self.calls.append(argv)
        if argv[0].endswith("rustc") and "--version" in argv:
            return 0, f"rustc {self.version} (abc 2026-01-01)\n", ""
        verb = argv[1]
        if verb == "build":
            if self.decoy_hit:
                flag = next(a for a in argv if a.startswith("--action_env=PATH="))
                decoy = Path(flag.split("=", 2)[2].split(":")[0])
                (decoy.parent / "decoy.log").write_text(f"{decoy}/rustc -vV\n")
            return self.build_code, "", "boom" if self.build_code else ""
        if verb == "aquery":
            return 0, aquery(*self.paths), ""
        if verb == "info":
            assert argv[2] == "execution_root"
            return 0, f"{self.ob}\n", ""
        raise AssertionError(argv)


class Proof(unittest.TestCase):
    def setUp(self):
        self.root = tmpdir(self)
        self.ob = tmpdir(self)
        (self.root / "MODULE.bazel").write_text(
            'module(name = "x")\nrust.toolchain(edition = "2024", versions = ["1.97.1"])\n'
        )

    def prove(self, **kw):
        fake = Fake(self.ob, **kw)
        return bazel_rust.prove(self.root, run=fake, base_env={"PATH": "/usr/bin:/bin"}), fake

    def test_declared_version_from_bazel_toolchain_in_output_base_and_no_host_tool_used(self):
        p, _ = self.prove()
        self.assertTrue(p["ok"], p["problems"])
        self.assertEqual(p["observed"], ["1.97.1"])
        self.assertTrue(p["rustc"][0]["bazel_external_repo"])
        self.assertEqual(len(p["rustc"][0]["sha256"]), 64)
        self.assertFalse(p["host_decoy"]["invoked"])

    def test_never_runs_cargo(self):
        _, fake = self.prove()
        for argv in fake.calls:
            self.assertNotIn("cargo", Path(argv[0]).name)
            self.assertNotIn("cargo", " ".join(argv[1:2]))

    def test_the_build_is_forced_to_re_execute_with_decoys_first(self):
        _, fake = self.prove()
        build = next(a for a in fake.calls if a[1] == "build")
        self.assertTrue(any(a.startswith("--action_env=DP_PROOF_NONCE=") for a in build))
        self.assertTrue(any(a.startswith("--action_env=PATH=") for a in build))
        self.assertIn("--lockfile_mode=error", build)

    def test_host_rustc_path_fails(self):
        p, _ = self.prove(paths=("/usr/local/bin/rustc",), install=False)
        self.assertFalse(p["ok"])
        self.assertTrue(any("not provided through a Bazel external repository" in x for x in p["problems"]))

    def test_rustc_resolving_to_a_host_location_fails(self):
        host = self.ob / "usr" / "bin" / "rustc"
        host.parent.mkdir(parents=True)
        host.write_text("rustc")
        link = self.ob / REL
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to("/usr/bin/env")  # resolves under /usr/: a host location
        p, _ = self.prove(install=False)
        self.assertFalse(p["ok"])
        self.assertTrue(any("host location" in x for x in p["problems"]))

    def test_version_mismatch_fails(self):
        p, _ = self.prove(version="1.96.0")
        self.assertFalse(p["ok"])
        self.assertTrue(any("declared 1.97.1" in x for x in p["problems"]))

    def test_decoy_invocation_fails(self):
        p, _ = self.prove(decoy_hit=True)
        self.assertFalse(p["ok"])
        self.assertTrue(p["host_decoy"]["invoked"])

    def test_build_failure_fails(self):
        p, _ = self.prove(build_code=1)
        self.assertFalse(p["ok"])

    def test_missing_binary_fails(self):
        p, _ = self.prove(install=False)
        self.assertFalse(p["ok"])

    def test_declared_version_must_be_unique(self):
        (self.root / "MODULE.bazel").write_text('rust.toolchain(versions = ["1.97.1", "1.96.0"])\n')
        p, fake = self.prove()
        self.assertFalse(p["ok"])
        self.assertEqual(fake.calls, [])  # nothing is executed without a declaration

    def test_no_rustc_actions_fails(self):
        p, _ = self.prove(paths=())
        self.assertFalse(p["ok"])


if __name__ == "__main__":
    unittest.main()
