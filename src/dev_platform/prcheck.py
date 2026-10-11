"""Static pull-request workflow checker (issue #48, ADR 0018).

It evaluates workflow files (the resulting head contents) against the *supplied* `dev-platform.infra/v1`
profile and never decides organization policy itself. Three outputs that are never collapsed:
  policy_violations  deterministic breach of the supplied policy                      -> failed
  incomplete         something could not be resolved; no conclusion for that item     -> unavailable
  risk_indicators    heuristic findings; advisory only, never change admission
It reads text only; it never executes PR content. Empty findings mean "no findings", not "safe".
"""

from __future__ import annotations

import fnmatch
import re

from . import runners

PR_REACHABLE = ("pull_request", "pull_request_target", "workflow_run")
HOSTED_LABELS = ("ubuntu-*", "macos-*", "windows-*")
DEFAULT_ADMISSION = {"forbidden_triggers": [], "protected_environments": []}


class Unsupported(Exception):
    """The workflow uses YAML this subset parser does not interpret; the caller reports `incomplete`."""


# ---------------------------------------------------------------- minimal YAML subset


def _strip_comment(line: str) -> str:
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _scalar(tok: str):
    tok = tok.strip()
    if tok[:1] in "&*!" or tok.startswith("<<") or tok == "|" or tok == ">":
        raise Unsupported(f"unsupported scalar {tok!r}")
    if tok[:1] in "'\"":
        if len(tok) < 2 or tok[-1] != tok[0]:
            raise Unsupported(f"unterminated quote {tok!r}")
        return tok[1:-1]
    if tok.startswith("["):
        if not tok.endswith("]"):
            raise Unsupported("multi-line flow sequence")
        inner = tok[1:-1].strip()
        return [_scalar(x) for x in _split_flow(inner)] if inner else []
    if tok.startswith("{"):
        if not tok.endswith("}"):
            raise Unsupported("multi-line flow mapping")
        inner = tok[1:-1].strip()
        d = {}
        for part in _split_flow(inner) if inner else []:
            k, sep, v = part.partition(":")
            if not sep:
                raise Unsupported(f"flow mapping entry {part!r}")
            d[_scalar(k)] = _scalar(v)
        return d
    return tok


def _split_flow(s: str) -> list[str]:
    parts, depth, cur, q = [], 0, [], None
    for ch in s:
        if q:
            q = None if ch == q else q
        elif ch in "'\"":
            q = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        if ch == "," and depth == 0 and not q:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def parse_yaml(text: str):
    lines = []
    for raw in text.splitlines():
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise Unsupported("tab indentation")
        s = _strip_comment(raw)
        if not s.strip():
            lines.append(None)
        elif s.strip() == "---" and not any(x for x in lines):
            continue
        else:
            lines.append((len(s) - len(s.lstrip()), s.strip()))
    rows = [(i, ln) for i, ln in enumerate(lines) if ln]
    pos = [0]

    def block(indent: int):
        if pos[0] >= len(rows):
            return None
        _, (ind, content) = rows[pos[0]]
        if content.startswith("- ") or content == "-":
            return seq(ind)
        return mapping(ind)

    def value_after_colon(rest: str, indent: int):
        rest = rest.strip()
        if rest in ("|", ">", "|-", ">-", "|+", ">+"):
            while pos[0] < len(rows) and rows[pos[0]][1][0] > indent:
                pos[0] += 1
            return "<block-scalar>"
        if rest:
            return _scalar(rest)
        if pos[0] < len(rows) and (
            rows[pos[0]][1][0] > indent
            or (rows[pos[0]][1][0] == indent and rows[pos[0]][1][1].startswith("- "))
        ):
            return block(indent)  # fmt: skip
        return None

    def mapping(indent: int):
        d: dict = {}
        while pos[0] < len(rows):
            _, (ind, content) = rows[pos[0]]
            if ind < indent:
                break
            if ind > indent:
                raise Unsupported(f"unexpected indentation at {content!r}")
            if content.startswith("- "):
                break
            m = re.match(r"""^("[^"]*"|'[^']*'|[^\s:'"][^:]*?)\s*:(?:\s+(.*))?$""", content)
            if not m:
                raise Unsupported(f"unparsed line {content!r}")
            key = m.group(1).strip("\"'")
            if key in d or key == "<<":
                raise Unsupported(f"duplicate or merge key {key!r}")
            pos[0] += 1
            d[key] = value_after_colon(m.group(2) or "", indent)
        return d

    def seq(indent: int):
        out: list = []
        while pos[0] < len(rows):
            _, (ind, content) = rows[pos[0]]
            if ind != indent or not (content.startswith("- ") or content == "-"):
                break
            item = content[1:].strip()
            if item and re.match(r"""^("[^"]*"|'[^']*'|[^\s:'"\[{][^:]*?)\s*:(\s|$)""", item):
                # inline mapping start: rewrite as a nested mapping at the item's column
                col = ind + (len(content) - len(item))
                rows[pos[0]] = (rows[pos[0]][0], (col, item))
                out.append(mapping(col))
            elif item:
                pos[0] += 1
                out.append(_scalar(item))
            else:
                pos[0] += 1
                out.append(block(indent) if pos[0] < len(rows) and rows[pos[0]][1][0] > indent else None)
        return out

    if not rows:
        return None
    result = block(rows[0][1][0])
    if pos[0] != len(rows):
        raise Unsupported(f"unparsed content near {rows[pos[0]][1][1]!r}")
    return result


