"""dev-platform.infra-config/v1: validation fails closed, projection maps onto the one contract (ADR 0023)."""

import copy
import json
import os
import subprocess
import sys
import unittest

from dev_platform import infra_config as C
from dev_platform import infra_provider, infra_release, prcheck, runners
from dev_platform.config import RunnerSpec
from tests.helpers import ROOT, tmpdir
from tests.infra_fixtures import write_policy

OWNER = "example-org"


def hosted_only():
    return C.template("github-hosted", OWNER, ["app"])


def self_hosted():
    cfg = C.template("self-hosted", OWNER, ["app", "site"])
    cfg["repositories"][1]["visibility"] = "public"
    cfg["repositories"][1]["runners"] = ["github-ubuntu-24.04"]
    cfg["runner_groups"][0]["repositories"] = ["app"]
    cfg["credential_refs"] = [
        {
            "id": "deploy-key",
            "class": "deploy",
            "provider": "github-environment-secret",
            "scope": "environment:release",
            "binding": "unbound",
        }
    ]
    cfg["runners"][-1]["credentials"] = ["deploy"]
    cfg["caches"] = [{"id": "build-cache", "modes": {"trusted": "read-write", "untrusted": "none"}}]
    cfg["repositories"][0]["cache"] = "build-cache"
    return cfg


def broken(mutate, base=self_hosted):
    cfg = base()
    mutate(cfg)
    return C.problems(cfg)


def runner(cfg, rid):
    return next(r for r in cfg["runners"] if r["id"] == rid)


class Templates(unittest.TestCase):
    def test_templates_validate(self):
        for kind in ("github-hosted", "self-hosted"):
            self.assertEqual(C.problems(C.template(kind, OWNER, ["a", "b"])), [], kind)
        self.assertEqual(C.problems(self_hosted()), [])

    def test_github_hosted_examples_are_public_ephemeral_without_credentials(self):
        cfg = hosted_only()
        prof = C.profile_for(cfg, "app")
        self.assertEqual(runners.validate_profile(prof), [])
        for r in prof["runners"]:
            self.assertEqual((r["trust"], r["isolation"], r["credentials"]), ("public", "ephemeral", []))
        self.assertEqual(
            {tuple(h["labels"]) for h in C.GITHUB_HOSTED}, {tuple(r["labels"]) for r in prof["runners"]}
        )

    def test_hosted_only_needs_no_infrastructure_of_its_own(self):
        cfg = hosted_only()
        self.assertNotIn("runner_groups", cfg)
        self.assertFalse(any(r["placement"] == "self-hosted" for r in cfg["runners"]))
        self.assertEqual(C.notes(cfg), [])

    def test_the_hosted_examples_route_and_pass_admission(self):
        prof = C.profile_for(hosted_only(), "app")
        offered = runners.load_profile(None)
        offered = [{"kind": "self-hosted", **r} for r in prof["runners"]] + offered
        for os_, arch in (("linux", "x86_64"), ("linux", "arm64"), ("macos", "arm64")):
            route = runners.route(RunnerSpec("x", os=os_, arch=arch), offered, "untrusted")
            self.assertTrue(route.ok, (os_, arch, route.reason))
        wf = "on: pull_request\njobs:\n  a:\n    runs-on: ubuntu-24.04-arm\n    steps: [{run: x}]\n"
        self.assertEqual(prcheck.check({"w.yml": wf}, prof)["admission"], "ok")


class Examples(unittest.TestCase):
    def test_public_examples_validate(self):
        files = sorted((ROOT / "examples" / "infra").rglob("*.json"))
        self.assertEqual(len(files), 2)
        for f in files:
            self.assertEqual(C.problems(json.loads(f.read_text())), [], f)

    def test_schema_documents_exactly_the_validated_keys(self):
        s = json.loads((ROOT / "schemas" / "infra-config-v1.schema.json").read_text())
        p = s["properties"]
        self.assertEqual(set(p), C._TOP)
        self.assertEqual(set(p["runners"]["items"]["properties"]), C._RUNNER)
        self.assertEqual(set(p["runner_groups"]["items"]["properties"]), C._GROUP)
        self.assertEqual(set(p["caches"]["items"]["properties"]), C._CACHE)
        self.assertEqual(set(p["credential_refs"]["items"]["properties"]), C._CRED)
        self.assertEqual(set(p["repositories"]["items"]["properties"]), C._REPO)
        self.assertEqual(
            set(p["repositories"]["items"]["properties"]["desired"]["properties"]), set(C._DESIRED)
        )


