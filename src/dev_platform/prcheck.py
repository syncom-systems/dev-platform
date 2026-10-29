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
import json
import re

from . import runners

PR_REACHABLE = ("pull_request", "pull_request_target", "workflow_run")
HOSTED_LABELS = ("ubuntu-*", "macos-*", "windows-*")
DEFAULT_ADMISSION = {"forbidden_triggers": [], "protected_environments": []}


# A guarded `runs-on` is read, never evaluated: one fixed shape, matched textually.
#   ${{ github.event.pull_request.head.repo.full_name == github.repository && <labels> || <labels> }}
# where <labels> is `'label'` or `fromJSON('["label", ...]')`. Anything else stays an unsupported expression.
_LABEL = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_LABELS = rf"""(?:'{_LABEL}'|fromJSON\('\[[^'\\]*\]'\))"""
_GUARDED = re.compile(
    rf"\$\{{\{{\s*github\.event\.pull_request\.head\.repo\.full_name\s*==\s*github\.repository"
    rf"\s*&&\s*({_LABELS})\s*\|\|\s*({_LABELS})\s*\}}\}}"
)
# Events whose payload carries `pull_request.head.repo` (the guard can be true), and events whose payload
# provably does not (the guard is false). Any other trigger leaves the guard unproved.
GUARD_TRUE_EVENTS = ("pull_request", "pull_request_target")
GUARD_FALSE_EVENTS = ("push", "schedule", "workflow_dispatch", "release", "workflow_run")
# Labels every self-hosted runner of an OS or architecture carries: never an unreachable sentinel.
IMPLICIT_LABELS = {"self-hosted", "linux", "windows", "macos", "x64", "x86", "arm", "arm64"}


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


def _labels(token: str) -> list[str]:
    if token.startswith("'"):
        return [token[1:-1]]
    try:
        labels = json.loads(token[len("fromJSON('") : -2])
    except ValueError:
        raise Unsupported("guarded runs-on: the label list is not JSON") from None
    if not (
        isinstance(labels, list)
        and labels
        and all(isinstance(x, str) and re.fullmatch(_LABEL, x) for x in labels)
        and len(set(labels)) == len(labels)
    ):
        raise Unsupported("guarded runs-on: labels must be unique plain strings")
    return labels


def guarded_runs_on(job: dict) -> tuple[list[str], list[str]] | None:
    """(labels when the guard holds, labels otherwise) of a `runs-on` in the one supported guarded shape;
    None when it has another shape. Raises Unsupported for that shape with labels that are not plain."""
    ro = job.get("runs-on")
    m = _GUARDED.fullmatch(ro.strip()) if isinstance(ro, str) else None
    return (_labels(m.group(1)), _labels(m.group(2))) if m else None


def _unreachable(labels: list[str], offered: list[dict]) -> bool:
    """A sentinel: one plain label that no runner of the supplied profile carries and no runner has by
    default. The job it selects waits for a runner that does not exist."""
    if len(labels) != 1 or labels[0].lower() in IMPLICIT_LABELS:
        return False
    if any(fnmatch.fnmatch(labels[0], g) for g in HOSTED_LABELS):
        return False
    return not any(labels[0] in r.get("labels", []) for r in offered)


def guarded_verdict(
    guard: tuple[list[str], list[str]],
    triggers: list[str],
    offered: list[dict],
    same_repo_pr_opt_in: bool = False,
) -> dict:
    """What a guarded runs-on can select, and for which events (static; nothing is evaluated).

    `not_admitted` lists the branches that are not admitted for the events that reach them, `problem` is set
    when the guard cannot be proved safe (the job is then `incomplete`)."""
    on_true, on_false = guard
    public_sets = _allowed_label_sets(offered)
    out: dict = {"on_true": on_true, "on_false": on_false, "problem": None, "true_reachable_by": [],
                 "true_event_trust": None, "not_admitted": []}  # fmt: skip
    unknown = [t for t in triggers if t not in GUARD_TRUE_EVENTS + GUARD_FALSE_EVENTS]
    if unknown:
        out["problem"] = f"trigger {unknown[0]!r} may carry a pull_request payload: the guard is not proved"
        return out
    # The false branch is reached by every event, fork pull requests included: it must be admitted for an
    # untrusted event or select no runner at all.
    if not (_runs_on_allowed(on_false, public_sets) or _unreachable(on_false, offered)):
        out["not_admitted"].append(on_false)
    out["true_reachable_by"] = [t for t in triggers if t in GUARD_TRUE_EVENTS]
    if not out["true_reachable_by"]:
        return out  # no trigger of this workflow can make the guard true
    # The true branch is reached only by a pull request whose head repository is the base repository. That
    # is trusted exactly when the platform's event-trust derivation says so: never for pull_request_target,
    # and for pull_request only on the operator's explicit same-repository opt-in.
    trusted = "pull_request_target" not in triggers and same_repo_pr_opt_in
    out["true_event_trust"] = "trusted" if trusted else "untrusted"
    if _runs_on_allowed(on_true, public_sets):
        return out
    if not (trusted and any(set(on_true) <= set(r.get("labels", [])) for r in offered)):
        out["not_admitted"].append(on_true)
    return out


def _job_line(text: str, name: str) -> int | None:
    """Best-effort 1-based line of `<name>:` under `jobs:` (the subset parser keeps no positions)."""
    in_jobs = False
    for i, line in enumerate(text.splitlines(), 1):
        if re.match(r"^jobs:\s*(#.*)?$", line):
            in_jobs = True
        elif in_jobs and re.match(rf"^\s+{re.escape(name)}:\s*(#.*)?$", line):
            return i
    return None


