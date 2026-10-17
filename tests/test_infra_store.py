"""The local store: exact selection only, write-once, forward-only policy, explicit sources (ADR 0023)."""

import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import unittest
from pathlib import Path

from dev_platform import infra_provider, infra_store
from dev_platform.infra_release import ReleaseError
from tests.helpers import ROOT, tmpdir
from tests.infra_fixtures import OWNER, VERSION, config_repo, policy, request, write_policy


def tarball(root, prefix="org-repo-abc/", extra=()):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                tf.add(p, arcname=prefix + p.relative_to(root).as_posix())
        for name, kind in extra:
            ti = tarfile.TarInfo(prefix + name)
            ti.type = kind
            ti.linkname = "/etc/passwd"
            tf.addfile(ti)
    return buf.getvalue()


class Base(unittest.TestCase):
    def setUp(self):
        self.repo = tmpdir(self)
        self.digests = config_repo(self.repo, versions=(VERSION, "2026.02.1"))
        self.store = tmpdir(self) / "store"

    def src(self, version=VERSION):
        return infra_store.from_directory(self.repo, version)

    def install(self, version=VERSION, digest=None, src=None):
        return infra_store.install_release(
            self.store, src or self.src(version), version, digest or self.digests[version]
        )


class ExactSelection(Base):
    def test_installs_read_only_and_resolves_from_the_store(self):
        self.assertEqual(self.install(), "installed")
        self.assertEqual(infra_store.install_policy(self.store, self.src()), "updated")
        d = self.store / "releases" / VERSION
        self.assertFalse(os.stat(d).st_mode & stat.S_IWUSR)
        self.assertFalse(os.stat(d / "manifest.json").st_mode & stat.S_IWUSR)
        res = infra_provider.resolve(self.store, request(digest=self.digests[VERSION]))
        self.assertEqual(res["result"]["decision"], "resolved")
        self.assertEqual([r["status"] for r in infra_store.verify(self.store)], ["ok"])

    def test_idempotent_and_side_by_side(self):
        self.install()
        self.assertEqual(self.install(), "present")
        self.install("2026.02.1")
        self.assertEqual([r["version"] for r in infra_store.verify(self.store)], [VERSION, "2026.02.1"])

    def test_only_the_selected_release_is_copied(self):
        self.install()
        self.assertFalse((self.store / "releases" / "2026.02.1").exists())

    def test_refusals(self):
        for kw, code in (
            (dict(digest="sha256:" + "0" * 64), "digest-mismatch"),
            (dict(digest="0" * 64), "selection-invalid"),
            (dict(version="latest"), "version-invalid"),
        ):
            with self.assertRaises(ReleaseError, msg=kw) as cm:
                infra_store.install_release(
                    self.store,
                    self.src(),
                    kw.get("version", VERSION),
                    kw.get("digest", self.digests[VERSION]),
                )
            self.assertEqual(cm.exception.code, code)
        with self.assertRaises(ReleaseError) as cm:
            infra_store.install_release(self.store, self.src("2026.03.1"), "2026.03.1", self.digests[VERSION])
        self.assertEqual(cm.exception.code, "version-unknown")
        self.assertFalse((self.store / "releases").exists() and any((self.store / "releases").iterdir()))

    def test_tampered_source_is_refused(self):
        p = self.repo / "releases" / VERSION / "profiles" / "app.json"
        p.write_bytes(p.read_bytes().replace(b"docker", b"dockr"))
        with self.assertRaises(ReleaseError) as cm:
            self.install()
        self.assertEqual(cm.exception.code, "release-tampered")

    def test_symlink_in_source_is_refused(self):
        os.symlink("/etc/hosts", self.repo / "releases" / VERSION / "hosts")
        with self.assertRaises(ReleaseError) as cm:
            self.install()
        self.assertEqual(cm.exception.code, "release-tampered")

    def test_a_corrupted_store_entry_is_left_in_place(self):
        self.install()
        d = self.store / "releases" / VERSION
        os.chmod(d / "profiles", 0o755)
        os.chmod(d / "profiles" / "app.json", 0o644)
        (d / "profiles" / "app.json").write_text("{}")
        with self.assertRaises(ReleaseError) as cm:
            self.install()
        self.assertEqual(cm.exception.code, "store-corrupt")
        self.assertEqual((d / "profiles" / "app.json").read_text(), "{}")
        self.assertEqual(infra_store.verify(self.store)[0]["status"], "tampered")


