import json
import subprocess
import tomllib
import unittest

from dev_platform import engine
from dev_platform.config import parse
from dev_platform.model import Stage
from dev_platform.resolve import Resolution
from tests.helpers import ROOT, cfg_text, tmpdir


def schema(name):
    return json.loads((ROOT / "schemas" / name).read_text())


class SchemaContractTest(unittest.TestCase):
    def test_all_schemas_are_valid_json_with_ids(self):
        for p in (ROOT / "schemas").glob("*.json"):
            self.assertIn("$id", json.loads(p.read_text()), p.name)

    def test_result_matches_schema_shape(self):
        cfg = parse(tomllib.loads(cfg_text([("a", '["pre-merge"]', "change", '["src/**"]')])))
        doc = engine.build(
            cfg,
            ROOT,
            Resolution("pinned", "0.1.0", None, "d"),
            Stage.PRE_MERGE,
            ("src/x",),
            execute=True,
            executor=lambda c, w: 0,
            revision="r",
        )
        s = schema("result-v1.schema.json")
        self.assertEqual(set(doc), set(s["properties"]))
        self.assertTrue(set(s["required"]) <= set(doc))
        item = s["properties"]["checks"]["items"]
        self.assertTrue(set(item["required"]) <= set(doc["checks"][0]))
        self.assertTrue(set(doc["checks"][0]) <= set(item["properties"]))
        self.assertEqual(doc["schema"], s["properties"]["schema"]["const"])

    def test_config_schema_keys_match_parser(self):
        s = schema("config-v1.schema.json")
        self.assertEqual(
            set(s["properties"]), {"schema_version", "platform", "project", "impact", "runner", "check"}
        )
        self.assertEqual(
            set(s["properties"]["check"]["items"]["properties"]),
            {
                "id",
                "adapter",
                "stages",
                "obligation",
                "cost",
                "inputs",
                "targets",
                "argv",
                "runner",
                "description",
            },
        )


class RecordSchemaTest(unittest.TestCase):
    def test_required_keys_match_validators(self):
        from tests.test_records import app_release, auth

        for name, doc in (("app-release", app_release()), ("authorization", auth())):
            s = schema(f"{name}-v1.schema.json")
            self.assertTrue(set(s["required"]) <= set(doc), name)
            self.assertEqual(doc["schema"], s["properties"]["schema"]["const"])

    def test_release_and_toolchain_schemas_match_builder(self):
        import json as _json

        from dev_platform import release
        from tests.test_release import build

        doc = _json.loads((build(self) / "release.json").read_text())
        s = schema("release-v1.schema.json")
        self.assertEqual(set(doc), set(s["properties"]))
        self.assertEqual(doc["schema"], release.RELEASE_SCHEMA)
        self.assertEqual(
            schema("toolchains-v1.schema.json")["properties"]["schema"]["const"], doc["toolchains"]["schema"]
        )


class GitChangeTest(unittest.TestCase):
    def git(self, d, *a):
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=d, check=True, capture_output=True
        )

    def test_base_and_failure_modes(self):
        d = tmpdir(self)
        self.git(d, "init", "-q", "-b", "main")
        (d / "a.txt").write_text("1")
        self.git(d, "add", ".")
        self.git(d, "commit", "-qm", "c1")
        self.git(d, "checkout", "-qb", "topic")
        (d / "a.txt").write_text("2")
        (d / "new.txt").write_text("n")
        self.assertEqual(engine.git_changed(d, base="main"), ("a.txt", "new.txt"))
        self.git(d, "add", "a.txt")
        self.assertEqual(engine.git_changed(d, staged=True), ("a.txt",))
        self.assertIsNone(engine.git_changed(d, base="no-such-ref"))  # unknown, not empty
        self.assertIsNone(engine.git_changed(tmpdir(self), base="main"))  # not a repo

    def test_revision(self):
        self.assertIsNone(engine.git_revision(tmpdir(self)))


if __name__ == "__main__":
    unittest.main()
