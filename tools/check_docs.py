"""Documentation consistency checks: ADR index, relative links, schema parseability."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\]\((?!https?:|#|mailto:)([^)#\s]+)")


def main() -> int:
    errors: list[str] = []
    for md in [*ROOT.glob("*.md"), *ROOT.glob("docs/**/*.md")]:
        for target in LINK.findall(md.read_text()):
            if not (md.parent / target).resolve().exists():
                errors.append(f"{md.relative_to(ROOT)}: broken link {target}")
    index = (ROOT / "docs/adr/README.md").read_text()
    for adr in sorted((ROOT / "docs/adr").glob("0*.md")):
        if adr.name not in index:
            errors.append(f"docs/adr/README.md: missing {adr.name}")
        if not re.search(r"^Status: (Ratified|Proposed|Superseded)", adr.read_text(), re.M):
            errors.append(f"{adr.name}: missing 'Status:' line")
    for schema in (ROOT / "schemas").glob("*.json"):
        try:
            json.loads(schema.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"{schema.name}: {e}")
    for e in errors:
        print(e, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