class Policy(Base):
    def test_forward_only(self):
        infra_store.install_policy(self.store, self.src())
        write_policy(self.repo, revision=2, withdrawn={"runner_classes": [], "credentials": ["deploy"]})
        self.assertEqual(infra_store.install_policy(self.store, self.src()), "updated")
        self.assertEqual(infra_store.install_policy(self.store, self.src()), "unchanged")
        write_policy(self.repo, revision=1)
        with self.assertRaises(ReleaseError) as cm:
            infra_store.install_policy(self.store, self.src())
        self.assertEqual(cm.exception.code, "policy-rollback")
        write_policy(self.repo, revision=2)  # same revision, other content
        with self.assertRaises(ReleaseError) as cm:
            infra_store.install_policy(self.store, self.src())
        self.assertEqual(cm.exception.code, "policy-conflict")
        write_policy(self.repo, revision=9, policy_id="another-organization")
        with self.assertRaises(ReleaseError) as cm:
            infra_store.install_policy(self.store, self.src())
        self.assertEqual(cm.exception.code, "policy-mismatch")
        self.assertEqual(infra_store.stored_policy(self.store)["revision"], 2)

    def test_a_newer_policy_narrows_or_revokes_a_stored_release(self):
        self.install()
        infra_store.install_policy(self.store, self.src())
        a = infra_provider.resolve(self.store, request(digest=self.digests[VERSION]))
        write_policy(
            self.repo, revision=2, withdrawn={"runner_classes": ["linux-trusted"], "credentials": []}
        )
        infra_store.install_policy(self.store, self.src())
        b = infra_provider.resolve(self.store, request(digest=self.digests[VERSION]))
        self.assertEqual(a["result"]["resolved"], b["result"]["resolved"])
        self.assertNotIn("linux-trusted", [r["id"] for r in b["profile"]["runners"]])
        write_policy(self.repo, revision=3, revoked_releases=[{"version": VERSION}])
        infra_store.install_policy(self.store, self.src())
        c = infra_provider.resolve(self.store, request(digest=self.digests[VERSION]))
        self.assertEqual(c["result"]["decision"], "denied")

    def test_invalid_source_policy(self):
        (self.repo / infra_provider.POLICY).write_text(json.dumps({**policy(), "granted": []}))
        with self.assertRaises(ReleaseError) as cm:
            infra_store.install_policy(self.store, self.src())
        self.assertEqual(cm.exception.code, "policy-invalid")
        self.assertIsNone(infra_store.stored_policy(self.store))


class GitHubSource(Base):
    """`fetch` and `sync` through a stubbed `gh`: GET only, explicit source, the caller's identity."""

    def gh(self, data, fail=False):
        calls = []

        def runner(argv, **kw):
            calls.append(argv)
            if fail:
                return subprocess.CompletedProcess(argv, 1, b"", b"HTTP 404: Not Found")
            if argv[-2:] == ["--jq", ".sha"]:
                return subprocess.CompletedProcess(argv, 0, b"a" * 40 + b"\n", b"")
            return subprocess.CompletedProcess(argv, 0, data, b"")

        return runner, calls

    def test_fetch_one_commit_with_get_only(self):
        runner, calls = self.gh(tarball(self.repo))
        src = infra_store.from_github("example-org/infra", "main", VERSION, runner)
        self.assertEqual(self.install(src=src), "installed")
        self.assertEqual(src.commit, "a" * 40)
        for argv in calls:
            self.assertEqual(argv[:4], ["gh", "api", "--method", "GET"])
            self.assertFalse({"-X", "-f", "-F", "--input", "--field", "--raw-field"} & set(argv))
        self.assertIn(f"repos/example-org/infra/tarball/{'a' * 40}", calls[1])

    def test_links_in_the_tarball_are_refused(self):
        runner, _ = self.gh(tarball(self.repo, extra=[(f"releases/{VERSION}/evil", tarfile.SYMTYPE)]))
        with self.assertRaises(ReleaseError) as cm:
            self.install(src=infra_store.from_github("example-org/infra", "main", VERSION, runner))
        self.assertEqual(cm.exception.code, "release-tampered")

    def test_path_traversal_is_ignored(self):
        data = tarball(self.repo, prefix="x/")
        src = infra_store.from_tarball(data, "t", "a" * 40, VERSION)
        self.assertTrue(all(".." not in p for p in src.files))

    def test_no_access_changes_nothing(self):
        self.install()
        runner, _ = self.gh(b"", fail=True)
        with self.assertRaises(ReleaseError) as cm:
            infra_store.from_github("example-org/infra", "main", VERSION, runner)
        self.assertEqual(cm.exception.code, "access-denied")
        self.assertEqual([r["status"] for r in infra_store.verify(self.store)], ["ok"])

    def test_sources_are_never_defaulted_or_free_form(self):
        for repo, ref in (
            ("", "main"),
            ("no-slash", "main"),
            ("a/b; rm -rf /", "main"),
            ("a/b", "../x"),
            ("a/b", ""),
        ):
            with self.assertRaises(ReleaseError, msg=(repo, ref)):
                infra_store.commit_of(repo, ref, runner=lambda *a, **k: self.fail("gh must not run"))


