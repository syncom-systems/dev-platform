"""The independent consumer-evidence verifier: every pin the consumer owns must be reflected in the record."""

import copy
import importlib.util
import json
import unittest

from tests.helpers import ROOT, tmpdir

spec = importlib.util.spec_from_file_location("vce", ROOT / "tools" / "verify_consumer_evidence.py")
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)

TREE = "c" * 64
CFG_DIGEST = "sha256:" + "d" * 64
CONFIG = {
    "platform": {"version": "0.8.0", "sha256": TREE, "profile": "rust-bazel-9"},
    "infra": {"provider": "acme-infra", "config_release": "1.4.0", "config_digest": CFG_DIGEST},
}
RESULT = {
    "schema": "dev-platform.result/v1",
    "platform": {"mode": "pinned", "pinned_version": "0.8.0", "digest": TREE, "running_version": "0.8.0"},
    "environment": {
        "release": {"version": "0.8.0", "tree_digest": TREE},
        "profile": "rust-bazel-9",
        "conformant": True,
        "assurance": "certifiable",
        "weak_tools": [],
    },
    "executed": True,
    "stage": "full",
    "revision": "r" * 40,
    "unsatisfied_obligations": [],
    "certification": {"certified": True, "blockers": []},
    "infra": {
        "status": "resolved",
        "source": "vendored-file",
        "pinned": CONFIG["infra"],
        "resolved": {"version": "1.4.0", "digest": CFG_DIGEST},
        "contract": "dev-platform.infra/v1",
        "reasons": [],
    },
}
PROOF = {
    "schema": "dev-platform.bazel-rust-proof/v1",
    "ok": True,
    "problems": [],
    "declared_versions": ["1.97.1"],
    "observed": ["1.97.1"],
    "host_decoy": {"invoked": False, "invocations": []},
    "rustc": [{"bazel_external_repo": True, "version": "1.97.1"}],
}


def verdict(result=RESULT, config=CONFIG, proof=PROOF, **kw):
    return V.verify(copy.deepcopy(result), copy.deepcopy(config), copy.deepcopy(proof), **kw)


def failed(doc):
    return {c["id"] for c in doc["checks"] if c["status"] == "failed"}


class Verify(unittest.TestCase):
    def test_consistent_evidence_is_verified(self):
        d = verdict(revision="r" * 40, require_bazel_proof=True)
        self.assertEqual(d["verdict"], "consistent", failed(d))

    def mutate(self, path, value, expect, **kw):
        r = copy.deepcopy(RESULT)
        node = r
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
        d = verdict(result=r, **kw)
        self.assertEqual(d["verdict"], "inconsistent", path)
        self.assertIn(expect, failed(d), path)

    def test_every_pin_is_checked(self):
        self.mutate(["platform", "mode"], "self", "platform-pinned")
        self.mutate(["platform", "pinned_version"], "0.9.0", "platform-version")
        self.mutate(["platform", "digest"], "e" * 64, "platform-tree-digest")
        self.mutate(["environment", "release", "tree_digest"], "e" * 64, "release-identity")
        self.mutate(["environment", "profile"], "rust-cargo", "toolchain-profile")
        self.mutate(["environment", "conformant"], False, "environment-conformant")
        self.mutate(["environment", "assurance"], "diagnostic", "environment-certifiable")
        self.mutate(["executed"], False, "executed-full-stage")
        self.mutate(["stage"], "pre-merge", "executed-full-stage")
        self.mutate(["certification", "certified"], False, "certified")
        self.mutate(["revision"], "x" * 40, "revision", revision="r" * 40)

    def test_infra_must_be_resolved_to_exactly_the_pin(self):
        self.mutate(["infra", "status"], "unavailable", "infra-resolved")
        self.mutate(
            ["infra", "resolved"], {"version": "1.5.0", "digest": CFG_DIGEST}, "infra-resolved-equals-pin"
        )
        self.mutate(["infra", "pinned", "config_release"], "1.3.0", "infra-pin-matches-config")
        self.mutate(["infra", "contract"], "dev-platform.infra/v2", "infra-contract")

    def test_a_result_with_infra_but_no_pin_in_the_config_is_rejected(self):
        cfg = {"platform": CONFIG["platform"]}
        d = verdict(config=cfg)
        self.assertIn("infra-not-pinned-hosted-only", failed(d))

    def test_hosted_only_without_pin_is_fine(self):
        r = copy.deepcopy(RESULT)
        r["infra"] = {"status": "hosted-only"}
        d = verdict(result=r, config={"platform": CONFIG["platform"]})
        self.assertEqual(d["verdict"], "consistent", failed(d))

    def test_self_hosted_results_are_not_consumer_evidence(self):
        d = verdict(config={"platform": {"self_hosted": True}})
        self.assertIn("config-pins-platform", failed(d))

    def test_bazel_proof_failures(self):
        for field, value, expect in (
            ("ok", False, "bazel-proof-ok"),
            ("observed", ["1.96.0"], "bazel-rust-version"),
            ("host_decoy", {"invoked": True}, "bazel-no-host-tool"),
            ("rustc", [{"bazel_external_repo": False}], "bazel-toolchain-external"),
            ("schema", "other", "bazel-proof-schema"),
        ):
            p = copy.deepcopy(PROOF)
            p[field] = value
            d = verdict(proof=p, require_bazel_proof=True)
            self.assertIn(expect, failed(d), field)

    def test_it_states_what_it_does_not_establish(self):
        d = verdict()
        text = " ".join(d["not_established"])
        for needle in ("subverted", "fabricated", "private infrastructure", "gates"):
            self.assertIn(needle, text)

    def test_required_proof_missing(self):
        d = verdict(proof=None, require_bazel_proof=True)
        self.assertEqual(d["verdict"], "inconsistent")

    def test_cli_reads_the_consumers_own_toml(self):
        d = tmpdir(self)
        (d / "r.json").write_text(json.dumps(RESULT))
        (d / "dev-platform.toml").write_text(
            f'schema_version = 1\n[platform]\nversion = "0.8.0"\nsha256 = "{TREE}"\nprofile = "rust-bazel-9"\n'
            f'[infra]\nprovider = "acme-infra"\nconfig_release = "1.4.0"\nconfig_digest = "{CFG_DIGEST}"\n'
        )
        (d / "p.json").write_text(json.dumps(PROOF))
        argv = [
            "--result",
            str(d / "r.json"),
            "--config",
            str(d / "dev-platform.toml"),
            "--bazel-proof",
            str(d / "p.json"),
            "--out",
            str(d / "v.json"),
        ]
        self.assertEqual(V.main(argv), 0)
        out = json.loads((d / "v.json").read_text())
        self.assertEqual(out["verdict"], "consistent")
        self.assertEqual(len(out["evidence"]["r.json"]), 64)


if __name__ == "__main__":
    unittest.main()