def _group_facts(ro: dict) -> tuple[str | None, list[str] | None]:
    """Structured `runs-on: {group, labels}` value as written (raw strings, never evaluated)."""
    group = ro.get("group")
    labels = ro.get("labels")
    if isinstance(labels, str):
        labels = [labels]
    if not (isinstance(labels, list) and all(isinstance(x, str) for x in labels)):
        labels = None
    return (group if isinstance(group, str) else None), labels


def job_facts(
    doc: dict,
    text: str,
    public_sets: list[set[str]] | None = None,
    offered: list[dict] | None = None,
    triggers: list[str] | None = None,
    same_repo_pr_opt_in: bool = False,
) -> list[dict]:
    """Per job: resolved runner label sets (or `unresolved` + reason), environment, source line.

    `non_public_label_sets` is the resolved sets the profile does not admit (the rule `check_workflow`
    applies); `[]` means every resolved set is admitted, `None` means the job could not be resolved (never
    read it as admitted). A `runs-on` group/labels mapping is exposed as `runs_on_group`/`runs_on_labels`
    and stays unresolved. A guarded `runs-on` lists both branches in `runs_on`, with `guard` (what reaches
    each branch and its event trust) and the branches that are not admitted in `non_public_label_sets`."""
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return []
    facts = []
    for name, job in jobs.items():
        f: dict = {"name": str(name), "line": _job_line(text, str(name)), "runs_on": None,
                   "runs_on_group": None, "runs_on_labels": None, "non_public_label_sets": None,
                   "unresolved": None, "environment": None, "uses": None, "guard": None}  # fmt: skip
        if not isinstance(job, dict):
            f["unresolved"] = "job is not a mapping"
        else:
            env = job.get("environment")
            env_name = env.get("name") if isinstance(env, dict) else env
            f["environment"] = env_name if isinstance(env_name, str) else None
            f["uses"] = job["uses"] if isinstance(job.get("uses"), str) else None
            if "uses" in job and "runs-on" not in job:
                f["unresolved"] = "reusable workflow call has no runs-on"
            else:
                if isinstance(job.get("runs-on"), dict):
                    f["runs_on_group"], f["runs_on_labels"] = _group_facts(job["runs-on"])
                try:
                    guard = guarded_runs_on(job)
                    if guard is not None:
                        v = guarded_verdict(guard, triggers or [], offered or [], same_repo_pr_opt_in)
                        if v["problem"]:
                            raise Unsupported(v["problem"])
                        f["runs_on"], f["guard"] = [guard[0], guard[1]], v
                        f["non_public_label_sets"] = v["not_admitted"]
                    else:
                        f["runs_on"] = _resolve_runs_on(job)
                        f["non_public_label_sets"] = [
                            ls for ls in f["runs_on"] if not _runs_on_allowed(ls, public_sets or [])
                        ]
                except Unsupported as e:
                    f["runs_on"] = None
                    f["unresolved"] = str(e)
        facts.append(f)
    return facts


def check_workflow(
    path: str,
    text: str,
    profile_runners: list[dict],
    admission: dict,
    facts: list | None = None,
    same_repo_pr_opt_in: bool = False,
) -> dict:
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
        if facts is not None:
            facts.append({"file": path, "triggers": None, "pr_reachable_triggers": None, "jobs": [],
                          "unresolved": str(e)})  # fmt: skip
        return out
    reachable = [t for t in trig if t in PR_REACHABLE]
    public_sets = _allowed_label_sets(profile_runners)
    if facts is not None:
        facts.append({"file": path, "triggers": trig, "pr_reachable_triggers": reachable,
                      "jobs": job_facts(doc, text, public_sets, profile_runners, trig, same_repo_pr_opt_in),
                      "unresolved": None})  # fmt: skip
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
            guard = guarded_runs_on(job)
            verdict = guarded_verdict(guard, trig, profile_runners, same_repo_pr_opt_in) if guard else None
            if verdict and verdict["problem"]:
                raise Unsupported(verdict["problem"])
            sets = [] if verdict else _resolve_runs_on(job)
        except Unsupported as e:
            inc(f"job {name}: {e}")
            continue
        env = job.get("environment")
        env_name = env.get("name") if isinstance(env, dict) else env
        for labels in verdict["not_admitted"] if verdict else sets:
            if not verdict and _runs_on_allowed(labels, public_sets):
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


def check(
    files: dict[str, str], profile: dict | None, *, facts: bool = False, same_repo_pr_opt_in: bool = False
) -> dict:
    """files: {path: text}. profile: parsed dev-platform.infra/v1 or None (public default).
    With facts=True the parsed per-file triggers and per-job runner/environment facts are returned as `facts`
    (the same conservative reader that decides admission; unresolvable shapes stay `incomplete`).
    `same_repo_pr_opt_in` is the operator's statement (as for `runners.event_trust`) that pull requests from
    the same repository are trusted; it is never read from a workflow, a profile or a configuration."""
    if profile is not None:
        problems = runners.validate_profile(profile)
        if problems:
            raise ValueError(f"invalid infra profile: {problems}")
    offered = (profile or {}).get("runners", []) + [dict(h) for h in runners.HOSTED]
    admission = {**DEFAULT_ADMISSION, **((profile or {}).get("admission") or {})}
    out = {"policy_violations": [], "incomplete": [], "risk_indicators": []}
    collected: list[dict] = []
    for path in sorted(files):
        r = check_workflow(
            path, files[path], offered, admission, collected if facts else None, same_repo_pr_opt_in
        )
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
    if facts:
        out["facts"] = collected
    return out