class Commands(Base):
    def run_cli(self, *a, env=None):
        e = {k: v for k, v in os.environ.items() if k not in ("CI", "GITHUB_ACTIONS")}
        e.update(
            {"PYTHONPATH": str(ROOT / "src"), "DEV_PLATFORM_HOME": str(tmpdir(self) / "home")}, **(env or {})
        )
        return subprocess.run(
            [sys.executable, "-m", "dev_platform", "infra", *a], capture_output=True, text=True, env=e
        )

    def test_import_list_doctor(self):
        st = str(self.store)
        p = self.run_cli(
            "store",
            "import",
            VERSION,
            "--digest",
            self.digests[VERSION],
            "--from",
            str(self.repo),
            "--with-policy",
            "--store",
            st,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        p = self.run_cli("store", "list", "--store", st)
        self.assertEqual(json.loads(p.stdout)["releases"][0]["status"], "ok")
        p = self.run_cli(
            "doctor",
            "--store",
            st,
            "--json",
            "--repo",
            f"{OWNER}/app",
            "--digest",
            self.digests[VERSION],
            "--project",
            str(self.project(VERSION, self.digests[VERSION])),
        )
        self.assertNotEqual(p.returncode, 0)  # --project and --digest together is a usage problem
        p = self.run_cli(
            "doctor",
            "--store",
            st,
            "--json",
            "--repo",
            f"{OWNER}/app",
            "--project",
            str(self.project(VERSION, self.digests[VERSION])),
        )
        rep = json.loads(p.stdout)
        self.assertEqual(p.returncode, 0, rep["problems"])
        self.assertEqual(rep["selection"]["decision"], "resolved")
        text = p.stdout
        for private in ("example-trusted", "linux-trusted", "deploy", "signing", "docker"):
            self.assertNotIn(private, text)  # identities only, never profile contents

    def project(self, version, digest, kind=None):
        d = tmpdir(self)
        lines = [
            "[infra]",
            'provider = "example-infra"',
            f'config_release = "{version}"',
            f'config_digest = "{digest}"',
        ]
        if kind:
            lines.append(f'config_digest_kind = "{kind}"')
        (d / "dev-platform.toml").write_text("\n".join(lines) + "\n")
        return d

    def test_doctor_reports_denials_and_missing_policy(self):
        st = str(self.store)
        self.run_cli(
            "store",
            "import",
            VERSION,
            "--digest",
            self.digests[VERSION],
            "--from",
            str(self.repo),
            "--store",
            st,
        )
        p = self.run_cli("doctor", "--store", st, "--json")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no current authorization policy", " ".join(json.loads(p.stdout)["problems"]))
        p = self.run_cli(
            "doctor",
            "--root",
            str(self.repo),
            "--json",
            "--repo",
            "someone/app",
            "--project",
            str(self.project(VERSION, self.digests[VERSION])),
        )
        self.assertEqual(json.loads(p.stdout)["selection"]["reasons"], ["repo-not-enabled"])
        p = self.run_cli(
            "doctor",
            "--root",
            str(self.repo),
            "--json",
            "--repo",
            f"{OWNER}/app",
            "--project",
            str(self.project(VERSION, self.digests[VERSION], "profile-file")),
        )
        self.assertEqual(p.returncode, 2)

    def test_selection_is_required(self):
        self.assertEqual(
            self.run_cli("store", "import", "--from", str(self.repo), "--store", str(self.store)).returncode,
            2,
        )
        self.assertEqual(self.run_cli("store", "import", VERSION, "--from", str(self.repo)).returncode, 2)
        self.assertEqual(
            self.run_cli("store", "fetch", VERSION, "--digest", self.digests[VERSION]).returncode, 2
        )  # no --source

    def test_default_location_is_job_local_in_ci(self):
        e = {"CI": "true", "RUNNER_TEMP": str(tmpdir(self))}
        e_home = {k: v for k, v in os.environ.items() if k != "DEV_PLATFORM_HOME"}
        env = {**e_home, **e, "PYTHONPATH": str(ROOT / "src")}
        p = subprocess.run(
            [sys.executable, "-m", "dev_platform", "infra", "store", "list"],
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(
            json.loads(p.stdout)["store"], str(Path(e["RUNNER_TEMP"]).absolute() / "dev-platform" / "infra")
        )


if __name__ == "__main__":
    unittest.main()
