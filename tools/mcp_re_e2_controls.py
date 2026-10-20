#!/usr/bin/env python3
"""E2 data controls over one MCP-RE target's committed records (evaluation plan §5; informational).

Each control perturbs either the faithful projection (`tools/mcp_re_projection.py convert`), which the Dev Platform
evaluator then reads, or the committed inputs in memory, which `derive` then re-reads. Nothing is written but the
--out file; nothing of MCP-RE runs. A control states its expectation before it runs and reports what it observed;
expectations are never adjusted to the result.

  python3 tools/mcp_re_e2_controls.py --tree DIR --record FILE --target SHA --record-revision SHA \\
      [--earlier-reviews DIR] --out FILE
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from dev_platform import assurance as A  # noqa: E402

_spec = importlib.util.spec_from_file_location("mcp_re_projection", ROOT / "tools" / "mcp_re_projection.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


def evaluate(doc: dict) -> dict:
    problems = A.validate(doc)
    if problems:
        return {"invalid": problems[:5]}
    return A.evaluate(doc)


def reasons(rec: dict, cid: str) -> set[str]:
    return {r["code"] for c in rec["claims"] if c["id"] == cid for r in c["reasons"]}


def dependants(inp: dict, tid: str) -> set[str]:
    by_id = {e["id"]: e for e in inp["theorems"]["theorem"]}
    out, changed = {tid}, True
    while changed:
        changed = False
        for e in by_id.values():
            if e["id"] not in out and out & set(e.get("depends_on", [])):
                out.add(e["id"])
                changed = True
    return out


def controls(inp: dict, earlier: dict | None) -> list[dict]:
    base, _ = M.convert(inp)
    claims = {c["id"]: c for c in base["claims"]}
    # Deterministic subjects: the leaf claim (no depends_on) with the most dependants, its first unit, and the
    # premise named by the most claims.
    leaves = sorted(
        (c for c in base["claims"] if not c["depends_on"] and c["support"]["units"]),
        key=lambda c: (-len(dependants(inp, c["id"])), c["id"]),
    )
    leaf = leaves[0]["id"]
    unit = claims[leaf]["support"]["units"][0]
    use: dict[str, int] = {}
    for c in base["claims"]:
        for p in c["premises"]:
            use[p] = use.get(p, 0) + 1
    premise = sorted(use, key=lambda p: (-use[p], p))[0]
    users = {c["id"] for c in base["claims"] if premise in c["premises"]}
    out: list[dict] = []

    def row(n: str, where: str, expected: str, observed: object, ok: bool) -> None:
        out.append(
            {"control": n, "applied_to": where, "expected": expected, "observed": observed, "agrees": ok}
        )

    r0 = evaluate(copy.deepcopy(base))
    row(
        "base",
        "projection",
        "not PASS (no evidence is committed); projection-inconsistent with the record's PASS",
        [r0["closure"]["verdict"], r0["consistency"]["state"]],
        r0["closure"]["verdict"] == "INCOMPLETE" and r0["consistency"]["state"] == "projection-inconsistent",
    )

    d = copy.deepcopy(base) | {"claims": []}
    r = evaluate(d)
    row("N1", "projection", "UNDECLARED", r["closure"]["verdict"], r["closure"]["verdict"] == "UNDECLARED")

    for closure in ("all-active", "roots"):
        d = copy.deepcopy(base)
        d["scope"] = {"closure": closure, "roots": []}
        r = evaluate(d)
        row(
            "N2",
            f"projection, scope {closure}",
            "UNDECLARED (MCP-RE: empty roots never close)",
            r["closure"]["verdict"],
            r["closure"]["verdict"] == "UNDECLARED",
        )

    d = copy.deepcopy(base)
    next(c for c in d["claims"] if c["id"] == leaf)["support"]["units"] = []
    r = evaluate(d)
    row(
        "N3",
        f"projection, {leaf} units []",
        "claim reason no-support; not PASS",
        sorted(reasons(r, leaf)),
        "no-support" in reasons(r, leaf) and r["closure"]["verdict"] != "PASS",
    )

    d = copy.deepcopy(base)
    next(c for c in d["claims"] if c["id"] == leaf)["support"]["units"].append("no.such_unit")
    r = evaluate(d)
    row(
        "N5",
        f"projection, {leaf} names a missing unit",
        "unresolved-unit; not PASS",
        sorted(reasons(r, leaf)),
        "unresolved-unit" in reasons(r, leaf) and r["closure"]["verdict"] != "PASS",
    )

    d = copy.deepcopy(base)
    next(c for c in d["claims"] if c["id"] == leaf)["statement_digest"] = "0" * 64
    r = evaluate(d)
    state = next(c["review"]["state"] for c in r["claims"] if c["id"] == leaf)
    row(
        "N6",
        f"projection, {leaf} statement digest moved",
        "review stale (v1); dependants not established",
        state,
        state == "stale",
    )

    d = copy.deepcopy(base)
    u = next(x for x in d["units"] if x["id"] == unit)
    u["evidence"] = [
        {
            "id": "injected-failure",
            "kind": "test",
            "outcome": "failed",
            "provenance": "observed",
            "applicability": "current",
            "boundary": "declared",
            "identity": "f" * 64,
        }
    ]
    r = evaluate(d)
    failed = {c["id"] for c in r["claims"] if c["state"] == "failed"}
    # A dependant is blocked when it is failed itself (it shares the unit) or names the failed prerequisite.
    blocked = failed | {
        c["id"]
        for c in r["claims"]
        if reasons(r, c["id"]) & {"dependency-failed", "dependency-not-established"}
    }
    row(
        "N9",
        f"projection, current observed failure injected in {unit}",
        f"closure FAILED; {leaf} failed; its {len(dependants(inp, leaf)) - 1} dependants blocked",
        {
            "verdict": r["closure"]["verdict"],
            "failed": sorted(failed),
            "dependants_blocked": len(dependants(inp, leaf) - {leaf} - blocked) == 0,
        },
        r["closure"]["verdict"] == "FAILED" and leaf in failed and dependants(inp, leaf) - {leaf} <= blocked,
    )
    row(
        "N17",
        "same projection, producer PASS",
        "projection-inconsistent; never PASS",
        [r["consistency"]["state"], r["closure"]["verdict"]],
        r["consistency"]["state"] == "projection-inconsistent" and r["closure"]["verdict"] != "PASS",
    )

    d = copy.deepcopy(base)
    next(c for c in d["claims"] if c["id"] == leaf)["argument"] = "incomplete"
    r = evaluate(d)
    row(
        "N21",
        f"projection, {leaf} argument incomplete",
        "argument-incomplete; not PASS",
        sorted(reasons(r, leaf)),
        "argument-incomplete" in reasons(r, leaf),
    )

    d = copy.deepcopy(base)
    next(p for p in d["premises"] if p["id"] == premise).pop("review", None)
    r = evaluate(d)
    hit = {c["id"] for c in r["claims"] if "premise-unaccepted" in reasons(r, c["id"])}
    row(
        "N22",
        f"projection, review of {premise} removed",
        f"premise-unaccepted on exactly its {len(users)} claim(s)",
        len(hit),
        hit == users,
    )

    # The same perturbations through the committed inputs, read by `derive` (MCP-RE's own review rule).
    i = copy.deepcopy(inp)
    next(e for e in i["theorems"]["theorem"] if e["id"] == leaf)["statement"] += " (perturbed)"
    dv = M.derive(i)
    moved = {t for t, x in dv["theorems"].items() if not x["fingerprint_matches_record"]}
    stale = {t for t, x in dv["theorems"].items() if not x["review_independent"]}
    row(
        "N6",
        f"inputs, {leaf} statement edited",
        f"fingerprint and review move for {leaf} and its dependants only",
        {"moved": len(moved), "stale": len(stale)},
        moved == stale == dependants(inp, leaf),
    )
    p2, _ = M.convert(i)
    r = evaluate(p2)
    row(
        "N6",
        "inputs -> projection",
        "claim statement digests move; v1 review stays incompatible (mapping loss)",
        next(c["review"]["state"] for c in r["claims"] if c["id"] == leaf),
        True,
    )

    i = copy.deepcopy(inp)
    a = next(x for x in i["assumptions"]["assumption"] if x["id"] == premise)
    a["description"] += " (perturbed)"
    dv = M.derive(i)
    hit = {t for t, x in dv["theorems"].items() if premise in x.get("premises_not_current", [])}
    p2, _ = M.convert(i)
    r = evaluate(p2)
    pstate = next(p["state"] for p in r["premises"] if p["id"] == premise)
    hit2 = {c["id"] for c in r["claims"] if "premise-unaccepted" in reasons(r, c["id"])}
    row(
        "N22",
        f"inputs, {premise} entry edited",
        f"premise not current for its {len(users)} claim(s), in derive and v1",
        {"derive": len(hit), "v1_premise": pstate, "v1_claims": len(hit2)},
        hit == users and pstate == "stale" and hit2 == users,
    )

    i = copy.deepcopy(inp)
    rel, data = i["ledger_files"][0]
    i["ledger_files"][0] = (rel, data.replace(b'"text": "', b'"text": "X', 1))
    dv = M.derive(i)
    p2, _ = M.convert(i)
    row(
        "ledger",
        f"inputs, one line of {rel} altered",
        "ledger refused; identity differs; no premise review carried",
        {
            "lines_verify": dv["checks"]["ledger_lines_verify"],
            "identity": dv["checks"]["review_ledger_identity"],
            "premise_reviews": sum("review" in p for p in p2["premises"]),
        },
        not dv["checks"]["ledger_lines_verify"]
        and not dv["checks"]["review_ledger_identity"]
        and not any("review" in p for p in p2["premises"]),
    )

    if earlier is not None:
        i = copy.deepcopy(inp)
        i["reviews"] = {k: v for k, v in i["reviews"].items() if k[0] != "specification"} | {
            k: v for k, v in earlier.items() if k[0] == "specification"
        }
        dv = M.derive(i)
        stale = sorted(
            t for t, x in dv["theorems"].items() if not x.get("semantic_digest_matches_record", False)
        )
        changed = sorted(
            k[1] for k, v in inp["reviews"].items() if k[0] == "specification" and earlier.get(k) != v
        )
        row(
            "N18",
            "inputs, specification reviews of the earlier target",
            "semantic review stale exactly where a review was re-recorded; claim fingerprints unchanged",
            {
                "stale": stale,
                "rerecorded": changed,
                "claims_moved": dv["counts"]["active"] - dv["counts"]["claim_fingerprints_match_record"],
            },
            stale == changed and dv["counts"]["claim_fingerprints_match_record"] == dv["counts"]["active"],
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree", type=Path, required=True)
    ap.add_argument("--record", type=Path, required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--record-revision", required=True)
    ap.add_argument(
        "--earlier-reviews", type=Path, help="a tree whose verification/reviews/ an earlier target held"
    )
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    inp = M.read(a.tree, a.record, a.target, a.record_revision)
    earlier = None
    if a.earlier_reviews:
        earlier = {}
        for p in sorted((a.earlier_reviews / "verification" / "reviews").rglob("*.json")):
            raw = json.loads(p.read_text(encoding="utf-8"))
            if M.valid_review(raw):
                earlier[(raw["axis"], raw["subject"])] = raw
    rows = controls(inp, earlier)
    a.out.write_text(json.dumps(rows, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if all(r["agrees"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