# ---------------------------------------------------------------- checking


def _triggers(doc: dict) -> list[str]:
    on = doc.get("on", doc.get(True))
    if on is None:
        raise Unsupported("no `on:` triggers")
    if isinstance(on, str):
        return [on]
    if isinstance(on, list):
        return [str(x) for x in on]
    if isinstance(on, dict):
        return list(on)
    raise Unsupported("unrecognized `on:` shape")


def _allowed_label_sets(profile_runners: list[dict]) -> list[set[str]]:
    return [set(r["labels"]) for r in profile_runners if r.get("trust") == "public"]


def _runs_on_allowed(labels: list[str], public_sets: list[set[str]]) -> bool:
    if (
        "self-hosted" not in labels
        and len(labels) == 1
        and any(fnmatch.fnmatch(labels[0], g) for g in HOSTED_LABELS)
    ):
        return True
    return any(set(labels) <= s for s in public_sets)


def _resolve_runs_on(job: dict, expr_ok: bool = True) -> list[list[str]]:
    ro = job.get("runs-on")
    if ro is None:
        raise Unsupported("job has no runs-on (reusable workflow call?)")
    if isinstance(ro, dict):
        raise Unsupported("runs-on group/labels mapping")
    values = [ro] if isinstance(ro, str) else ro
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise Unsupported("runs-on shape")
    if len(values) == 1:
        m = re.fullmatch(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}", values[0])
        if m:
            matrix = ((job.get("strategy") or {}).get("matrix")) or {}
            if not isinstance(matrix, dict):
                raise Unsupported("matrix is not a mapping")
            key = m.group(1)
            opts = matrix.get(key, [])
            inc = matrix.get("include", [])
            if not isinstance(opts, list) or not isinstance(inc, list):
                raise Unsupported(f"matrix.{key} is not a plain list")
            # `include` can only add combinations and `exclude` only removes them: the union is a superset
            opts = opts + [i[key] for i in inc if isinstance(i, dict) and key in i]
            if not opts:
                raise Unsupported(f"matrix.{key} has no values")
            if any(not isinstance(o, str) or "${{" in o for o in opts):
                raise Unsupported("matrix value is not a plain string")
            return [[str(o)] for o in opts]
    if any("${{" in v for v in values):
        raise Unsupported("runs-on is an expression")
    return [values]