class FailsClosed(unittest.TestCase):
    def assertRejects(self, mutate, needle, base=self_hosted):
        errs = broken(mutate, base)
        self.assertTrue(any(needle in e for e in errs), f"{needle!r} not in {errs}")

    def test_unknown_keys_everywhere(self):
        self.assertRejects(lambda c: c.update(extra=1), "unknown keys")
        self.assertRejects(lambda c: c["runners"][0].update(kind="hosted"), "unknown keys")
        self.assertRejects(lambda c: c["repositories"][0].update(trust="trusted"), "unknown keys")
        self.assertRejects(
            lambda c: c["repositories"][0]["desired"].update(branch_protection="off"), "unknown keys"
        )
        self.assertRejects(lambda c: c["admission"].update(event_trust="trusted"), "unknown keys")

    def test_wrong_schema_and_owner(self):
        self.assertTrue(C.problems({**self_hosted(), "schema": "dev-platform.infra-config/v2"}))
        self.assertTrue(C.problems([]))
        self.assertRejects(lambda c: c.update(owner="not an owner"), "owner")

    def test_unknown_runner_group(self):
        self.assertRejects(
            lambda c: runner(c, "linux-build").update(runner_group="elsewhere"), "runner_group"
        )
        self.assertRejects(lambda c: runner(c, "linux-build").pop("runner_group"), "runner_group")

    def test_runner_group_must_admit_the_repository(self):
        self.assertRejects(lambda c: c["runner_groups"][0].update(repositories=[]), "does not admit")
        self.assertRejects(
            lambda c: c["runner_groups"][0].update(repositories=["app", "ghost"]), "unknown repository"
        )

    def test_public_repository_and_self_hosted_runners(self):
        def public_self_hosted(c):
            c["repositories"][1]["runners"].append("linux-build")
            c["runner_groups"][0]["repositories"].append("site")

        self.assertRejects(public_self_hosted, "does not allow public repositories")

        def persistent(c):
            public_self_hosted(c)
            c["runner_groups"][0]["allows_public_repositories"] = True
            runner(c, "linux-build")["isolation"] = "persistent"

        self.assertRejects(persistent, "persistent runner")

        def no_approval(c):
            public_self_hosted(c)
            c["runner_groups"][0]["allows_public_repositories"] = True

        self.assertRejects(no_approval, "fork_pr_approval")

    def test_persistent_runner_never_serves_untrusted_events(self):
        def f(c):
            r = runner(c, "linux-build")
            r.update(trust="public", isolation="persistent", credentials=[])

        self.assertRejects(f, "persistent runner must never serve untrusted events")

    def test_self_hosted_runner_cannot_pose_as_hosted(self):
        self.assertRejects(
            lambda c: runner(c, "linux-build").update(labels=["ubuntu-24.04"]), "GitHub-hosted image label"
        )

    def test_github_hosted_shape(self):
        self.assertRejects(
            lambda c: c["runners"][0].update(labels=["self-hosted", "x"]), "standard image label"
        )
        self.assertRejects(lambda c: c["runners"][0].update(labels=["windows-2025"]), "standard image label")
        self.assertRejects(lambda c: c["runners"][0].update(isolation="persistent"), "ephemeral")
        self.assertRejects(lambda c: c["runners"][0].update(runner_group="g"), "no runner_group")

    def test_credentials_are_references_with_a_class(self):
        self.assertRejects(
            lambda c: runner(c, "linux-build").update(credentials=["cloud-admin"]), "no credential_ref"
        )
        self.assertRejects(lambda c: c["credential_refs"][0].update(value="x"), "unknown keys")
        self.assertRejects(lambda c: c["credential_refs"][0].update(binding="maybe"), "binding")
        self.assertRejects(
            lambda c: c["credential_refs"][0].update(provider="ghp_" + "a" * 36), "embedded secret"
        )

    def test_public_trust_runner_never_offers_credentials_or_a_writable_cache(self):
        self.assertRejects(lambda c: c["runners"][0].update(credentials=["deploy"]), "trust 'trusted'")
        self.assertRejects(lambda c: c["runners"][0].update(cache="read-write"), "read-write")

    def test_caches(self):
        self.assertRejects(
            lambda c: c["caches"][0]["modes"].update(untrusted="read-only"), "untrusted events"
        )
        self.assertRejects(lambda c: c["caches"][0].update(modes={"trusted": "all"}), "modes")
        self.assertRejects(lambda c: c["caches"][0].update(credential_ref="ghost"), "unknown credential_ref")
        self.assertRejects(lambda c: c["repositories"][0].update(cache="ghost"), "unknown cache")
        self.assertRejects(lambda c: c["repositories"][1].update(cache="build-cache"), "shared cache")
        self.assertRejects(
            lambda c: c["caches"][0].update(endpoint="https://user:pw@cache.example"), "embedded secret"
        )

    def test_references_and_duplicates(self):
        self.assertRejects(lambda c: c["repositories"][0]["runners"].append("ghost"), "unknown runner")
        self.assertRejects(lambda c: c["runners"].append(copy.deepcopy(c["runners"][0])), "duplicate")
        self.assertRejects(
            lambda c: c["repositories"].append(copy.deepcopy(c["repositories"][0])), "duplicate"
        )
        self.assertRejects(
            lambda c: c["admission"].update(forbidden_triggers=["pull_request_targett"]), "unknown trigger"
        )

    def test_required_lists_are_required(self):
        for key in ("runners", "repositories"):
            self.assertRejects(lambda c, key=key: c.pop(key), f"{key}: required")

    def test_credentials_and_capabilities_must_be_lists(self):
        self.assertRejects(
            lambda c: runner(c, "linux-build").update(credentials="deploy"), "credentials: a list"
        )
        self.assertRejects(
            lambda c: runner(c, "linux-build").update(capabilities="docker"), "capabilities: a list"
        )
        self.assertRejects(lambda c: runner(c, "linux-build").update(labels="build"), "labels: a list")

    def test_an_unassigned_runner_is_validated_too(self):
        def f(c):
            c["runners"].append(dict(c["runners"][0], id="spare", os="windows"))

        self.assertRejects(f, "runners: runners[")

    def test_secret_values_anywhere(self):
        for s in ("-----BEGIN OPENSSH PRIVATE KEY-----", "AKIA" + "A" * 16, "github_pat_x", "xoxb-12345"):
            self.assertRejects(
                lambda c, s=s: runner(c, "linux-build").update(description=s), "embedded secret"
            )


