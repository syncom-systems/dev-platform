#!/usr/bin/env python3
"""E2 tooling: one MCP-RE target's committed records -> `dev-platform.assurance-projection/v1` (informational).

Evaluation plan E2 only (docs/assurance/evaluation-plan.md §8). Two steps over the same committed files, kept apart:

  convert  the projection: claims, units, premises, scope and the producer's closure verdict, as far as v1 carries
           them faithfully. What v1 cannot carry goes to the mapping-loss list, never into the projection: no
           evidence outcome, review or identity is invented, and nothing unknown becomes `current`.
  derive   an independent recomputation, from the same files, of the identities and review facts MCP-RE's closure
           rests on (theorem fingerprints, ledger identity, review and premise currency, the record's own digests),
           each compared with the closure record. It never feeds the projection.

Nothing here runs MCP-RE code, reaches the network or writes outside --out. The encodings re-implemented below are
MCP-RE's own (tools/verification/_fingerprint.py, _approvals.py, _closure_record.py, _review.py at the targets);
agreement with a recorded identity is a report about content identity, not an attestation.

  python3 tools/mcp_re_projection.py --tree DIR --record FILE --target SHA --record-revision SHA --out DIR

DIR holds the target revision's files at their repository paths; FILE is the closure record for that target.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

PROJECTION = "dev-platform.assurance-projection/v1"
REVIEW_ENCODING = "mcp-re.specification-review/1"  # foreign: v1 reports it `incompatible`, never current
PREMISE_CLASSES = ("assumed", "external-boundary", "review-obligation")
MODEL_REGISTRATION = "model-registration"  # MCP-RE drops these from every premise closure
RECORD_KEYS = {
    "schema_version",
    "kind",
    "subject",
    "verdict",
    "target",
    "run",
    "policy_revision",
    "review_ledger",
    "units",
    "units_digest",
    "theorems",
    "theorems_digest",
    "roots",
    "counts",
}
REVIEW_KEYS = {
    "axis",
    "subject",
    "reviewed_fingerprint",
    "components",
    "reviewer",
    "notes",
    "review_digest",
    "review_components",
}
LEDGER_REQUIRED = {"ruling", "approved_by", "approved", "sha256", "text", "source"}
ENTRY_SOURCE = re.compile(
    r'^verification/policy/(?:assumptions|theorems)\.toml \[\[(?:assumption|theorem)\]\] id = "((?:ASM|THM)-\d{4})"'
)


# ------------------------------------------------------------------ MCP-RE encodings (re-implemented, not run)


def mcp_digest(value: object) -> str:
    """`_fingerprint.canonical_digest`."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_digest(rows: list) -> str:
    """`_closure_record.canonical_digest` (ASCII-escaped, unlike `mcp_digest`)."""
    return (
        "sha256:"
        + hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    )


def theorem_fingerprint(entry: dict, by_id: dict[str, dict]) -> dict:
    """`_fingerprint.fingerprint_theorem`: claim, transitive dependency claims, review requirement."""

    def claim(e: dict) -> str:
        return mcp_digest({k: e[k] for k in ("statement", "security_consequence", "scope")})

    deps: dict[str, str] = {}
    stack, seen = list(entry.get("depends_on", [])), {entry["id"]}
    while stack:
        d = stack.pop()
        if d in seen or d not in by_id:
            continue
        seen.add(d)
        deps[d] = claim(by_id[d])
        stack.extend(by_id[d].get("depends_on", []))
    components = {
        "encoding_version": 1,
        "theorem_id": entry["id"],
        "theorem_claim": claim(entry),
        "theorem_dependencies": deps,
        "theorem_review_requirement": entry["review_requirement"],
    }
    return {"fingerprint": mcp_digest(components), "components": components}


