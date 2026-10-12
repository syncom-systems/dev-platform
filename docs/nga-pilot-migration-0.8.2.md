# NGA pilot: migration from the inline workflow (0.8.1 pins) to the reusable workflow at v0.8.2

For the NGA workspace. NGA owns this change, reviews it and verifies it before merging; this document changes nothing in NGA.
v0.8.2 is **verified-unaccepted**; the pilot stays an explicit opt-in (`allow_unaccepted: true`), non-required, hosted-only.

## Pinned identity (from `releases/0.8.2/identity.json`)
| | |
|---|---|
| version / tag | 0.8.2 / `v0.8.2` (annotated) |
| source revision | `f617b37edde2b5e550c813ea4b47c886a761dc62` |
| archive sha256 | `993c03fda1b0958dcc2ebee5484cdf620a7a953cf62df041bcddf7713a84f66f` |
| tree digest | `0f9780801f9e2b718e4f953739f8df2b085628ee91db1a60926f0c3060e0e5ad` |
| verifier pins | `verify_release.py` `a2d53075…`, policy file `577bcf92…`, `install_release.py` `473a2c73…`, `consumer_run.py` `bc502b37…` (full values in the diff) |

## The diff (three files, all already in NGA; the pilot target line is untouched)
```diff
--- a/dev-platform.toml
+++ b/dev-platform.toml
@@ -3,8 +3,8 @@
 schema_version = 1
 
 [platform]
-version = "0.8.1"
-sha256 = "35d5b2c99cc11e3da5b618ae4a19223b97834da2de2ac55f3a4e9f00759bffea"
+version = "0.8.2"
+sha256 = "0f9780801f9e2b718e4f953739f8df2b085628ee91db1a60926f0c3060e0e5ad"
 profile = "rust-bazel-9"
 
 [project]
--- a/dev-platform.release-pins.json
+++ b/dev-platform.release-pins.json
@@ -1,13 +1,15 @@
 {
-  "version": "0.8.1",
-  "source_revision": "5fa25c68814ee9f4d284682215fa4c98198103ff",
-  "archive_sha256": "5671100327d3b8bdfbf74277ae0b21bde39ec2f1f85d4abde12799647740a898",
-  "tree_digest_pin": "35d5b2c99cc11e3da5b618ae4a19223b97834da2de2ac55f3a4e9f00759bffea",
+  "version": "0.8.2",
+  "source_revision": "f617b37edde2b5e550c813ea4b47c886a761dc62",
+  "archive_sha256": "993c03fda1b0958dcc2ebee5484cdf620a7a953cf62df041bcddf7713a84f66f",
+  "tree_digest_pin": "0f9780801f9e2b718e4f953739f8df2b085628ee91db1a60926f0c3060e0e5ad",
   "verifier_pins": {
     "verify_release.py_sha256": "a2d53075b8bf11bb14f4a2dffb0b40fc6e66b04af73801951fcd768ba29f6f2e",
-    "trust_policy_sha256": "9074871080b437518cf0c7ad9558409297faf023b09365aa0ac6f52f7dba1120",
+    "trust_policy_sha256": "577bcf92633fd1de5f3d59c8bbc5f031b1554d40f49ed569cfdedbb70dc098cb",
     "install_release.py_sha256": "473a2c73eb71904ea6ee0e010f2288976126d4560e3efd11c33c11e44f15bb93",
+    "verify_app_release.py_sha256": "c53bf1351e4f87e7871e616b7eeaee8eca9cb999218e8f70519321cd361d8172",
+    "verify_platform_current.py_sha256": "55af0f2e20818b879fa998259e0e4d16da96afdbe48cd187e9203658408398fe",
     "verify_consumer_evidence.py_sha256": "2c5ee2890925d496025d5193e60a0a56953fdbb301f3335845fbb9c63864bbe7",
-    "consumer_run.py_sha256": "d2e6dbced5e540378d33a4beb07a0187af4d16beff5fa1c901d605490b8d012a"
+    "consumer_run.py_sha256": "bc502b3741ea5ba7632b1ed2d66d202e677ad91ca4d08ddc1f6b1330080d9a36"
   }
 }
--- a/.github/workflows/dev-platform-pilot.yml
+++ b/.github/workflows/dev-platform-pilot.yml
@@ -1,7 +1,5 @@
 # Limited Dev Platform pilot: independent and NOT a required check. It does not call, wrap or depend on `check` or
 # `full-gate`, reads no repository variable or secret, and runs on a literal GitHub-hosted runner with a read-only token.
-# The steps are those of syncom-systems/dev-platform's consumer-pilot.yml at the pinned revision, inlined because that
-# reusable workflow (v0.8.1) does not give `gh attestation verify` a token (GH_TOKEN) and so refuses every install.
 # Removal is deleting dev-platform.toml, dev-platform.release-pins.json and this file.
 name: dev-platform-pilot
 
@@ -18,33 +16,8 @@
 
 jobs:
   dev-platform:
-    runs-on: ubuntu-24.04
-    timeout-minutes: 60
-    steps:
-      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
-        with: {persist-credentials: false}
-      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
-        with:
-          repository: syncom-systems/dev-platform
-          ref: 5fa25c68814ee9f4d284682215fa4c98198103ff
-          path: .dev-platform-src
-          persist-credentials: false
-      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
-        with: {python-version: "3.14"}
-      - name: Keep the pilot's own directories out of the tree-cleanliness check (runner-local; no repository change)
-        run: |
-          echo '.dev-platform-src/' >> .git/info/exclude
-          echo 'dp-evidence/' >> .git/info/exclude
-      - name: Select, provision, execute, verify
-        env:
-          GH_TOKEN: ${{ github.token }}
-        run: |
-          python .dev-platform-src/tools/consumer_run.py --consumer-dir . --work "$RUNNER_TEMP/dp" \
-            --evidence-dir dp-evidence --dev-platform-checkout .dev-platform-src --allow-unaccepted
-      - name: Summary
-        if: always()
-        run: |
-          { echo '```json'; cat dp-evidence/consumer-run.json 2>/dev/null || echo '{"error":"no record"}'; echo '```'; } >> "$GITHUB_STEP_SUMMARY"
-      - uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2
-        if: always()
-        with: {name: dp-evidence, path: dp-evidence, if-no-files-found: ignore}
+    uses: syncom-systems/dev-platform/.github/workflows/consumer-pilot.yml@f617b37edde2b5e550c813ea4b47c886a761dc62
+    with:
+      platform_source_revision: "f617b37edde2b5e550c813ea4b47c886a761dc62"
+      allow_unaccepted: true
+      runs_on: ubuntu-24.04
```
The pins file also gains the two verifier digests the release identity lists; `consumer_run.py` does not require them and they are harmless.