class Projection(unittest.TestCase):
    def test_profile_is_only_the_assigned_runners_and_the_admission(self):
        cfg = self_hosted()
        app, site = C.profile_for(cfg, "app"), C.profile_for(cfg, "site")
        self.assertIn("linux-build", [r["id"] for r in app["runners"]])
        self.assertEqual([r["id"] for r in site["runners"]], ["github-ubuntu-24.04"])
        for prof in (app, site):
            self.assertEqual(runners.validate_profile(prof), [])
            self.assertEqual(prof["admission"], cfg["admission"])
            text = json.dumps(prof)
            for private in ("runner_group", "trusted-builds", "deploy-key", "build-cache", "placement"):
                self.assertNotIn(private, text)

    def test_trusted_runner_is_not_offered_to_untrusted_events(self):
        prof = C.profile_for(self_hosted(), "app")
        offered = [{"kind": "self-hosted", **r} for r in prof["runners"]]
        spec = RunnerSpec("deploy", credentials=("deploy",))
        self.assertTrue(runners.route(spec, offered, "trusted").ok)
        self.assertFalse(runners.route(spec, offered, "untrusted").ok)

    def test_release_build_resolves_through_the_generic_provider(self):
        root = tmpdir(self)
        cfg = self_hosted()
        hexd = infra_release.build(root, "2026.10.1", C.release_files(cfg, "2026.10.1"))
        write_policy(root, minimum_release="2026.10.1", repositories_enabled=["app", "site"])
        from tests.infra_fixtures import request

        res = infra_provider.resolve(
            root, request(version="2026.10.1", digest="sha256:" + hexd, repo=f"{OWNER}/app")
        )
        self.assertEqual(res["result"]["decision"], "resolved", res["result"]["reasons"])
        self.assertEqual(res["profile"], C.profile_for(cfg, "app"))