def ledger_rows(files: list[tuple[str, bytes]]) -> list[dict]:
    """`_approvals.load_ledger`; raises ValueError where MCP-RE refuses the whole ledger."""
    rows = []
    for rel, data in files:
        for n, line in enumerate(data.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or not set(row) >= LEDGER_REQUIRED:
                raise ValueError(f"{rel}:{n}: missing required keys")
            if hashlib.sha256(str(row["text"]).encode()).hexdigest() != row["sha256"]:
                raise ValueError(f"{rel}:{n}: sha256 is not the digest of text")
            rows.append(row)
    return rows


def ledger_identity(files: list[tuple[str, bytes]]) -> str:
    """`_approvals.ledger_identity`."""
    return record_digest([{"file": rel, "sha256": hashlib.sha256(data).hexdigest()} for rel, data in files])


def entry_text(registry: str, subject: str) -> str | None:
    """`_approvals.entry_text`: the entry as an entry approval signs it."""
    table = "assumption" if subject.startswith("ASM-") else "theorem"
    for block in re.split(rf"(?m)^(?=\[\[{table}\]\])", registry):
        if re.search(rf'(?m)^id = "{re.escape(subject)}"$', block):
            lines = block.rstrip().split("\n")
            while lines and (not lines[-1].strip() or lines[-1].lstrip().startswith("#")):
                lines.pop()
            return "\n".join(lines).rstrip() + "\n"
    return None


def backed(subject: str, text: str | None, rows: list[dict], allow_ruling: bool) -> bool:
    """`_approvals.ledger_state`: an entry approval, if any exists, must sign the current text."""
    signed = [
        r for r in rows if (m := ENTRY_SOURCE.match(str(r.get("source", "")))) and m.group(1) == subject
    ]
    if signed:
        return text is not None and hashlib.sha256(text.encode()).hexdigest() in {r["sha256"] for r in signed}
    return allow_ruling


def valid_review(raw: object) -> bool:
    """`_review._valid`: a malformed record is dropped, never repaired."""
    if not isinstance(raw, dict) or set(raw) - REVIEW_KEYS:
        return False
    if not {"axis", "subject", "reviewed_fingerprint", "reviewer"} <= set(raw):
        return False
    prefix = {"specification": "THM-", "assumption": "ASM-"}.get(raw["axis"])
    if raw["axis"] not in ("specification", "assumption", "audit"):
        return False
    if not isinstance(raw["subject"], str) or (prefix and not raw["subject"].startswith(prefix)):
        return False
    if not (
        isinstance(raw["reviewed_fingerprint"], str) and raw["reviewed_fingerprint"].startswith("sha256:")
    ):
        return False
    if not (isinstance(raw["reviewer"], str) and raw["reviewer"].strip()):
        return False
    if "review_digest" in raw and not (
        isinstance(raw["review_digest"], str) and raw["review_digest"].startswith("sha256:")
    ):
        return False
    if "review_components" in raw and not isinstance(raw["review_components"], dict):
        return False
    return not (("review_digest" in raw or "review_components" in raw) and raw["axis"] != "specification")


def hexd(digest: str) -> str:
    return digest.removeprefix("sha256:")


# ------------------------------------------------------------------ inputs


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def read(tree: Path, record: Path, target: str, record_revision: str) -> dict:
    """Every input, with its path, revision and digests. Reads only these paths."""
    sources: list[dict] = []

    def load(path: Path, rel: str, revision: str) -> bytes:
        data = path.read_bytes()
        sources.append(
            {
                "path": rel,
                "revision": revision,
                "sha256": hashlib.sha256(data).hexdigest(),
                "git_blob": git_blob(data),
            }
        )
        return data

    def registry(name: str) -> tuple[dict, str]:
        rel = f"verification/policy/{name}.toml"
        text = load(tree / rel, rel, target).decode("utf-8")
        return tomllib.loads(text), text

    theorems, theorems_text = registry("theorems")
    assumptions, assumptions_text = registry("assumptions")
    policy, _ = registry("verification")
    reviews: dict[tuple[str, str], dict] = {}
    dropped: list[str] = []
    for p in sorted((tree / "verification" / "reviews").rglob("*.json")):
        rel = p.relative_to(tree).as_posix()
        try:
            raw = json.loads(load(p, rel, target))
        except json.JSONDecodeError:
            raw = None
        if valid_review(raw):
            reviews[(raw["axis"], raw["subject"])] = raw
        else:
            dropped.append(rel)
    ledger = [
        (p.relative_to(tree).as_posix(), p)
        for p in sorted((tree / "docs" / "security").glob("owner-approvals-*.jsonl"))
    ]
    ledger_files = [(rel, load(p, rel, target)) for rel, p in ledger]
    rec_rel = f"verification/closures/{target}.json"
    rec = json.loads(load(record, rec_rel, record_revision))
    return {
        "target": target,
        "theorems": theorems,
        "theorems_text": theorems_text,
        "assumptions": assumptions,
        "assumptions_text": assumptions_text,
        "policy": policy,
        "reviews": reviews,
        "dropped_reviews": dropped,
        "ledger_files": ledger_files,
        "record": rec,
        "sources": sorted(sources, key=lambda s: s["path"]),
    }


# ------------------------------------------------------------------ convert


def _ledger_or_none(inp: dict) -> list[dict] | None:
    try:
        return ledger_rows(inp["ledger_files"])
    except (ValueError, json.JSONDecodeError):
        return None


def convert(inp: dict) -> tuple[dict, list[dict]]:
    """The v1 projection and the mapping losses. Deterministic; reads only `inp`."""
    entries = inp["theorems"].get("theorem", [])
    by_id = {e["id"]: e for e in entries}
    active = sorted(e["id"] for e in entries if not e.get("replaced_by"))
    rec = inp["record"]
    rec_thm = {r["theorem"]: r for r in rec.get("theorems", [])}
    rec_unit = {r["unit"]: r["fingerprint"] for r in rec.get("units", [])}
    asm = {a["id"]: a for a in inp["assumptions"].get("assumption", [])}
    rows = _ledger_or_none(inp)
    losses: list[dict] = []

    def loss(concept: str, treatment: str, subjects: list[str] | None = None) -> None:
        row: dict[str, object] = {"concept": concept, "treatment": treatment}
        if subjects is not None:
            row["subjects"] = sorted(subjects)
        losses.append(row)

    claims, premise_ids = [], set()
    no_review, no_semantic, closure_unknown, undeclared_units = [], [], [], []
    for tid in active:
        e = by_id[tid]
        fp = theorem_fingerprint(e, by_id)
        spec = inp["reviews"].get(("specification", tid))
        reviewed_premises = (spec or {}).get("review_components", {}).get("premises")
        recorded = rec_thm.get(tid, {})
        # MCP-RE derives the premise closure from unit fingerprints (source analysis), which no committed file
        # holds; only a review record states it, as reviewed. It is the current closure only where MCP-RE's own
        # recorded review digest (which covers the premises) equals the reviewed one; otherwise it is unknown.
        known = isinstance(reviewed_premises, dict) and spec.get("review_digest") == recorded.get(
            "review_digest"
        )
        if not known:
            closure_unknown.append(tid)
        units = [str(u).removeprefix("unit://") for u in e.get("supported_by", [])]
        c = {
            "id": tid,
            "statement_digest": hexd(fp["fingerprint"]),
            "argument": "declared" if known else "unknown",
            "support": {"form": "all", "units": units},
            "depends_on": list(e.get("depends_on", [])),
            "premises": sorted(reviewed_premises) if known else [],
        }
        if spec is None:
            no_review.append(tid)
        elif "review_digest" not in spec:
            no_semantic.append(tid)
        else:
            c["review"] = {
                "encoding": REVIEW_ENCODING,
                "statement_digest": hexd(spec["reviewed_fingerprint"]),
                "argument_digest": hexd(spec["review_digest"]),
                "reviewer": spec["reviewer"],
            }
        c["extensions"] = {
            "mcp-re": {
                "fingerprint": fp["fingerprint"],
                "recorded_fingerprint": recorded.get("fingerprint"),
                "recorded_review_digest": recorded.get("review_digest"),
            }
        }
        premise_ids.update(c["premises"])
        undeclared_units += [u for u in units if u not in {x["id"] for x in inp["policy"].get("unit", [])}]
        claims.append(c)

    units = []
    for u in sorted(inp["policy"].get("unit", []), key=lambda x: x["id"]):
        units.append(
            {
                "id": u["id"],
                "evidence": [],
                "extensions": {
                    "mcp-re": {
                        "class": u.get("class"),
                        "evidence_class": u.get("evidence_class"),
                        "declared_evidence": list(u.get("evidence", [])),
                        "recorded_fingerprint": rec_unit.get(u["id"]),
                    }
                },
            }
        )

    premises, unmapped_class, missing_asm, unbacked = [], [], [], []
    for pid in sorted(premise_ids):
        a = asm.get(pid)
        if a is None:
            missing_asm.append(pid)
            continue
        if a.get("premise_class") not in PREMISE_CLASSES:
            unmapped_class.append(pid)
            continue
        digest = mcp_digest(a)
        p = {"id": pid, "statement_digest": hexd(digest), "class": a["premise_class"]}
        r = inp["reviews"].get(("assumption", pid))
        if (
            r is not None
            and rows is not None
            and backed(pid, entry_text(inp["assumptions_text"], pid), rows, False)
        ):
            p["review"] = {"statement_digest": hexd(r["reviewed_fingerprint"]), "reviewer": r["reviewer"]}
        elif r is not None:
            unbacked.append(pid)
        premises.append(p)

    loss(
        "evidence outcomes",
        "MCP-RE's per-unit evidence is the run's attestation store, which is not committed "
        "(the closure record lists unit fingerprints only). Every unit carries `evidence: []`; its declared "
        "evidence references are kept in `extensions` and no outcome is inferred from the record's PASS or counts.",
    )
    loss(
        "specification review binding",
        f"a review binds MCP-RE's theorem fingerprint and semantic review digest, "
        f"not v1's argument digest; it is carried under encoding {REVIEW_ENCODING!r}, which v1 reports "
        "`incompatible`. No v1 review is minted for it.",
    )
    loss(
        "semantic review components",
        "`supporting_semantics` (per-unit semantic fingerprint components) and stale "
        "causes have no v1 field; v1 binds unit ids only (docs/assurance-evaluation.md, Limits).",
    )
    loss(
        "owner-approval ledger backing",
        "v1 premise reviews have no backing field; an assumption review is carried "
        "only if the ledger backs its current entry text (MCP-RE's rule), otherwise the premise is unreviewed.",
        unbacked,
    )
    loss(
        "unit fingerprints and run identity",
        "full unit fingerprints (toolchain, lanes, policy), the run's event, "
        "evidence commit and completeness rule are kept in `extensions`; v1 derives no applicability from them.",
    )
    loss(
        "unit edges",
        "verification.toml `edge` rows (unit-to-unit proof/compile dependencies) have no v1 field.",
    )
    loss(
        "premise closure",
        "taken from the review record only where MCP-RE's recorded review digest equals the "
        "reviewed one; otherwise `argument: unknown`.",
        closure_unknown,
    )
    if no_review:
        loss("missing specification review", "claim carries no review", no_review)
    if no_semantic:
        loss(
            "review without semantic digest",
            "MCP-RE `NO_SEMANTIC_DIGEST`; claim carries no review",
            no_semantic,
        )
    if missing_asm or unmapped_class:
        loss(
            "unmappable premise", "not emitted; the claim reports it unresolved", missing_asm + unmapped_class
        )
    if undeclared_units:
        loss("undeclared supporting unit", "not emitted; the claim reports it unresolved", undeclared_units)
    if rows is None:
        loss(
            "owner-approval ledger",
            "the ledger does not verify (MCP-RE refuses it); no premise review is carried",
        )
    if inp["dropped_reviews"]:
        loss("malformed review record", "dropped, as MCP-RE drops it", inp["dropped_reviews"])

    doc = {
        "schema": PROJECTION,
        "producer": {
            "name": "mcp-re",
            "converter": "dev-platform tools/mcp_re_projection.py",
            "record_kind": rec.get("kind"),
            "policy_revision": rec.get("policy_revision"),
        },
        "subject": {
            "repository": "syncom-systems/mcp-re",
            "commit": inp["target"],
            "tree": rec.get("target", {}).get("tree"),
        },
        # MCP-RE's condition: every active theorem currently verified AND every declared root complete.
        "scope": {"closure": "all-active", "roots": list(inp["theorems"].get("root_theorems", []))},
        "claims": claims,
        "units": units,
        "premises": premises,
        "extensions": {
            "mcp-re": {
                "run": rec.get("run"),
                "review_ledger": rec.get("review_ledger"),
                "sources": inp["sources"],
            }
        },
    }
    if (
        rec.get("verdict") == "PASS"
    ):  # a record exists only for a PASS; MCP-RE's FAIL has no single v1 verdict
        doc["producer_verdicts"] = {"closure": "PASS"}
    return doc, losses


# ------------------------------------------------------------------ derive


def derive(inp: dict) -> dict:
    """Recompute from committed files what can be recomputed, and compare it with the closure record."""
    entries = inp["theorems"].get("theorem", [])
    by_id = {e["id"]: e for e in entries}
    active = sorted(e["id"] for e in entries if not e.get("replaced_by"))
    rec = inp["record"]
    rec_thm = {r["theorem"]: r for r in rec.get("theorems", [])}
    asm = {a["id"]: a for a in inp["assumptions"].get("assumption", [])}
    rows = _ledger_or_none(inp)
    units = {u["id"] for u in inp["policy"].get("unit", [])}
    checks: dict[str, object] = {}

    checks["record_keys"] = set(rec) == RECORD_KEYS
    checks["record_target"] = rec.get("target", {}).get("commit") == inp["target"]
    checks["record_units_digest"] = record_digest(rec.get("units", [])) == rec.get("units_digest")
    checks["record_theorems_digest"] = record_digest(rec.get("theorems", [])) == rec.get("theorems_digest")
    checks["policy_revision"] = inp["policy"].get("policy_revision") == rec.get("policy_revision")
    checks["unit_set"] = sorted(units) == [r["unit"] for r in rec.get("units", [])]
    checks["active_theorem_set"] = active == [r["theorem"] for r in rec.get("theorems", [])]
    checks["roots"] = list(inp["theorems"].get("root_theorems", [])) == rec.get("roots", {}).get("declared")
    checks["ledger_lines_verify"] = rows is not None
    checks["review_ledger_identity"] = ledger_identity(inp["ledger_files"]) == rec.get("review_ledger")

    per: dict[str, dict] = {}
    for tid in active:
        e, fp = by_id[tid], theorem_fingerprint(by_id[tid], by_id)
        spec = inp["reviews"].get(("specification", tid))
        r: dict[str, object] = {
            "fingerprint_matches_record": fp["fingerprint"] == rec_thm.get(tid, {}).get("fingerprint")
        }
        r["review_record"] = spec is not None
        if spec is not None:
            comps = {k: v for k, v in fp["components"].items() if k != "encoding_version"}
            recorded = spec.get("components") or {}
            r["claim_reviewed"] = spec["reviewed_fingerprint"] == fp["fingerprint"] and all(
                recorded.get(k) == v for k, v in comps.items()
            )
            r["claim_backed"] = rows is not None and backed(
                tid, entry_text(inp["theorems_text"], tid), rows, True
            )
            rc = spec.get("review_components")
            r["semantic_digest_present"] = isinstance(rc, dict) and "review_digest" in spec
            if r["semantic_digest_present"]:
                r["semantic_components_hash"] = mcp_digest(rc) == spec["review_digest"]
                r["semantic_claim_part"] = all(
                    rc.get(k) == fp["components"][k]
                    for k in ("theorem_claim", "theorem_dependencies", "theorem_review_requirement")
                )
                bad = []
                for pid, d in sorted(rc.get("premises", {}).items()):
                    a, ar = asm.get(pid), inp["reviews"].get(("assumption", pid))
                    ok = (
                        a is not None
                        and a.get("premise_class") != MODEL_REGISTRATION
                        and mcp_digest(a) == d
                        and ar is not None
                        and ar["reviewed_fingerprint"] == d
                        and rows is not None
                        and backed(pid, entry_text(inp["assumptions_text"], pid), rows, False)
                    )
                    if not ok:
                        bad.append(pid)
                r["premises"] = len(rc.get("premises", {}))
                r["premises_not_current"] = bad
                scoped = {
                    a["id"]
                    for a in asm.values()
                    if a.get("premise_class") != MODEL_REGISTRATION
                    and any(
                        f"unit://{str(u).removeprefix('unit://')}" in a.get("scope", [])
                        for u in e.get("supported_by", [])
                    )
                }
                r["unit_scoped_premises_missing"] = sorted(scoped - set(rc.get("premises", {})))
                # The record's review digest is MCP-RE's derivation at the target; its supporting_semantics part
                # needs unit fingerprints over the source tree, which this step does not compute.
                r["semantic_digest_matches_record"] = spec["review_digest"] == rec_thm.get(tid, {}).get(
                    "review_digest"
                )
        r["review_independent"] = bool(
            spec is not None
            and r.get("claim_reviewed")
            and r.get("claim_backed")
            and r.get("semantic_digest_present")
            and r.get("semantic_components_hash")
            and r.get("semantic_claim_part")
            and not r.get("premises_not_current")
            and not r.get("unit_scoped_premises_missing")
        )
        r["review_current_given_record"] = bool(
            r["review_independent"] and r.get("semantic_digest_matches_record")
        )
        per[tid] = r

    # Structure the closure fixpoint and root walk read.
    unresolved = sorted({d for t in active for d in by_id[t].get("depends_on", []) if d not in by_id})
    state: dict[str, int] = {}
    cyclic: set[str] = set()

    def visit(t: str) -> None:
        state[t] = 1
        for d in by_id[t].get("depends_on", []):
            if d in by_id and state.get(d) == 1:
                cyclic.add(t)
            elif d in by_id and d not in state:
                visit(d)
        state[t] = 2

    for t in active:
        if t not in state:
            visit(t)

    def closure(t: str) -> set[str]:
        out, stack = set(), [t]
        while stack:
            n = stack.pop()
            if n in out or n not in by_id:
                continue
            out.add(n)
            stack.extend(by_id[n].get("depends_on", []))
        return out

    roots = list(inp["theorems"].get("root_theorems", []))
    root_cover = set().union(*(closure(r) for r in roots)) if roots else set()
    declared_evidence = sum(len(u.get("evidence", [])) for u in inp["policy"].get("unit", []))
    counts = {
        "active": len(active),
        "claim_fingerprints_match_record": sum(r["fingerprint_matches_record"] for r in per.values()),
        "review_independent": sum(r["review_independent"] for r in per.values()),
        "review_current_given_record": sum(r["review_current_given_record"] for r in per.values()),
        "evidence_established": None,  # not derivable: no attestation is committed
        "currently_verified": None,
        "roots_established": None,
    }
    return {
        "target": inp["target"],
        "checks": checks,
        "counts": counts,
        "recorded_counts": rec.get("counts"),
        "structure": {
            "unresolved_dependencies": unresolved,
            "cyclic": sorted(cyclic),
            "roots": roots,
            "roots_active": all(r in active for r in roots),
            "root_closure_size": len(root_cover),
            "active_outside_root_closure": sorted(set(active) - root_cover),
            "units": len(units),
            "declared_evidence_references": declared_evidence,
        },
        "theorems": per,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tree", type=Path, required=True)
    ap.add_argument("--record", type=Path, required=True)
    ap.add_argument("--target", required=True)
    ap.add_argument("--record-revision", required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    inp = read(a.tree, a.record, a.target, a.record_revision)
    projection, losses = convert(inp)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "projection.json").write_text(
        json.dumps(projection, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    (a.out / "mapping-loss.json").write_text(
        json.dumps(losses, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    (a.out / "derivation.json").write_text(
        json.dumps(derive(inp), indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
