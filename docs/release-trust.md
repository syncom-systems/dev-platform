# Release trust, bootstrap and self-release

Normative decision: [ADR 0014](adr/0014-release-trust-bootstrap-and-execution.md).

## Verify-then-execute (implemented)
1. Launcher reads the consumer pin.
2. It snapshots `<store>/<version>` into a fresh `0700` temp dir, hashing the exact bytes written.
3. If the digest differs from the pin: abort (exit 3), delete the snapshot.
4. It runs the child from the snapshot (`PYTHONPATH`, no bytecode writes); the child re-hashes the
   tree it runs from and refuses a mismatch.
5. The snapshot is deleted afterwards. Residual risk: a same-user attacker can modify the running
   snapshot (it is writable by its owner); the threat model excludes same-user compromise.

## Trust roots and bootstrap (designed)
| Question | Trust root |
|---|---|
| Is this the release my repo pinned? | digest committed in the consumer repo (reviewed diff) |
| Was this release built by the project's workflow from that source? | Sigstore attestation, checked with `gh attestation verify <archive> --repo syncom-systems/dev-platform` using a verifier **not shipped inside the release** |
| Can a release be substituted? | write-once store; digest pin; protected tags; required review on `release.yml` |

Fresh machine: obtain the archive, verify the attestation with the independent verifier, check the
archive digest, unpack to the store (never executing release code first), then run normally.

## Self-release
A result produced by a release about itself (`mode = self`) is never certifiable. Release N is
accepted when (a) the workflow attested it at a protected tag, and (b) pinned release N-1 verified it
by running the full stage over N's source. The first release has no N-1; its acceptance is an owner
action (verify the attestation, pin the digest) and must be recorded as such. **No release has been
built, attested or accepted yet.**