class Commands(unittest.TestCase):
    def run_cli(self, *a, cwd=None):
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        return subprocess.run(
            [sys.executable, "-m", "dev_platform", *a], capture_output=True, text=True, env=env, cwd=cwd
        )

    def test_init_validate_profile_build(self):
        root = tmpdir(self)
        p = self.run_cli(
            "infra",
            "init",
            "--root",
            str(root),
            "--owner",
            OWNER,
            "--repo",
            "app",
            "--template",
            "self-hosted",
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["activated"], [])
        self.assertEqual(
            sorted(x.relative_to(root).as_posix() for x in root.rglob("*") if x.is_file()),
            ["config/infra.v1.json"],
        )
        self.assertNotEqual(
            self.run_cli("infra", "init", "--root", str(root), "--owner", OWNER).returncode, 0
        )
        self.assertEqual(self.run_cli("infra", "validate", str(root)).returncode, 0)
        p = self.run_cli("infra", "profile", "--config", str(root / "config/infra.v1.json"), "--repo", "app")
        self.assertEqual(runners.validate_profile(json.loads(p.stdout)), [])
        p = self.run_cli("infra", "release", "build", "2026.10.1", "--root", str(root))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.run_cli("infra", "release", "verify", "--root", str(root)).returncode, 0)
        self.assertNotEqual(
            self.run_cli("infra", "release", "build", "2026.10.1", "--root", str(root)).returncode, 0
        )

    def test_validate_reports_and_fails(self):
        root = tmpdir(self)
        bad = self_hosted()
        runner(bad, "linux-build")["runner_group"] = "elsewhere"
        f = root / "c.json"
        f.write_text(json.dumps(bad))
        p = self.run_cli("infra", "validate", str(f))
        self.assertEqual(p.returncode, 1)
        self.assertFalse(json.loads(p.stdout)["valid"])

    def test_workflows_with_an_undeclared_runner_group_fail(self):
        root = tmpdir(self)
        f = root / "c.json"
        f.write_text(json.dumps(self_hosted()))
        wf = root / "wf"
        wf.mkdir()
        (wf / "a.yml").write_text(
            "on: push\njobs:\n  a:\n    runs-on: {group: elsewhere, labels: [x]}\n    steps: [{run: x}]\n"
        )
        p = self.run_cli("infra", "validate", str(f), "--workflows", str(wf), "--repo", "app")
        out = json.loads(p.stdout)
        self.assertEqual(p.returncode, 1)
        self.assertTrue(out["workflows"]["unknown_runner_groups"])
        (wf / "a.yml").write_text(
            "on: push\njobs:\n  a:\n    runs-on: {group: trusted-builds, labels: [x]}\n    steps: [{run: x}]\n"
        )
        out = json.loads(
            self.run_cli("infra", "validate", str(f), "--workflows", str(wf), "--repo", "app").stdout
        )
        self.assertEqual(out["workflows"]["unknown_runner_groups"], [])
        self.assertEqual(out["workflows"]["admission"], "ok")
        # reachable from pull requests, a declared group is still not judged admitted: it stays incomplete
        (wf / "a.yml").write_text(
            "on: pull_request\njobs:\n  a:\n    runs-on: {group: trusted-builds, labels: [x]}\n    steps: [{run: x}]\n"
        )
        p = self.run_cli("infra", "validate", str(f), "--workflows", str(wf), "--repo", "app")
        self.assertEqual(p.returncode, 1)
        self.assertNotEqual(json.loads(p.stdout)["workflows"]["admission"], "ok")


if __name__ == "__main__":
    unittest.main()
