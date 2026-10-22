#!/usr/bin/env python3
"""Search the vendored code-film and motion-graphics style briefs."""
import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LEMO = ROOT / "styles" / "lemo"
MG = ROOT / "styles" / "mg" / "prompts"
SKILL = ROOT.parent


def _rel(path):
    return path.resolve().relative_to(SKILL).as_posix()


def lemo_styles():
    rows = []
    for path in sorted(LEMO.glob("*/style.json")):
        if path.parent.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data["folder"] = path.parent.name
        data["kind"] = "lemo"
        data["path"] = _rel(path.parent / "STYLE.md")
        rows.append(data)
    return rows


def mg_styles():
    rows = []
    for path in sorted(MG.glob("*.md")):
        title = path.stem
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        rows.append({
            "slug": path.stem,
            "en": title,
            "cn": title,
            "folder": path.stem,
            "kind": "mg",
            "path": _rel(path),
            "uses": ["motion graphics"],
        })
    return rows


def all_styles():
    return lemo_styles() + mg_styles()


def _haystack(row):
    parts = [row.get("slug"), row.get("en"), row.get("cn"), row.get("folder"),
             row.get("category_en"), row.get("category_cn"), row.get("line"), row.get("line_cn"),
             row.get("kind")]
    uses = row.get("uses") or []
    parts.extend(uses)
    return " ".join(str(part) for part in parts if part).casefold()


def find(query, limit=20):
    needle = query.casefold().strip()
    if not needle:
        return []
    hits = [row for row in all_styles() if needle in _haystack(row)]
    return hits[:limit]


def _print(rows):
    for row in rows:
        label = row.get("cn") or row.get("en")
        print(f"{row['kind']:4}  {row['folder']:22}  {label}\n       {row['path']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "find"))
    parser.add_argument("query", nargs="?")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.command == "list":
        rows = all_styles()
    else:
        if not args.query:
            parser.error("find needs a query")
        rows = find(args.query, args.limit)
    _print(rows)
    print(f"{len(rows)} style(s)")


if __name__ == "__main__":
    main()