## What changes in behavior
The inline job (copied from the 0.8.1 reusable workflow plus a `GH_TOKEN` and a runner-local `.git/info/exclude`) is replaced by the platform's
reusable workflow, which now (a) supplies the read-only token to the attestation check only, (b) needs only `contents: read`, and (c) checks the
consumer out to `consumer/` and the platform source to `platform/`, with evidence in `evidence/`, so no exclude entry is needed. No secret,
variable, self-hosted runner, private infrastructure or Cargo is involved; `check`, `full-gate` and the ruleset are not touched.

## Verify before merging (NGA's pull request)
1. The diff touches exactly the three files above; `check` is green and is still the only required status.
2. The `dev-platform-pilot` run: `consumer-run.json` shows `installed`, `pinned_tools`, `pins_consistent`, `provision_deterministic` true,
   `bazel_rust_proof` true, `event_trust` `untrusted` and `evidence_verdict` `consistent`; `bazel-rust-proof.json` shows `host_decoy.invoked` false,
   every rustc `bazel_external_repo` true and the observed version equal to the declared Rust version; `result.json` has `platform.pinned_version` 0.8.2
   and `platform.digest` equal to the tree digest above, and `infra.status` `hosted-only`.
3. The run used a GitHub-hosted `ubuntu-24.04` runner. If the run fails at install, stop; do not edit the pins to make it pass.

Reference: the same workflows at this revision ran green against a hosted validation consumer (`releases/0.8.2/consumer-workflow-validation/`).
