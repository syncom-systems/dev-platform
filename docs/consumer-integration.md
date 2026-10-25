# Consumer integration (ADR 0021)

What a real consumer owns, what it runs and what it can prove, using only public data.

## The consumer owns every pin (committed, reviewed in its own pull requests)
| File | Pins |
|---|---|
| `dev-platform.toml` `[platform]` | release version, release **tree sha256**, toolchain profile |
| `dev-platform.toml` `[infra]` | infrastructure provider, **config release**, **config digest** (`sha256:`); absent = hosted runners only |
| `dev-platform.toml` `[platform]` (0.17.0) | the release identity from `releases/<version>/identity.json`: `source_revision`, `archive_sha256`, `[platform.verifier_pins]` (digests of the trusted verifier, policy and installer at that revision). Until 0.16.x this was `dev-platform.release-pins.json`, which `setup` reads only for a pin before 0.17.0 and the CI path below still needs ([ADR 0027](adr/0027-repository-isolation.md)) |
| `.dev-platform/infra-profile.json` | the vendored infrastructure profile; its sha256 must equal `[infra] config_digest` |

Upgrading the platform or the infrastructure configuration is an explicit edit of these files. Nothing floats: the engine
refuses a different release, a different configuration digest, or a provider that resolves anything but the pin.

## What `consumer_run.py` does (from public pins only)
1. checks the pin files agree with each other;
2. takes the trusted installer, verifier and policy from the public platform repository **at the pinned revision** and refuses
   them unless they equal the pinned digests;
3. installs the pinned release (verifies provenance, SBOM and build-environment attestations first; a release up to 0.11.0
   is verified-unaccepted and used only with `--allow-unaccepted`, a consumer decision);
4. `toolchain provision --pinned --verify` twice into clean directories: the realized environment is verified against the
   release's manifest (closure-verified tools) and the two verifications must be identical (deterministic provisioning);
5. `doctor` and `check --stage full --result` through the pinned platform, with the vendored infra profile and the event
   trust derived by the platform from the CI event (a provider is never called here);
6. for `rust-bazel*` profiles: `toolchain prove-bazel-rust` (Bazel's Rustc actions use an external-repository rustc at the
   declared version; decoy host `rustc`/`cargo` are never executed; Cargo is never run);
7. writes the evidence bundle and judges it with `tools/verify_consumer_evidence.py` against the consumer's own pins.

Exit status is 0 only when the evidence verdict is `consistent` (0.8.0 printed `verified`; the word was changed because it overstated: consistency with pins is not trustworthy execution). The reusable workflow `.github/workflows/consumer-pilot.yml` wraps this for GitHub Actions; call it as an additional job (not a
required check unless you decide so). It needs only `contents: read`; a caller grants nothing else:
```yaml
jobs:
  dev-platform:
    uses: syncom-systems/dev-platform/.github/workflows/consumer-pilot.yml@<full commit sha of the pinned release>
    with: {platform_source_revision: "<same sha>", allow_unaccepted: true, runs_on: ubuntu-24.04}
```
Layout on the runner: the consumer is checked out to `consumer/`, the platform source (at the pinned revision) to `platform/` and
the evidence to `evidence/` (artifact `dp-evidence`), three siblings, so nothing the run writes can dirty the consumer's working
tree; `consumer_run.py` refuses a work, evidence or platform directory inside the consumer directory. The job's read-only token is
given to `gh attestation verify` (the installer) only and removed from every later process, including the consumer's builds and
tests; checkouts persist no credentials. v0.8.0 and v0.8.1 shipped without the token, with the attestation permissions required of
every caller and with the platform source and evidence inside the consumer tree; use v0.8.2 or later.

Optional attestation of the evidence is a separate workflow and a separate job, the only one that holds `id-token` and
`attestations` write; it checks nothing out and runs no code:
```yaml
  attest:
    needs: dev-platform
    if: always() && needs.dev-platform.result != 'skipped'
    uses: syncom-systems/dev-platform/.github/workflows/consumer-pilot-attest.yml@<same sha>
    permissions: {contents: read, id-token: write, attestations: write}
```

## Evidence and how it is verified
`dp-evidence/` holds `result.json` (`dev-platform.result/v1`, including `platform`, `environment`, `infra` and
`certification`), the consumer's `dev-platform.toml` and release pins, `bazel-rust-proof.json` (Bazel consumers),
`consumer-run.json` and `verification.json`. Anyone can re-check it:
```
python3 -I tools/verify_consumer_evidence.py --result result.json --config dev-platform.toml \
  [--bazel-proof bazel-rust-proof.json --require-bazel-proof] [--revision <consumer commit>]
gh attestation verify result.json --repo <consumer repo> --signer-workflow <consumer repo>/.github/workflows/<caller>.yml
```
The verifier checks that the record used exactly the pinned release (mode, version, tree digest), a conformant and
certifiable toolchain environment, the pinned infrastructure configuration (resolved identity equals the pin), and the
Bazel Rust proof. The attestation shows which workflow run produced the files.

## What the infrastructure block establishes, and what it does not
`result.infra` records the exact configuration release and digest the consumer pinned (`pinned`), what the source resolved
(`resolved`, `source`), the provider's claimed authorization policy identity if any, and the effective profile digest; never
profile contents. It does not establish that private infrastructure was or is authorized for this run: that stays the provider's
decision (per run, for trusted events only) and the runner-group/environment settings on GitHub. In untrusted CI the evidence
shows `source: vendored-file` and no authorization policy, which confers no private access. `verification.json` carries
`not_established` listing exactly this, so a reader cannot take the verdict for more than it is.

## Relationship to the consumer's own gates
The run is an additional job: it must not replace, wrap, reorder or relax a consumer's existing build, test, security or
release gates, and it is not a required check unless the owner of that repository makes it one. A `consistent` verdict never
substitutes for a passing gate, and a failing platform job never excuses one.

## Limits (read these)
- The verdict is consistency with the consumer's pins. It does not prove the consumer job was not subverted: the job that
  executes the consumer's code also writes the record. The attestation binds the bytes to a workflow run, not to their truth.
  The platform's gate does not replace the consumer's own gates.
- Toolchains are closure-verified, not hermetic; Bazel-fetched artifacts are covered by the Bazel lock and the Rust proof only.
- The Rust proof covers Rustc actions of the chosen target pattern; repository rules run at fetch time with Bazel's environment.
- Infrastructure: untrusted events use only the vendored profile (public runner labels and credential class names). Private
  runners and credentials are decided by trusted events and the provider's own authorization; the public platform never reads
  the private repository (`docs/infra-integration.md`).
- Running this in a consumer's CI is the owner's decision (a production CI change); nothing here modifies a consumer.
