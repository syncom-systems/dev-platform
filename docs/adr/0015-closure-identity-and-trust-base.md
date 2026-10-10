# 0015 Closure identity, SBOM correspondence and the verification trust base

Status: Ratified (owner directive, turn 4). Amends ADR 0010 (identity strength); extends ADR 0014.

## Four different claims
These are kept apart in every record, document and command:
1. **Development verification** - the checks a change owes ran and passed (`dev-platform check`).
2. **Release verification** - an archive was independently shown to be the artifact the trusted
   workflow built from the expected revision (`tools/verify_release.py`, `dev-platform.verification/v1`).
3. **Certification** - a result record is `certifiable` (pinned platform, clean tree, full stage, every
   check verified, every tool in the environment strongly identified).
4. **Owner acceptance** - an effective `authorization/v1` bound to the exact archive digest. Nothing
   automated can produce it.

## Tool identity covers the runtime closure
A version string, a filename, or the digest of one executable does not identify what runs. A tool's
manifest entry may declare a `closure`:
- `kind: file` (a single static-ish executable) or `kind: prefix` (an install tree, `prefix_up`
  levels above the executable's real path - e.g. an interpreter with its standard library).
- `sha256`: per `<sys.platform>-<machine>` canonical digest over every file (path, bytes, executable
  bit) and every symlink (relative target; absolute or escaping links are rejected), excluding
  bytecode caches.
- `system_libs`: the only things the closure may load from outside itself.
Verification (`closure.py`) establishes (1) the digest equals the pin for this platform and (2) every
native object (ELF/Mach-O) in the closure depends only on closure members or declared system
libraries; an object whose dependencies cannot be listed fails closed. Result: `closure-verified`.
No pin for the current platform means only the version was established (`version-only`); it never
errors into a stronger claim.

What is **not** claimed, and is stated in each record (`closure.scope`): system libraries are trusted by
name/prefix, not by content; `dlopen` of paths outside the closure is not enumerated; the host kernel,
CPU and `gh`/`otool`/`readelf` used for inspection are outside the claim.

Pins are authored with `dev-platform toolchain measure` and are reviewed manifest changes. Realization
(`tools/setup_env.py`) only produces bytes: the python-build-standalone archive named in the manifest
(`source`, https + sha256 checked before extraction, extracted unmodified so the closure is
location-independent) and a `--require-hashes` locked ruff wheel. Whether the result is right is decided
by closure verification, in CI on linux-x86_64 and macOS-arm64 (`toolchain verify --require-certifiable`).
A package manager that rewrites files at install time (uv-managed pythons patch install names) is
unsuitable for closure pins because the digest then depends on the install path; this was measured.

## SBOM correspondence
The SBOM carries, per tool component, the closure digests (properties) and source archives (external
references with hashes) from the manifest. The independent verifier checks: SBOM file digest equals
`release.json`; the component set and pins equal the manifest exactly (no missing, no undeclared); the
root component is this version and source digest; and the SBOM **attestation** verifies under the same
signer policy and its predicate equals the SBOM inside the archive.

## Verification trust base (minimal)
Roots, none of which is the artifact under verification:
1. The Sigstore public-good trust root as embedded in the `gh` binary used to verify attestations.
2. The trust policy (`trust/policy.json`): OIDC issuer, signer repository/workflow, ref pattern, hosted
   runner requirement. A valid signature that does not match the policy is rejected.
3. The expected source revision, taken from git (the tag), not from release assets.
4. The verifier code itself, obtained out of band at a revision the operator pins.
5. For stable releases, the owner's authorization record.
A previously accepted platform release is **continuity evidence** only: it may corroborate that the
policy and signer are unchanged, but a release is never verified by code that arrives inside it, and no
single previous release is the sole root.

## Supported scope fails closed; environment evidence is not hermeticity (turn 5)
- The first stable release supports only combinations that passed real qualification (python, rust-bazel;
  linux-x86_64 and darwin-arm64; see docs/consumer-compatibility.md). A tool with no pinned closure for the
  current platform, or a profile outside the manifest, can never yield `assurance = certifiable`; the
  result is `diagnostic` and certification is blocked, naming the tools. There is no override.
- Every environment record carries `platform` and `scope = {hermetic: false, limitations: [...]}`, and the
  result's `certification.limitations` repeats them. The limitations always include that system libraries
  are trusted by name, not by content, and that host kernel/CPU/filesystem are outside the evidence; for
  Bazel-managed tools also that the Bazel repository cache, the host C toolchain and fetch-time network are
  outside the evidence. Nothing in this repository claims a hermetic environment.
- The build-environment record is attested together with the archive. `tools/verify_release.py
  --environment` checks it against the release's own manifest (profile, certifiable, non-hermetic
  statement, every tool `closure-verified` with the digest the manifest pins for the recorded platform,
  same version, same tool set) and verifies its attestation under the signer policy. Policy key
  `require_environment_evidence` makes the record mandatory.
- Publishing reflects the verified state. A stable tag without an effective owner authorization is
  published as `verified-unaccepted`: a GitHub pre-release titled "NOT accepted", with notes saying so.
  The workflow never passes authorization records and so can never publish `accepted`.
