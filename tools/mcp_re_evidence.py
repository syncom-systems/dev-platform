#!/usr/bin/env python3
"""Bind one MCP-RE run's evidence records to a closure target's projection (E2 follow-up; informational).

Reads an extracted `verification-evidence-<run>-<attempt>` artifact (the directory `assurance-closure` was given as
`--evidence`) and one target's committed inputs (`tools/mcp_re_projection.py read`). It never runs MCP-RE, never
recomputes a fingerprint and never reads anything else.

A record becomes a v1 evidence item only for a (unit, lane) pair the target's `verification.toml` declares, which
is the set MCP-RE's `attest` consumes (`_evidence.required_lanes`). Outcome is the record's `result`. Applicability is
derived only by comparing the record's fingerprint with the unit fingerprint the closure record asserts
(`--applicability record-bound`; `attest` refuses on exactly that inequality) or left `unknown`
(`--applicability unknown`). The unit fingerprint is the record's assertion and is not recomputed here, so a
`current` item is current relative to that assertion only. Reviews, premises and arguments are `convert`'s,
unchanged.

  python3 tools/mcp_re_evidence.py --tree DIR --record FILE --target SHA --record-revision SHA \\
      --artifact DIR --artifact-name NAME --artifact-sha256 HEX --run-id ID --run-attempt N \\
      [--applicability record-bound|unknown] --out DIR
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("mcp_re_projection", ROOT / "tools" / "mcp_re_projection.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)

# Lane -> v1 kind. `mutation` (a probe turns a declared control red) and `structural` (a probe is refused by the
# declared compiler error) check that a control detects a fault; v1 has no closer kind. Kind never changes a
# v1 verdict; both are reported as approximate.
KIND = {
    "test": "test",
    "verus": "proof",
    "lean": "proof",
    "measured": "measurement",
    "mutation": "control",
    "structural": "control",
}
APPROXIMATE_KIND = ("mutation", "structural")
OUTCOME = {"pass": "passed", "fail": "failed"}
RECORD_KEYS = {"unit_id", "lane", "result", "fingerprint"}


def read_artifact(directory: Path) -> dict:
    """The bundle, every lane record and every file's digest. Malformed records are dropped and listed."""
    files, records, dropped = [], {}, []
    for p in sorted(x for x in directory.rglob("*") if x.is_file()):
        rel = p.relative_to(directory).as_posix()
        data = p.read_bytes()
        files.append({"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "git_blob": M.git_blob(data)})
        parts = rel.split("/")
        if len(parts) != 2 or not rel.endswith(".json") or parts[0] == "measured-artifacts":
            continue
        try:
            raw = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raw = None
        if (
            not isinstance(raw, dict)
            or not set(raw) >= RECORD_KEYS
            or raw["lane"] != parts[0]
            or f"{raw['unit_id']}.json" != parts[1]
        ):
            dropped.append(rel)
            continue
        records[(raw["lane"], raw["unit_id"])] = raw | {"_path": rel, "_sha256": files[-1]["sha256"]}
    bundle = None
    if (directory / "bundle.json").is_file():
        try:
            bundle = json.loads((directory / "bundle.json").read_bytes())
        except json.JSONDecodeError:
            bundle = None
    return {
        "bundle": bundle if isinstance(bundle, dict) else None,
        "records": records,
        "dropped": dropped,
        "files": files,
        "manifest_digest": M.mcp_digest(files),
    }


def declared_lanes(unit: dict) -> list[str]:
    """MCP-RE `_evidence.required_lanes`: every scheme of every declared evidence URI."""
    return sorted(
        {str(e).split("://", 1)[0] if "://" in str(e) else "<malformed>" for e in unit.get("evidence", [])}
    )


def bind(inp: dict, art: dict) -> dict:
    """Each declared (unit, lane) pair against the artifact, and the records no pair claims."""
    rec_unit = {r["unit"]: r["fingerprint"] for r in inp["record"].get("units", [])}
    pairs, claimed = [], set()
    for u in sorted(inp["policy"].get("unit", []), key=lambda x: x["id"]):
        lanes = declared_lanes(u)
        if not lanes:
            pairs.append({"unit": u["id"], "lane": None, "status": "no-declared-evidence"})
        for lane in lanes:
            r = art["records"].get((lane, u["id"]))
            claimed.add((lane, u["id"]))
            if r is None:
                status = "missing"
            elif rec_unit.get(u["id"]) is None:
                status = "no-recorded-fingerprint"
            elif r["fingerprint"] != rec_unit[u["id"]]:
                status = "fingerprint-differs"
            else:
                status = "fingerprint-matches"
            row = {"unit": u["id"], "lane": lane, "status": status}
            if r is not None:
                row["result"] = r["result"]
            pairs.append(row)
    counts: dict[str, int] = {}
    for p in pairs:
        key = f"{p['status']}/{p.get('result', '-')}"
        counts[key] = counts.get(key, 0) + 1
    unclaimed = sorted(f"{lane}/{unit}" for lane, unit in art["records"] if (lane, unit) not in claimed)
    return {"pairs": pairs, "counts": dict(sorted(counts.items())), "unclaimed_records": unclaimed}


def run_link(inp: dict, art: dict, run_id: str, attempt: str) -> dict:
    """Producer-reported run facts beside the record's run identity. Reported, never upgraded."""
    rec, b = inp["record"], art["bundle"] or {}
    run = rec.get("run", {})
    return {
        "record_run_id_matches": str(run.get("id")) == str(run_id),
        "record_run_attempt_matches": str(run.get("attempt")) == str(attempt),
        "record_event": run.get("event"),
        "bundle_present": art["bundle"] is not None,
        "bundle_aggregate": b.get("aggregate"),
        "bundle_scoped": "scope" in b,
        "bundle_lanes": b.get("lanes"),
        "bundle_policy_revision_matches_record": b.get("policy_revision") == rec.get("policy_revision"),
    }


def attach(inp: dict, art: dict, applicability: str) -> tuple[dict, list[dict]]:
    """`convert`'s projection with the artifact's records as evidence items, and the remaining mapping losses."""
    doc, losses = M.convert(inp)
    losses = [x for x in losses if x["concept"] != "evidence outcomes"]
    rec_unit = {r["unit"]: r["fingerprint"] for r in inp["record"].get("units", [])}
    policy = {u["id"]: u for u in inp["policy"].get("unit", [])}
    unknown_result, unknown_lane = [], []
    for unit in doc["units"]:
        items = []
        for lane in declared_lanes(policy[unit["id"]]):
            r = art["records"].get((lane, unit["id"]))
            if r is None:
                continue
            if r["result"] not in OUTCOME:
                unknown_result.append(f"{lane}/{unit['id']}")
                continue
            if lane not in KIND:
                unknown_lane.append(f"{lane}/{unit['id']}")
                continue
            item = {
                "id": f"{lane}:{unit['id']}",
                "kind": KIND[lane],
                "outcome": OUTCOME[r["result"]],
                "provenance": "measured" if lane == "measured" else "observed",
                "boundary": "declared",
                "identity": M.hexd(r["fingerprint"]),
            }
            if applicability == "record-bound" and rec_unit.get(unit["id"]) is not None:
                if r["fingerprint"] == rec_unit[unit["id"]]:
                    item["applicability"] = "current"
                else:
                    item["applicability"] = "stale"
                    item["cause"] = "fingerprint differs from the closure record's unit fingerprint"
            else:
                item["applicability"] = "unknown"
            item["extensions"] = {
                "mcp-re": {
                    "lane": lane,
                    "fingerprint": r["fingerprint"],
                    "detail": r.get("detail", ""),
                    "prover": r.get("prover"),
                    "record": r["_path"],
                    "record_sha256": r["_sha256"],
                    "applicability_basis": "closure-record unit fingerprint (asserted, not recomputed)"
                    if item["applicability"] != "unknown"
                    else None,
                }
            }
            items.append(item)
        unit["evidence"] = items
    doc["producer"]["converter"] += " + tools/mcp_re_evidence.py"
    doc["extensions"]["mcp-re"]["evidence_artifact"] = {
        "files": len(art["files"]),
        "manifest_digest": art["manifest_digest"],
        "bundle": art["bundle"],
        "applicability": applicability,
    }

    def loss(concept: str, treatment: str, subjects: list[str] | None = None) -> None:
        row: dict[str, object] = {"concept": concept, "treatment": treatment}
        if subjects is not None:
            row["subjects"] = sorted(subjects)
        losses.append(row)

    loss(
        "evidence applicability basis",
        "v1 `current` rests on the closure record's unit fingerprint, which is MCP-RE's assertion and is not "
        "recomputed (recomputation needs MCP-RE's fingerprinting over the source tree). `unknown` mode withholds it.",
    )
    loss(
        "evidence kind",
        "mutation and structural probes are mapped to `control`; v1 has no test-adequacy or negative-probe kind",
        [f"{lane}" for lane in APPROXIMATE_KIND],
    )
    loss(
        "evidence boundary",
        "`declared`: a unit's `paths` and fingerprint components are declared inputs, not shown complete",
    )
    loss(
        "run completeness",
        "bundle aggregate, lane verdicts and absence of `scope`, and the run event, have no v1 field; kept in "
        "`extensions` and not used to upgrade any item",
    )
    loss(
        "prover and lane detail",
        "prover pins and lane detail strings are kept per item in `extensions`; v1 has no field",
    )
    loss(
        "unit prerequisite propagation",
        "MCP-RE refuses a unit over a failed or unissuable prerequisite edge (`decide_issuance`); v1 has no "
        "unit edges, so a refusal it would make through an edge alone is not represented",
    )
    missing = [
        f"{p['lane']}/{p['unit']}"
        for p in bind(inp, art)["pairs"]
        if p["status"] in ("missing", "no-declared-evidence")
    ]
    if missing:
        loss("missing evidence record", "no item; the unit reports it", missing)
    unclaimed = bind(inp, art)["unclaimed_records"]
    if unclaimed:
        loss("record no unit declares", "not attached (attest consumes declared lanes only)", unclaimed)
    if unknown_result or unknown_lane:
        loss("unmappable record", "not attached", unknown_result + unknown_lane)
    if art["dropped"]:
        loss("malformed record", "dropped, as MCP-RE `load_records` drops it", art["dropped"])
    return doc, losses


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree", type=Path, required=True)
    ap.add_argument("--record", type=Path, required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--record-revision", required=True)
    ap.add_argument("--artifact", type=Path, required=True)
    ap.add_argument("--artifact-name", required=True)
    ap.add_argument("--artifact-sha256", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--run-attempt", required=True)
    ap.add_argument("--applicability", choices=("record-bound", "unknown"), default="record-bound")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    inp = M.read(a.tree, a.record, a.target, a.record_revision)
    art = read_artifact(a.artifact)
    doc, losses = attach(inp, art, a.applicability)
    doc["extensions"]["mcp-re"]["evidence_artifact"] |= {
        "name": a.artifact_name,
        "sha256": a.artifact_sha256,
        "run_id": a.run_id,
        "run_attempt": a.run_attempt,
    }
    binding = {
        "artifact": {
            "name": a.artifact_name,
            "sha256": a.artifact_sha256,
            "manifest_digest": art["manifest_digest"],
            "files": len(art["files"]),
            "records": len(art["records"]),
            "dropped": art["dropped"],
        },
        "run": run_link(inp, art, a.run_id, a.run_attempt),
        "binding": bind(inp, art),
    }
    a.out.mkdir(parents=True, exist_ok=True)
    for name, body in (("projection.json", doc), ("mapping-loss.json", losses), ("binding.json", binding)):
        (a.out / name).write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
