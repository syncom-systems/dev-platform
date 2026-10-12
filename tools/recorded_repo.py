"""A recorded `gh api` that behaves like one GitHub repository: a linear history of commits on `main`.

Used by the unit tests and by the qualification tools (a stand-in for GitHub when no second identity exists).

Unlike a per-path table it keeps the tree after every commit, so what the verifier reads at a commit id is the
state of the repository at that commit, a listing is the directory at that commit, a deleted file leaves a
`removed` entry in the history, and a commit published after a read does not show in what was already read.
Only the endpoints the verifiers use are modelled; anything else is "not found".
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path


class Repo:
    def __init__(self) -> None:
        self.commits: list[dict] = []  # oldest first
        self.trees: dict[str, dict[str, bytes]] = {}
        self.fail = None  # callable(endpoint) -> bool: that call fails like an outage
        self.hooks: list = []  # callables(endpoint) run before each call (e.g. publish a commit mid-read)
        self.calls: list[str] = []
        self._seq = 0  # commit ids never repeat, even after history is rewritten

    # ---- building history
    def commit(self, changes, *, verified=True, author="", committer="", date=None, sha=None) -> str:
        """changes: {path: bytes | None}; None deletes the path."""
        tree = dict(self.commits[-1]["tree"]) if self.commits else {}
        files = []
        for path, data in changes.items():
            if data is None:
                files.append({"filename": path, "status": "removed"})
                tree.pop(path, None)
            else:
                files.append({"filename": path, "status": "modified" if path in tree else "added"})
                tree[path] = data
        self._seq += 1
        n = len(self.commits) + 1
        c = {
            "sha": sha or f"{self._seq:040x}",
            "verified": verified,
            "author": author,
            "committer": committer,
            "date": date or f"2026-10-12T11:{n % 60:02d}:00Z",
            "files": files,
            "tree": tree,
        }
        self.commits.append(c)
        self.trees[c["sha"]] = tree
        return c["sha"]

    def sign(self, path, raw, *, verified=True, author="", committer="", content=None, sha=None):
        """Compatibility with the per-path double: a commit of `path` whose bytes are `content` (default `raw`)."""
        self.commit({path: raw if content is None else content}, verified=verified, author=author,
                    committer=committer, sha=sha)  # fmt: skip

    def delete(self, path, *, author="", committer="", verified=True) -> str:
        return self.commit({path: None}, verified=verified, author=author, committer=committer)

    def rewind(self, count: int) -> None:
        """Force-push: drop the last `count` commits from the branch (the next commit gets a fresh id)."""
        for c in self.commits[len(self.commits) - count :]:
            self.trees.pop(c["sha"], None)
        del self.commits[len(self.commits) - count :]

    def wipe(self) -> None:
        self.commits.clear()
        self.trees.clear()

    # ---- persistence (qualification subprocesses read the same repository through a `gh` shim)
    def dump(self, path) -> None:
        enc = [{**{k: v for k, v in c.items() if k != "tree"}} for c in self.commits]
        blobs = {
            c["sha"]: {p: base64.b64encode(b).decode() for p, b in c["tree"].items()} for c in self.commits
        }
        Path(path).write_text(json.dumps({"commits": enc, "trees": blobs}))

    @classmethod
    def load(cls, path) -> Repo:
        doc = json.loads(Path(path).read_text())
        r = cls.__new__(cls)
        Repo.__init__(r)  # not a subclass's own seeding: the history is exactly what was dumped
        for c in doc["commits"]:
            tree = {p: base64.b64decode(b) for p, b in doc["trees"][c["sha"]].items()}
            r.commits.append({**c, "tree": tree})
            r.trees[c["sha"]] = tree
        r._seq = len(r.commits)
        return r

    # ---- the API
    def _public(self, c: dict) -> dict:
        return {
            "sha": c["sha"],
            "commit": {
                "verification": {
                    "verified": c["verified"],
                    "reason": "valid" if c["verified"] else "unsigned",
                },
                "committer": {"date": c["date"]},
            },
            "author": {"login": c["author"]},
            "committer": {"login": c["committer"]},
        }

    def _upto(self, ref: str) -> list[dict]:
        if ref == "main":
            return list(self.commits)
        for i, c in enumerate(self.commits):
            if c["sha"] == ref:
                return self.commits[: i + 1]
        raise KeyError(ref)

    def __call__(self, argv):
        assert argv[:2] == ["gh", "api"], argv
        ep = argv[2]
        self.calls.append(ep)
        for h in list(self.hooks):
            h(ep)
        if self.fail and self.fail(ep):
            return 1, "", "HTTP 502: Bad Gateway"
        try:
            m = re.search(r"/commits\?sha=([^&]+)&path=([^&]+)(?:&per_page=(\d+))?(?:&page=(\d+))?", ep)
            if m:
                ref, path, per, page = m.group(1), m.group(2), int(m.group(3) or 30), int(m.group(4) or 1)
                hits = [c for c in reversed(self._upto(ref))
                        if any(f["filename"] == path or f["filename"].startswith(path.rstrip("/") + "/")
                               for f in c["files"])]  # fmt: skip
                hits = hits[(page - 1) * per : page * per]
                return 0, json.dumps([self._public(c) for c in hits]), ""
            m = re.search(r"/compare/([0-9a-f]{40})\.\.\.([0-9a-f]{40}|main)", ep)
            if m:
                shas = [c["sha"] for c in self.commits]
                base, head = m.group(1), self._upto(m.group(2))[-1]["sha"]
                if base not in shas:
                    return 0, json.dumps({"status": "diverged"}), ""
                status = (
                    "identical"
                    if base == head
                    else "ahead"
                    if shas.index(base) < shas.index(head)
                    else "behind"
                )
                return 0, json.dumps({"status": status}), ""
            m = re.search(r"/commits/([0-9a-f]{40}|main)$", ep)
            if m:
                i = len(self._upto(m.group(1))) - 1
                c = self.commits[i]
                parents = [{"sha": self.commits[i - 1]["sha"]}] if i else []
                return 0, json.dumps({**self._public(c), "files": c["files"], "parents": parents}), ""
            m = re.search(r"/contents/([^?]+)\?ref=([0-9a-f]{40}|main)$", ep)
            if m:
                path, tree = m.group(1), self._upto(m.group(2))[-1]["tree"]
                if path in tree:
                    return 0, json.dumps({"content": base64.b64encode(tree[path]).decode()}), ""
                kids = sorted(p for p in tree if p.startswith(path + "/") and "/" not in p[len(path) + 1 :])
                if kids:
                    return (
                        0,
                        json.dumps([{"name": p.rsplit("/", 1)[1], "path": p, "type": "file"} for p in kids]),
                        "",
                    )
        except (KeyError, IndexError):
            pass
        return 1, "", "HTTP 404: Not Found"
