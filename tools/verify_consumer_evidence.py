#!/usr/bin/env python3
"""Independently check a consumer's execution evidence against the consumer's own pins (ADR 0021).

Imports nothing from `dev_platform`. Inputs: the result record (`dev-platform.result/v1`) produced by
`dev-platform check --stage full --result`, the consumer's `dev-platform.toml` (the exact pins the consumer owns:
platform version + tree digest + toolchain profile, and the `[infra]` configuration pin), and optionally the
`prove-bazel-rust` record. It answers: did this execution use the pinned platform release, a conformant and
certifiable toolchain environment, the pinned infrastructure configuration, and (for Bazel consumers) a Bazel-provided
Rust toolchain at the declared version? It cannot establish that the record was not fabricated: pair it with a
signature/attestation over the files (docs/consumer-integration.md).

Exit status: 0 consistent, 1 inconsistent, 2 usage/unreadable input. "Consistent" means the record agrees with
the consumer's pins; it is not a finding that the execution was trustworthy (see NOT_ESTABLISHED).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path

SCHEMA = "dev-platform.consumer-evidence-verification/v1"
NOT_ESTABLISHED = [
    "that the consumer job executed honestly or was not subverted (it writes the record it is judged by)",
    "that the record was not fabricated (attest the files)",
    "current authorization for private infrastructure: the provider and the runner groups decide that per run; the "
    "infra block records only which configuration release and digest were pinned and resolved",
    "that the consumer's own build, test and security gates passed or are unnecessary",
]
RESULT_SCHEMA = "dev-platform.result/v1"
PROOF_SCHEMA = "dev-platform.bazel-rust-proof/v1"


class Checks:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, cid: str, ok: bool, detail: str = "") -> bool:
        self.items.append({"id": cid, "status": "passed" if ok else "failed", "detail": detail})
        return ok

    @property
    def ok(self) -> bool:
        return bool(self.items) and all(c["status"] == "passed" for c in self.items)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify(
    result: dict,
    config: dict,
    proof: dict | None = None,
    *,
    revision: str | None = None,
    require_bazel_proof: bool = False,
    allow_uncertified: bool = False,
) -> dict:
    c = Checks()
    plat = config.get("platform") or {}
    pin_v, pin_t, pin_p = plat.get("version"), plat.get("sha256"), plat.get("profile")
    c.add(
        "config-pins-platform",
        bool(pin_v and pin_t and pin_p) and not plat.get("self_hosted"),
        "dev-platform.toml pins version, tree sha256 and profile (self-hosted results are not consumer evidence)",
    )
    c.add("result-schema", result.get("schema") == RESULT_SCHEMA, str(result.get("schema")))
    p = result.get("platform") or {}
    c.add("platform-pinned", p.get("mode") == "pinned", f"mode {p.get('mode')}")
    c.add("platform-version", p.get("pinned_version") == pin_v, f"{p.get('pinned_version')} vs pin {pin_v}")
    c.add("platform-tree-digest", p.get("digest") == pin_t, f"{p.get('digest')} vs pin {pin_t}")
    env = result.get("environment") or {}
    rel = env.get("release") or {}
    c.add(
        "release-identity",
        rel.get("version") == pin_v and rel.get("tree_digest") == pin_t,
        f"{rel.get('version')} {rel.get('tree_digest')}",
    )
    c.add("toolchain-profile", env.get("profile") == pin_p, f"{env.get('profile')} vs pin {pin_p}")
    c.add("environment-conformant", env.get("conformant") is True, "every declared tool matched the release")
    c.add(
        "environment-certifiable",
        env.get("assurance") == "certifiable",
        f"assurance {env.get('assurance')}; weak: {env.get('weak_tools')}",
    )
    c.add(
        "executed-full-stage",
        result.get("executed") is True and result.get("stage") == "full",
        f"executed={result.get('executed')} stage={result.get('stage')}",
    )
    if revision is not None:
        c.add("revision", result.get("revision") == revision, f"{result.get('revision')} vs {revision}")
    cert = result.get("certification") or {}
    if allow_uncertified:
        c.add(
            "checks-passed",
            not (result.get("unsatisfied_obligations") or []),
            str(result.get("unsatisfied_obligations")),
        )
    else:
        c.add("certified", cert.get("certified") is True, "; ".join(cert.get("blockers") or []))

    pin = config.get("infra")
    infra = result.get("infra")
    if pin:
        ok = bool(infra) and infra.get("status") == "resolved"
        c.add("infra-resolved", ok, f"{(infra or {}).get('status')}: {(infra or {}).get('reasons')}")
        got = (infra or {}).get("pinned") or {}
        c.add(
            "infra-pin-matches-config",
            got == {k: pin.get(k) for k in ("provider", "config_release", "config_digest")},
            f"recorded {got} vs config {pin}",
        )
        res = (infra or {}).get("resolved") or {}
        c.add(
            "infra-resolved-equals-pin",
            res == {"version": pin.get("config_release"), "digest": pin.get("config_digest")},
            f"resolved {res}",
        )
        c.add(
            "infra-contract",
            (infra or {}).get("contract") == "dev-platform.infra/v1",
            str((infra or {}).get("contract")),
        )
    else:
        c.add(
            "infra-not-pinned-hosted-only",
            infra is None or infra.get("status") == "hosted-only",
            f"no [infra] pin in config but result infra is {(infra or {}).get('status')}",
        )

    if require_bazel_proof or proof is not None:
        pr = proof or {}
        c.add("bazel-proof-schema", pr.get("schema") == PROOF_SCHEMA, str(pr.get("schema")))
        c.add("bazel-proof-ok", pr.get("ok") is True, "; ".join(pr.get("problems") or ["no proof supplied"]))
        declared, observed = pr.get("declared_versions") or [], pr.get("observed") or []
        c.add(
            "bazel-rust-version",
            len(declared) == 1 and observed == declared,
            f"declared {declared} observed {observed}",
        )
        c.add(
            "bazel-no-host-tool",
            (pr.get("host_decoy") or {}).get("invoked") is False,
            str(pr.get("host_decoy")),
        )
        c.add(
            "bazel-toolchain-external",
            bool(pr.get("rustc")) and all(r.get("bazel_external_repo") for r in pr["rustc"]),
            "every Rustc action names a Bazel external-repository rustc",
        )
    return {
        "schema": SCHEMA,
        "verdict": "consistent" if c.ok else "inconsistent",
        "not_established": NOT_ESTABLISHED,
        "checks": c.items,
        "claims": "the record is consistent with the consumer's pins; it does not prove the record was not fabricated "
        "(attest the files)",
    }


def _load(p: Path, what: str):
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"cannot read {what} {p}: {e}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--result", type=Path, required=True)
    ap.add_argument(
        "--config", type=Path, required=True, help="the consumer's dev-platform.toml (its own pins)"
    )
    ap.add_argument("--bazel-proof", type=Path)
    ap.add_argument("--require-bazel-proof", action="store_true")
    ap.add_argument("--revision", help="expected consumer revision")
    ap.add_argument(
        "--allow-uncertified",
        action="store_true",
        help="accept a result whose checks passed but is not certifiable (diagnostic only)",
    )
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    try:
        config = tomllib.loads(a.config.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        sys.exit(f"cannot read config {a.config}: {e}")
    doc = verify(
        _load(a.result, "result"),
        config,
        _load(a.bazel_proof, "proof") if a.bazel_proof else None,
        revision=a.revision,
        require_bazel_proof=a.require_bazel_proof,
        allow_uncertified=a.allow_uncertified,
    )
    doc["evidence"] = {a.result.name: sha256_file(a.result), "dev-platform.toml": sha256_file(a.config)}
    if a.bazel_proof:
        doc["evidence"][a.bazel_proof.name] = sha256_file(a.bazel_proof)
    for ck in doc["checks"]:
        print(
            f"{ck['status'].upper():7} {ck['id']}"
            + (f"  ({ck['detail']})" if ck["status"] == "failed" else "")
        )
    print(
        f"consumer evidence: {doc['verdict']} with the consumer's pins (consistency only; see not_established)"
    )
    if a.out:
        a.out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    return 0 if doc["verdict"] == "consistent" else 1


if __name__ == "__main__":
    sys.exit(main())
