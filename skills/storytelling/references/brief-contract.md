# Brief and handoff contract

`story.py` is an offline editor helper, not a text-generation service or publisher. An agent researches and writes the content; this tool checks references and prepares files. No API keys or network access are used.

## Essential fields

`version: 1`, nonempty `title`, `audience`, `goal`, and a nonempty `platforms` list. Optional `author` and `body_markdown` are strings. Start with `init`, fill these fields, then `validate`. `init --demo` is explicitly fictional and can be tested without assets.

Platform IDs: `wechat-article`, `xiaohongshu`, `csdn`, `aws-builder-center`, `x`, `wechat-channels`, `xiaohongshu-video`, `douyin`, `bilibili`, `youtube`.

## Evidence and assets

- `sources`: objects with unique `id` and at least a `url`, local `path`, or `note` recording user testimony/context. Store publication dates and retrieval dates as extra fields when needed.
- `claims`: `id`, `text`, `kind` (`fact`, `observation`, `illustration`), `source_ids`. Facts and observations require a known source. A numeric claim with `metric: true` also requires `meaning` and `scope`; add `unit`, denominator, raw value, normalization formula and date when applicable. The validator checks links, not the truth of a URL or claim.
- `assets`: unique `id`, local `path` relative to the brief (absolute paths also work locally), and `usage` explaining permitted use. Optional `people` entries contain `name`, `role`, `represents_author`, `identity_confirmed`. A shot marked as representing the author cannot pass without confirmed identity. Do not infer identity from clothing or proximity.

Keep proprietary briefs/assets outside the public toolkit checkout. The public release contains only instructions, code and text examples.

## Authored channel variants

`variants.<platform>` may contain `title`, `summary`, `body_markdown`, `description`, `tags`, `asset_ids`. X may include an ordered `posts` list. Select only the media needed for that platform by `asset_ids`; the tool does not copy every source into every post.

The tool uses authored variants when supplied, otherwise the master text. A fallback is labelled `shared-master-needs-editorial-adaptation`; it is not claimed to be an optimized platform edition. `thread.json` reports Unicode code-point counts, not X's account-specific or weighted limit.

## Commands

```bash
python scripts/story.py init /tmp/my-story --demo
python scripts/story.py validate /tmp/my-story/brief.json
python scripts/story.py pack /tmp/my-story/brief.json --output /tmp/my-story/release-v1
# Include explicitly selected local assets in a portable publishing bundle:
python scripts/story.py pack /path/to/brief.json --output /path/to/release-v2 --copy-assets
```

Each target gets Markdown, metadata and a handoff note. Article/card channels also get local HTML when media can be resolved; video targets get a description; X gets ordered thread JSON. Every metadata file has `publication_state: local_only`. Existing nonempty output directories are refused, so each revision is reviewable.

The HTML converter supports paragraphs, headings, fenced code, bold, inline code, bullet paragraphs, quotes and standalone Markdown images. Raw HTML is escaped. It is intentionally not a complete Markdown implementation. Images must match included asset paths or use HTTP(S). Without `--copy-assets`, local images require a later preview pass; there is no automatic upload, CDN rewrite or claim of WeChat compatibility. Use the publishing adapter/editor for that stage.
