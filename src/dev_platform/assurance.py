"""General assurance evaluation over a read-only projection (prototype of draft ADR A; not ratified).

`evaluate` is a pure function of a validated `dev-platform.assurance-projection/v1` document. It reads
the execution outcomes and applicability the producer reports; it runs nothing, does not authenticate the
producer and does not establish that a declared input boundary is complete. Its verdict is informational: no
admission, certification, release or owner-acceptance obligation reads it.

Supported argument structure: conjunctive support (`form: all`), `depends_on` prerequisites, premises and a
review bound to the claim statement and argument digests. Any other support form, including the reserved
`any-of`, is reported `unsupported-form`, never reinterpreted.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TypeGuard

from .identity import BOUNDARIES
from .model import Outcome
from .records import canonical_digest

PROJECTION = "dev-platform.assurance-projection/v1"
EVALUATION = "dev-platform.assurance-evaluation/v1"
ARGUMENT_ENCODING = "dev-platform.assurance-argument/1"

OUTCOMES = tuple(o.value for o in Outcome)
APPLICABILITY = ("current", "stale", "unknown")
KINDS = ("proof", "test", "measurement", "analysis", "control")
PROVENANCE = ("observed", "measured", "declared", "inferred")
SUPPORTING_PROVENANCE = ("observed", "measured")  # a declared or inferred result never supports or refutes
PREMISE_CLASSES = ("assumed", "external-boundary", "review-obligation")
ARGUMENT = ("declared", "incomplete", "unknown")
CLOSURE_SCOPES = ("roots", "all-active")
CLAIM_STATES = ("established", "failed", "not-established")
VERDICTS = ("PASS", "INCOMPLETE", "FAILED", "UNDECLARED")
LIMITATIONS = (
    "evidence outcomes and applicability are reported by the producer and are not authenticated",
    "a declared input boundary is not shown to contain everything a check reads",
    "satisfies no admission, certification, release or owner-acceptance obligation",
)

_SHA = re.compile(r"^[0-9a-f]{64}$")
_TOP = (
    {"schema", "producer", "claims", "units", "premises"},
    {"subject", "scope", "producer_verdicts", "extensions"},
)
_CLAIM = (
    {"id", "statement_digest", "argument", "support"},
    {"statement", "depends_on", "premises", "review", "extensions"},
)
_REVIEW = ({"encoding", "statement_digest", "argument_digest"}, {"reviewer", "extensions"})
_UNIT = ({"id", "evidence"}, {"premises", "extensions"})
_ITEM = (
    {"id", "kind", "outcome", "provenance", "applicability", "boundary"},
    {"identity", "cause", "extensions"},
)
_PREMISE = ({"id", "statement_digest", "class"}, {"statement", "review", "extensions"})
_PREMISE_REVIEW = ({"statement_digest"}, {"reviewer", "extensions"})
_SCOPE = ({"closure"}, {"roots"})
_VERDICTS = (set(), {"claims", "closure"})


def _keys(d: object, spec: tuple[set, set], where: str, errs: list[str]) -> TypeGuard[dict]:
    if not isinstance(d, dict):
        errs.append(f"{where}: object required")
        return False
    required, optional = spec
    errs.extend(f"{where}.{k}: required" for k in sorted(required - set(d)))
    errs.extend(f"{where}.{k}: unknown field" for k in sorted(set(d) - required - optional))
    return True


def _str(v: object, where: str, errs: list[str], values: tuple[str, ...] | None = None) -> None:
    if not (isinstance(v, str) and v):
        errs.append(f"{where}: non-empty string required")
    elif values is not None and v not in values:
        errs.append(f"{where}: {v!r} is not one of {list(values)}")


def _sha(v: object, where: str, errs: list[str]) -> None:
    if not (isinstance(v, str) and _SHA.match(v)):
        errs.append(f"{where}: 64 lowercase hex characters required")


def _ids(v: object, where: str, errs: list[str]) -> None:
    if not (isinstance(v, list) and all(isinstance(x, str) and x for x in v)):
        errs.append(f"{where}: list of non-empty strings required")
    elif len(set(v)) != len(v):
        errs.append(f"{where}: duplicate entries")


def _unique(items: list, where: str, errs: list[str]) -> None:
    seen: set[str] = set()
    for i, x in enumerate(items):
        if isinstance(x, dict) and isinstance(x.get("id"), str):
            if x["id"] in seen:
                errs.append(f"{where}[{i}].id: duplicate {x['id']!r}")
            seen.add(x["id"])


def validate(doc: object) -> list[str]:
    """Structural problems; empty when `evaluate` may read the document. References are not checked here:
    an unresolved reference is evaluated (and reported) as not established."""
    if not isinstance(doc, dict):
        return ["projection: JSON object required"]
    if doc.get("schema") != PROJECTION:
        return [f"schema {doc.get('schema')!r} is not supported (this evaluator reads {PROJECTION} only)"]
    e: list[str] = []
    _keys(doc, _TOP, "projection", e)
    if not isinstance(doc.get("producer"), dict):
        e.append("producer: object required")
    else:  # producer metadata is carried, not interpreted; only its name is required
        _str(doc["producer"].get("name"), "producer.name", e)
    for k in ("subject", "extensions"):
        if k in doc and not isinstance(doc[k], dict):
            e.append(f"{k}: object required")
    if "scope" in doc and _keys(doc["scope"], _SCOPE, "scope", e):
        _str(doc["scope"].get("closure"), "scope.closure", e, CLOSURE_SCOPES)
        if "roots" in doc["scope"]:
            _ids(doc["scope"]["roots"], "scope.roots", e)
    for coll in ("claims", "units", "premises"):
        if not isinstance(doc.get(coll), list):
            e.append(f"{coll}: list required")
            doc_items: list = []
        else:
            doc_items = doc[coll]
        _unique(doc_items, coll, e)
        for i, x in enumerate(doc_items):
            {"claims": _claim, "units": _unit, "premises": _premise}[coll](x, f"{coll}[{i}]", e)
    pv = doc.get("producer_verdicts")
    if "producer_verdicts" in doc and _keys(pv, _VERDICTS, "producer_verdicts", e):
        if "claims" in pv:
            if not isinstance(pv["claims"], dict):
                e.append("producer_verdicts.claims: object required")
            else:
                for cid, st in pv["claims"].items():
                    _str(st, f"producer_verdicts.claims.{cid}", e, CLAIM_STATES)
        if "closure" in pv:
            _str(pv["closure"], "producer_verdicts.closure", e, VERDICTS)
    return e


def _claim(c: object, where: str, e: list[str]) -> None:
    if not _keys(c, _CLAIM, where, e):
        return
    _str(c.get("id"), f"{where}.id", e)
    _sha(c.get("statement_digest"), f"{where}.statement_digest", e)
    _str(c.get("argument"), f"{where}.argument", e, ARGUMENT)
    for k in ("depends_on", "premises"):
        if k in c:
            _ids(c[k], f"{where}.{k}", e)
    s = c.get("support")
    if not (isinstance(s, dict) and isinstance(s.get("form"), str) and s["form"]):
        e.append(f"{where}.support: object with a non-empty form required")
    elif s["form"] == "all" and _keys(s, ({"form", "units"}, set()), f"{where}.support", e):
        _ids(s["units"], f"{where}.support.units", e)
    # any other form is evaluated as `unsupported-form`; its contents are not interpreted
    if "review" in c and _keys(c["review"], _REVIEW, f"{where}.review", e):
        _str(c["review"].get("encoding"), f"{where}.review.encoding", e)
        _sha(c["review"].get("statement_digest"), f"{where}.review.statement_digest", e)
        _sha(c["review"].get("argument_digest"), f"{where}.review.argument_digest", e)


def _unit(u: object, where: str, e: list[str]) -> None:
    if not _keys(u, _UNIT, where, e):
        return
    _str(u.get("id"), f"{where}.id", e)
    if "premises" in u:
        _ids(u["premises"], f"{where}.premises", e)
    if not isinstance(u.get("evidence"), list):
        e.append(f"{where}.evidence: list required")
        return
    _unique(u["evidence"], f"{where}.evidence", e)
    for i, it in enumerate(u["evidence"]):
        w = f"{where}.evidence[{i}]"
        if not _keys(it, _ITEM, w, e):
            continue
        _str(it.get("id"), f"{w}.id", e)
        _str(it.get("kind"), f"{w}.kind", e, KINDS)
        _str(it.get("outcome"), f"{w}.outcome", e, OUTCOMES)
        _str(it.get("provenance"), f"{w}.provenance", e, PROVENANCE)
        _str(it.get("applicability"), f"{w}.applicability", e, APPLICABILITY)
        _str(it.get("boundary"), f"{w}.boundary", e, BOUNDARIES)
        if it.get("identity") is not None:
            _sha(it["identity"], f"{w}.identity", e)
        if "cause" in it:
            _str(it["cause"], f"{w}.cause", e)


def _premise(p: object, where: str, e: list[str]) -> None:
    if not _keys(p, _PREMISE, where, e):
        return
    _str(p.get("id"), f"{where}.id", e)
    _sha(p.get("statement_digest"), f"{where}.statement_digest", e)
    _str(p.get("class"), f"{where}.class", e, PREMISE_CLASSES)
    if "review" in p and _keys(p["review"], _PREMISE_REVIEW, f"{where}.review", e):
        _sha(p["review"].get("statement_digest"), f"{where}.review.statement_digest", e)


def argument_digest(claim: dict) -> str:
    """What a claim review is bound to besides the statement: argument marker, support, premises and
    prerequisites. List order is not significant."""
    s = dict(claim["support"])
    if s.get("form") == "all":
        s["units"] = sorted(s["units"])
    return canonical_digest(
        {
            "encoding": ARGUMENT_ENCODING,
            "argument": claim["argument"],
            "support": s,
            "premises": sorted(claim.get("premises", [])),
            "depends_on": sorted(claim.get("depends_on", [])),
        }
    )


def _item(it: dict) -> dict:
    app, reasons = it["applicability"], []
    if app == "current" and it["boundary"] == "unknown":  # ADR B §3: an unknown boundary is never current
        app, reasons = "unknown", ["boundary-unknown"]
    elif app == "current" and it.get("identity") is None:
        app, reasons = "unknown", ["identity-unknown"]
    elif app == "unknown":
        reasons = ["applicability-unknown"]
    elif app == "stale":
        reasons = [f"stale({it.get('cause', 'unspecified')})"]
    observed = it["provenance"] in SUPPORTING_PROVENANCE
    if it["outcome"] == "passed" and app == "current" and observed:
        state = "supports"
    elif it["outcome"] == "failed" and app == "current" and observed:
        state = "counterevidence"
    else:
        state = "does-not-support"
        if it["outcome"] != "passed":
            reasons.append(f"outcome-{it['outcome']}")
        if not observed:
            reasons.append(f"provenance-{it['provenance']}")
    out = {k: it[k] for k in ("id", "kind", "outcome", "provenance", "boundary")}
    return out | {"applicability": app, "identity": it.get("identity"), "state": state, "reasons": reasons}


def _unit_state(u: dict) -> dict:
    items = [_item(it) for it in sorted(u["evidence"], key=lambda x: x["id"])]
    if not items:
        state = "no-evidence"
    elif any(i["state"] == "counterevidence" for i in items):
        state = "failed"
    elif all(i["state"] == "supports" for i in items):
        state = "established"
    else:
        state = "not-established"
    return {"id": u["id"], "state": state, "premises": sorted(u.get("premises", [])), "evidence": items}


def _premise_state(p: dict) -> dict:
    r = p.get("review")
    if r is None:
        state = "unreviewed"
    elif r["statement_digest"] != p["statement_digest"]:
        state = "stale"
    else:
        state = "current"
    return {"id": p["id"], "class": p["class"], "state": state}


def _review_state(c: dict) -> tuple[str, str | None]:
    r = c.get("review")
    if r is None:
        return "absent", None
    if r["encoding"] != ARGUMENT_ENCODING:
        return "incompatible", f"encoding {r['encoding']!r} is not {ARGUMENT_ENCODING}"
    if r["statement_digest"] != c["statement_digest"]:
        return "stale", "statement"
    if r["argument_digest"] != argument_digest(c):
        return "stale", "argument"
    return "current", None


def _cyclic(claims: dict[str, dict]) -> set[str]:
    """Claims that reach themselves through `depends_on`. No resolution is defined: never established."""
    out = set()
    for start in claims:
        stack, seen = list(claims[start].get("depends_on", [])), set()
        while stack:
            n = stack.pop()
            if n == start:
                out.add(start)
                break
            if n in seen or n not in claims:
                continue
            seen.add(n)
            stack.extend(claims[n].get("depends_on", []))
    return out


def evaluate(doc: dict) -> dict:
    """Claim states and closure for a document `validate` accepted. Identical input, identical output."""
    claims = {c["id"]: c for c in doc["claims"]}
    units = {u["id"]: _unit_state(u) for u in doc["units"]}
    premises = {p["id"]: _premise_state(p) for p in doc["premises"]}

    own: dict[str, list[dict]] = {}
    failed: set[str] = set()
    for cid, c in claims.items():
        r: list[dict] = []
        if c["argument"] != "declared":
            r.append({"code": f"argument-{c['argument']}"})
        form = c["support"]["form"]
        support_units: list[str] = []
        if form != "all":
            r.append({"code": "unsupported-form", "form": form})
        elif not c["support"]["units"]:
            r.append({"code": "no-support"})
        else:
            support_units = sorted(c["support"]["units"])
        for u in support_units:
            st = units[u]["state"] if u in units else None
            if st is None:
                r.append({"code": "unresolved-unit", "unit": u})
            elif st == "failed":
                failed.add(cid)
                r.append({"code": "unit-failed", "unit": u})
            elif st != "established":
                r.append({"code": f"unit-{st}", "unit": u})
        for p in _premises_of(c, support_units, units):
            if p not in premises:
                r.append({"code": "unresolved-premise", "premise": p})
            elif premises[p]["state"] != "current":
                r.append({"code": "premise-unaccepted", "premise": p, "state": premises[p]["state"]})
        review, cause = _review_state(c)
        if review != "current":
            r.append({"code": f"review-{review}"} | ({"cause": cause} if cause else {}))
        r.extend(
            {"code": "unresolved-claim", "claim": d}
            for d in sorted(c.get("depends_on", []))
            if d not in claims
        )
        own[cid] = r

    established: set[str] = set()
    changed = True
    while changed:  # least fixpoint: a cycle never enters it
        changed = False
        for cid, c in claims.items():
            if cid not in established and not own[cid] and set(c.get("depends_on", [])) <= established:
                established.add(cid)
                changed = True
    cyclic = _cyclic(claims)

    out_claims = []
    for cid in sorted(claims):
        c, r = claims[cid], list(own[cid])
        if cid in cyclic:
            r.append({"code": "cyclic-dependency"})
        for d in sorted(c.get("depends_on", [])):
            if d in claims and d not in established:
                r.append(
                    {"code": "dependency-failed" if d in failed else "dependency-not-established", "claim": d}
                )
        state = "failed" if cid in failed else "established" if cid in established else "not-established"
        review, cause = _review_state(c)
        entry = {
            "id": cid,
            "state": state,
            "review": {"state": review} | ({"cause": cause} if cause else {}),
            "support": {"form": c["support"]["form"]}
            | ({"units": sorted(c["support"]["units"])} if c["support"]["form"] == "all" else {}),
            "depends_on": sorted(c.get("depends_on", [])),
            "reasons": r,
        }
        if state == "established":
            entry["basis"] = _basis([cid], claims, units)
        out_claims.append(entry)
    by_id = {c["id"]: c for c in out_claims}

    closure = _closure(doc.get("scope"), claims, by_id, units)
    consistency = _consistency(doc.get("producer_verdicts"), by_id, closure["recomputed_verdict"])
    if consistency["state"] == "projection-inconsistent" and closure["verdict"] == "PASS":
        closure["verdict"] = "INCOMPLETE"
        closure["blockers"].append({"code": "projection-inconsistent"})
    return {
        "schema": EVALUATION,
        "authority": "informational",
        "limitations": list(LIMITATIONS),
        "projection": {"digest": canonical_digest(doc), "producer": doc["producer"]["name"]},
        "closure": closure,
        "consistency": consistency,
        "claims": out_claims,
        "units": [units[u] for u in sorted(units)],
        "premises": [premises[p] for p in sorted(premises)],
    }


def _premises_of(c: dict, support_units: list[str], units: dict[str, dict]) -> list[str]:
    """A claim rests on its own premises and those of every unit supporting it."""
    ps = set(c.get("premises", []))
    for u in support_units:
        ps |= set(units[u]["premises"]) if u in units else set()
    return sorted(ps)


def _deps(roots: list[str], claims: dict[str, dict]) -> list[str]:
    seen, stack = set(), [r for r in roots if r in claims]
    while stack:
        n = stack.pop()
        if n not in seen:
            seen.add(n)
            stack.extend(d for d in claims[n].get("depends_on", []) if d in claims)
    return sorted(seen)


def _basis(cids: list[str], claims: dict[str, dict], units: dict[str, dict]) -> dict:
    """What established claims rest on: premises, and the evidence by kind, boundary and identity."""
    scope = _deps(cids, claims)
    premises, evidence = set(), []
    for cid in scope:
        su = sorted(claims[cid]["support"].get("units", []))
        premises |= set(_premises_of(claims[cid], su, units))
        for u in su:
            evidence += [(u, i["id"], i["kind"], i["boundary"], i["identity"]) for i in units[u]["evidence"]]
    evidence = sorted(set(evidence))
    return {
        "claims": scope,
        "premises": sorted(premises),
        "kinds": sorted({e[2] for e in evidence}),
        "boundaries": sorted({e[3] for e in evidence}),
        "evidence": [
            {"unit": u, "item": i, "kind": k, "boundary": b, "identity": d} for u, i, k, b, d in evidence
        ],
    }


def _closure(scope: dict | None, claims: dict[str, dict], by_id: dict[str, dict], units: dict) -> dict:
    blockers: list[dict] = []
    kind = scope.get("closure") if scope else None
    roots = sorted(scope.get("roots", [])) if scope else []
    if kind is None:
        blockers.append({"code": "scope-undeclared"})
    elif not claims:
        blockers.append({"code": "no-claims"})
    elif kind == "roots" and not roots:
        blockers.append({"code": "roots-empty"})
    if blockers:
        verdict, in_scope = "UNDECLARED", []
    else:
        in_scope = _deps(roots, claims) if kind == "roots" else sorted(claims)
        blockers += [{"code": "unresolved-root", "claim": r} for r in roots if r not in claims]
        for cid in in_scope:
            if by_id[cid]["state"] != "established":
                blockers += [{"claim": cid, "state": by_id[cid]["state"]} | r for r in by_id[cid]["reasons"]]
        if any(by_id[c]["state"] == "failed" for c in in_scope):
            verdict = "FAILED"
        elif blockers:
            verdict = "INCOMPLETE"
        else:
            verdict = "PASS"
    rec = {"scope": {"closure": kind, "roots": roots, "claims": in_scope}}
    rec |= {"verdict": verdict, "recomputed_verdict": verdict, "blockers": blockers}
    if verdict == "PASS":
        rec["basis"] = _basis(in_scope, claims, units)
    return rec


def _consistency(pv: dict | None, by_id: dict[str, dict], verdict: str) -> dict:
    if pv is None:
        return {"state": "not-compared", "disagreements": []}
    d = []
    if "claims" in pv:
        for cid in sorted(set(pv["claims"]) | set(by_id)):
            mine = by_id[cid]["state"] if cid in by_id else None
            theirs = pv["claims"].get(cid)
            if mine != theirs:
                d.append({"subject": f"claim:{cid}", "producer": theirs, "recomputed": mine})
    if "closure" in pv and pv["closure"] != verdict:
        d.append({"subject": "closure", "producer": pv["closure"], "recomputed": verdict})
    return {"state": "projection-inconsistent" if d else "consistent", "disagreements": d}


def load(path: Path) -> tuple[dict | None, list[str]]:
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        return None, [f"{path}: {ex}"]
    problems = validate(doc)
    return (None if problems else doc), problems


def render(rec: dict) -> str:
    c = rec["closure"]
    lines = [
        f"closure: {c['verdict']} (scope {c['scope']['closure'] or 'undeclared'}, "
        f"{len(c['scope']['claims'])} claims)",
        f"consistency: {rec['consistency']['state']}",
    ]
    for b in c["blockers"]:
        detail = " ".join(f"{k}={v}" for k, v in b.items() if k != "code")
        lines.append(f"  {b['code']}" + (f" {detail}" if detail else ""))
    for d in rec["consistency"]["disagreements"]:
        lines.append(f"  disagreement {d['subject']}: producer {d['producer']}, recomputed {d['recomputed']}")
    if c["verdict"] == "PASS":
        b = c["basis"]
        lines.append(
            f"  rests on premises {b['premises'] or '[]'}, boundaries {b['boundaries']}, kinds {b['kinds']}"
        )
    lines.append("informational only: " + "; ".join(rec["limitations"]))
    return "\n".join(lines)
