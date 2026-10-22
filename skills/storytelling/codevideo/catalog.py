#!/usr/bin/env python3
"""Filter the code-rendered video index. Prompt bodies are not stored."""
import argparse
import json
from pathlib import Path


INDEX = Path(__file__).resolve().parent / "opus-index.json"


def load(path=None):
    payload = json.loads((path or INDEX).read_text(encoding="utf-8"))
    for entry in payload["entries"]:
        if "prompt" in entry:
            raise ValueError("opus index must not carry prompt bodies")
    return payload


def query(payload, category=None, tag=None, author=None, slug=None, limit=20):
    rows = payload["entries"]
    if category:
        rows = [row for row in rows if row["category"] == category]
    if tag:
        rows = [row for row in rows if tag in row["tech_tags"]]
    if author:
        needle = author.casefold()
        rows = [row for row in rows if needle in row["author"].casefold()]
    if slug:
        rows = [row for row in rows if row["slug"] == slug]
    return rows[:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category")
    parser.add_argument("--tag")
    parser.add_argument("--author")
    parser.add_argument("--slug")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    payload = load()
    if not any([args.category, args.tag, args.author, args.slug]):
        print(payload["note"])
        for name, count in sorted(payload["counts"].items()):
            print(f"{name}: {count}")
        print(f"entries: {len(payload['entries'])}")
        return
    rows = query(payload, args.category, args.tag, args.author, args.slug, args.limit)
    for row in rows:
        tags = ",".join(row["tech_tags"])
        print(f"{row['category']:12} {row['slug']}\n  {tags}\n  {row['post_url']}\n  {row['prompt_url']}")
    print(f"{len(rows)} match(es)")


if __name__ == "__main__":
    main()