def check_workflow(path: str, text: str, profile_runners: list[dict], admission: dict) -> dict:
    out = {"policy_violations": [], "incomplete": [], "risk_indicators": []}

    def inc(msg):
        out["incomplete"].append({"file": path, "detail": msg})

    try:
        doc = parse_yaml(text)
        if not isinstance(doc, dict):
            raise Unsupported("workflow is not a mapping")
        trig = _triggers(doc)
    except Unsupported as e:
        inc(str(e))
        return out
    reachable = [t for t in trig if t in PR_REACHABLE]
    for t in trig:
        if t in admission["forbidden_triggers"]:
            out["policy_violations"].append({"file": path, "rule": "forbidden-trigger", "detail": t})
    if "pull_request_target" in trig:
        out["risk_indicators"].append(
            {
                "file": path,
                "indicator": "pull_request_target",
                "detail": "runs with base-repository privileges on untrusted events",
            }
        )
        if re.search(r"github\.event\.pull_request\.head\.(sha|ref)|github\.head_ref", text):
            out["risk_indicators"].append(
                {
                    "file": path,
                    "indicator": "pr-head-referenced-under-pull_request_target",
                    "detail": "heuristic: workflow references the PR head",
                }
            )
    heuristics = (
        (r"base64\s+-d", "base64-decode"),
        (r"(curl|wget)[^\n|]*\|\s*(sudo\s+)?(ba)?sh", "pipe-to-shell"),
        (r"secrets\.", "secrets-reference"),
    )
    for pat, name in heuristics:
        if re.search(pat, text):
            out["risk_indicators"].append(
                {"file": path, "indicator": name, "detail": "heuristic keyword match"}
            )
    if not reachable:
        return out  # not reachable from pull-request events: runner rules do not apply
    public_sets = _allowed_label_sets(profile_runners)
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        inc("jobs is not a mapping")
        return out
    for name, job in jobs.items():
        if not isinstance(job, dict):
            inc(f"job {name}: not a mapping")
            continue
        if "uses" in job and "runs-on" not in job:
            if isinstance(job["uses"], str) and job["uses"].startswith("./"):
                continue  # local reusable workflow: checked as its own file when supplied
            inc(f"job {name}: external reusable workflow {job['uses']!r} is not visible")
            continue
        try:
            sets = _resolve_runs_on(job)
        except Unsupported as e:
            inc(f"job {name}: {e}")
            continue
        env = job.get("environment")
        env_name = env.get("name") if isinstance(env, dict) else env
        for labels in sets:
            if _runs_on_allowed(labels, public_sets):
                continue
            if (
                isinstance(env_name, str)
                and "${{" not in env_name
                and env_name in admission["protected_environments"]
            ):
                continue
            out["policy_violations"].append(
                {
                    "file": path,
                    "rule": "non-allowed-runner-without-protected-environment",
                    "detail": f"job {name} runs-on {labels} reachable from {reachable}",
                }
            )
    return out


def check(files: dict[str, str], profile: dict | None) -> dict:
    """files: {path: text}. profile: parsed dev-platform.infra/v1 or None (public default)."""
    if profile is not None:
        problems = runners.validate_profile(profile)
        if problems:
            raise ValueError(f"invalid infra profile: {problems}")
    offered = (profile or {}).get("runners", []) + [dict(h) for h in runners.HOSTED]
    admission = {**DEFAULT_ADMISSION, **((profile or {}).get("admission") or {})}
    out = {"policy_violations": [], "incomplete": [], "risk_indicators": []}
    for path in sorted(files):
        r = check_workflow(path, files[path], offered, admission)
        for k in out:
            out[k] += r[k]
    out["admission"] = (
        "failed" if out["policy_violations"] else ("unavailable" if out["incomplete"] else "ok")
    )
    out["policy_source"] = (
        "supplied profile" if profile is not None else "public default (hosted runners only)"
    )
    out["note"] = (
        "risk_indicators are heuristic and never change admission; no findings is not a proof of safety"
    )
    return out
