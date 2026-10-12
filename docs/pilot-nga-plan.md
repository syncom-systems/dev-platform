# Pilot adoption plan: nga (first production consumer)

Status: plan only. **Nothing here migrates nga, modifies the nga repository, or is authorized by any release
acceptance.** nga is private; this plan is derived from reading its public-to-the-owner declarations
(`.bazelversion`, `.bazelrc`, `MODULE.bazel`, workflow names) and from the flight pilot
([pilot results](../pilot/consumers.json)). Decisions that are the owner's are marked **owner**.

## What nga declares (read-only inspection)
| Declaration | Value | Platform status |
|---|---|---|
| Build system | Bazel only ("never invoke cargo") | `bazel_only = true` supported; `rust-cargo` profiles must not apply |
| Bazel | 9.2.0 (`.bazelversion`) | profile `rust-bazel-9` added for qualification (shipped `rust-bazel` is 8.4.2) |
| rules_rust | 0.74.0 | `rust-bazel-9` integrity pin (BCR `source.json` digest) |
| Rust | 1.97.1, edition 2024, extra target `aarch64-unknown-none-softfloat` | toolchain pin ok; the extra bare-metal target is **not** covered by evidence |
| Java | remote JDK 21 fetched by Bazel | outside tool evidence (Bazel-fetched) |
| Host dependency | `qemu-system-aarch64` on `PATH` (boot test) | not declared in evidence (issue #60); needs a runner capability (#20 item 3) |
| Extra toolchains | Kani (nightly rustc by hash via repo rule), Apalache, TLC jars by hash | Bazel-resolved; recorded only as lock/declaration facts, not closure-verified |
| CI | `check.yml`, `full-gate.yml` | to be replaced by the reusable platform workflow, in nga, by the owner's decision |
| Evidence | `evidence/EvidenceManifest.bzl`, mutation witnesses | needs a mapping to `dev-platform.result/v1` / app-release records |

## Constraints from the platform model (carried from the pilots)
- Exact-version pinning: nga pins release version + tree digest (+ installer pins out of band). No floating.
- A toolchain change is a new platform release; nga adopts it in two explicit steps (platform pin, then its own
  declaration).
- Environment evidence is never hermetic; nga's Bazel-fetched artifacts, the host linker and `qemu` stay on the
  stated limitations list.
- Certification is of nga's checks on a stated platform and profile, not of the release and not owner acceptance.

## Phases (each independently verifiable; none touches nga until phase 4 is decided)
1. **Platform prerequisites (public, this repository).**
   a. `rust-bazel-9` qualified by real execution on linux-x86_64 and darwin-arm64 (fixture
      `fixtures-real/rust-bazel-9`, negative cases) - required before any claim.
   b. Reconciliation of `versions = [...]` with `extra_target_triples` and edition 2024 in the Bazel adapter (check
      that declaration drift is still detected).
   c. Declared host requirements (issue #60) and a runner capability for qemu (issue #20 item 3): second concrete
      need after flight's tmux, so #20 item 3 is now justified.
2. **Dry run without modifying nga.** A read-only pilot job (like `pilot.yml` for flight) cannot check out private
   nga from this public repository. **Owner:** provide either a public minimal reproduction of nga's Bazel layout
   or run the platform's pilot tool from nga's own CI on a throwaway branch.
3. **Mapping design.** Map nga's evidence manifest and invariant map to platform records without weakening nga's
   own gate (nga keeps its gate; the platform's result is additional evidence).
4. **Adoption decision. Owner.** Whether to add `dev-platform.toml` and the reusable workflow to nga. This is a
   production migration and is outside anything the platform releases or milestones authorize.

## Runbook for phase 2 (owner decision; nothing here modifies nga)
`docs/consumer-integration.md` is the runbook: the Bazel-only profile `rust-bazel-9`, the consumer-owned pins, the reusable
workflow `consumer-pilot.yml` run as an additional non-required job from nga's own CI on a throwaway branch (so no private
checkout from this public repository is needed), the Bazel Rust toolchain proof (Bazel only, no Cargo), and the
independently verifiable evidence bundle. The public reference consumer for the same flow is `fixtures-real/rust-bazel-9`
(`pilot/consumers.json` `reference-bazel`). The infra pin starts as absent (hosted only) until the owner adopts one.

## Exit criteria for v0.2.0's part of this issue
Phase 1 complete (qualified profile, adapter drift tests, declared-requirement design) and this plan reviewed.
Phases 2 to 4 belong to the owner's schedule; the milestone does not depend on them.
