#!/usr/bin/env python3
"""Local story briefs and channel handoff packages. No network calls."""
from __future__ import annotations
import argparse
import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path

PLATFORMS = {
    'wechat-article': ('微信公众号', 'article'),
    'xiaohongshu': ('小红书图文', 'cards'),
    'csdn': ('CSDN', 'article'),
    'aws-builder-center': ('AWS Builder Center', 'article'),
    'x': ('X', 'thread'),
    'wechat-channels': ('微信视频号', 'video'),
    'xiaohongshu-video': ('小红书视频', 'video'),
    'douyin': ('抖音', 'video'),
    'bilibili': ('B站', 'video'),
    'youtube': ('YouTube', 'video'),
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def errors_for(data, root, check_files=False):
    errors = []
    if not isinstance(data, dict):
        return ['Brief must be a JSON object']
    if data.get('version') != 1:
        errors.append('version must be 1')
    for key in ('title', 'audience', 'goal'):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f'{key} must be a nonempty string')
    for key in ('body_markdown', 'author'):
        if not isinstance(data.get(key, ''), str):
            errors.append(f'{key} must be a string')
    platforms = data.get('platforms', [])
    if not isinstance(platforms, list) or not platforms:
        errors.append('platforms must be a nonempty list')
        platforms = []
    for p in platforms:
        if not isinstance(p, str) or p not in PLATFORMS:
            errors.append(f'Unsupported platform: {p!r}')
    sources = data.get('sources', [])
    assets = data.get('assets', [])
    claims = data.get('claims', [])
    for key, value in [('sources', sources), ('assets', assets), ('claims', claims)]:
        if not isinstance(value, list):
            errors.append(f'{key} must be a list')
    if not all(isinstance(x, list) for x in (sources, assets, claims)):
        return errors
    known = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get('id'), str):
            errors.append('Each source needs a string id'); continue
        if source['id'] in known:
            errors.append(f'Duplicate source id: {source["id"]}')
        known.add(source['id'])
        if not any(source.get(k) for k in ('url', 'path', 'note')):
            errors.append(f'Source {source["id"]} needs url, path, or a user-provided note')
    for claim in claims:
        if not isinstance(claim, dict):
            errors.append('Each claim must be an object'); continue
        kind = claim.get('kind')
        if kind not in ('fact', 'observation', 'illustration'):
            errors.append(f'Claim {claim.get("id")} needs kind fact, observation, or illustration')
        ids = claim.get('source_ids', [])
        if not isinstance(ids, list):
            errors.append('source_ids must be a list'); continue
        if kind in ('fact', 'observation') and not ids:
            errors.append(f'Claim {claim.get("id")} has no evidence')
        for sid in ids:
            if not isinstance(sid, str) or sid not in known:
                errors.append(f'Claim references unknown source {sid!r}')
        if claim.get('metric') and not all(claim.get(k) for k in ('meaning', 'scope')):
            errors.append(f'Metric {claim.get("id")} needs meaning and scope')
    asset_ids = set()
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get('id'), str):
            errors.append('Each asset needs a string id'); continue
        if asset['id'] in asset_ids:
            errors.append(f'Duplicate asset id: {asset["id"]}')
        asset_ids.add(asset['id'])
        path = asset.get('path')
        if not isinstance(path, str) or not path:
            errors.append(f'Asset {asset["id"]} needs a local path'); continue
        if not asset.get('usage'):
            errors.append(f'Asset {asset["id"]} needs usage/rights context')
        people = asset.get('people', [])
        if not isinstance(people, list):
            errors.append('Asset people must be a list'); continue
        for person in people:
            if not isinstance(person, dict):
                errors.append('Each person must be an object'); continue
            if person.get('represents_author') and person.get('identity_confirmed') is not True:
                errors.append(f'Asset {asset["id"]}: author identity is not confirmed')
        if check_files and not (root / path).is_file():
            errors.append(f'Missing asset: {path}')
    variants = data.get('variants', {})
    if not isinstance(variants, dict):
        errors.append('variants must be an object'); return errors
    for key, variant in variants.items():
        if key not in PLATFORMS or not isinstance(variant, dict):
            errors.append(f'Invalid variant: {key}'); continue
        for field in ('title', 'summary', 'body_markdown', 'description'):
            if field in variant and not isinstance(variant[field], str):
                errors.append(f'{key}.{field} must be a string')
        for field in ('asset_ids', 'tags', 'posts'):
            if field in variant and (not isinstance(variant[field], list) or
                                     not all(isinstance(x, str) for x in variant[field])):
                errors.append(f'{key}.{field} must be a string list')
        if isinstance(variant.get('asset_ids', []), list):
            ids = variant.get('asset_ids', [])
            if all(isinstance(aid, str) for aid in ids) and len(ids) != len(set(ids)):
                errors.append(f'{key} has duplicate asset_ids')
            for aid in variant.get('asset_ids', []):
                if not isinstance(aid, str) or aid not in asset_ids:
                    errors.append(f'{key} references unknown asset {aid!r}')
    return errors


def safe_url(raw):
    return raw if re.match(r'^https?://', raw, re.I) else ''


def inline(text):
    """Small safe formatting subset; raw HTML is always escaped."""
    out = html.escape(text)
    out = re.sub(r'`([^`]+)`', r'<code style="background:#eee;padding:2px 4px;">\1</code>', out)
    out = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', out)
    return out


def article_html(markdown, title, assets):
    # Deliberately not a full Markdown parser. It accepts our documented subset.
    rows = [f'<h1 style="font-size:27px;line-height:1.35;">{html.escape(title)}</h1>']
    paragraph, code = [], None
    asset_paths = {a.get('original_path'): a.get('package_path') for a in assets}
    def flush():
        if paragraph:
            rows.append('<p style="margin:0 0 18px;line-height:1.85;font-size:16px;">' + inline(' '.join(paragraph)) + '</p>')
            paragraph.clear()
    for line in markdown.splitlines():
        if line.startswith('```'):
            flush()
            if code is None: code = []
            else:
                rows.append('<pre style="white-space:pre-wrap;background:#f1f3f5;padding:16px;"><code>' + html.escape('\n'.join(code)) + '</code></pre>')
                code = None
            continue
        if code is not None: code.append(line); continue
        if not line.strip(): flush(); continue
        heading = re.match(r'^(#{1,6})\s+(.*)$', line)
        picture = re.fullmatch(r'!\[([^\]]*)\]\(([^)]+)\)', line.strip())
        if heading:
            flush(); n = min(6, len(heading[1]) + 1)
            rows.append(f'<h{n} style="margin:28px 0 14px;line-height:1.5;">{inline(heading[2])}</h{n}>')
        elif picture:
            flush(); src = asset_paths.get(picture[2]) or safe_url(picture[2])
            if src:
                rows.append(f'<figure style="margin:20px 0;"><img src="{html.escape(src, quote=True)}" alt="{html.escape(picture[1], quote=True)}" style="display:block;width:100%;height:auto;"/><figcaption style="color:#666;font-size:13px;margin-top:8px;">{inline(picture[1])}</figcaption></figure>')
            else:
                raise ValueError(f'Image must be included as an asset or use https URL: {picture[2]}')
        elif line.startswith('> '):
            flush(); rows.append('<blockquote style="border-left:3px solid #8264cc;padding:12px 18px;margin:18px 0;background:#f4f1fa;">' + inline(line[2:]) + '</blockquote>')
        elif re.match(r'^[-*] ', line):
            flush(); rows.append('<p style="line-height:1.85;margin:7px 0;">• ' + inline(line[2:]) + '</p>')
        else: paragraph.append(line.strip())
    if code is not None:
        raise ValueError('Unclosed fenced code block')
    flush()
    body = '<section style="max-width:680px;margin:auto;padding:24px;color:#17141f;font-family:system-ui,sans-serif;">' + '\n'.join(rows) + '</section>'
    return '<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(title) + '</title><body style="margin:0;background:#fff;">' + body + '</body></html>'


def pack(brief_path, output, targets, copy_assets=False):
    path = Path(brief_path).resolve(); data = read_json(path)
    errors = errors_for(data, path.parent, check_files=copy_assets)
    if errors: raise ValueError('\n'.join(errors))
    targets = targets or data['platforms']
    for p in targets:
        if p not in PLATFORMS: raise ValueError(f'Unsupported platform: {p}')
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output is not empty; choose a new revision directory')
    output.mkdir(parents=True, exist_ok=True)
    receipts = []
    for platform in targets:
        folder = output / platform; folder.mkdir()
        variant = data.get('variants', {}).get(platform, {})
        title = variant.get('title', data['title'])
        body = variant.get('body_markdown', data.get('body_markdown', ''))
        selected = variant.get('asset_ids', [])
        attachments = []
        registry = {asset['id']: asset for asset in data.get('assets', [])}
        for asset_id in selected:
            asset = registry[asset_id]
            original = Path(asset['path'])
            row = {'id':asset['id'], 'original_path':asset['path'], 'usage':asset['usage'], 'package_path':None}
            if copy_assets:
                destination = folder / 'media' / f'{len(attachments)+1:02d}{original.suffix.lower()}'
                destination.parent.mkdir(exist_ok=True)
                shutil.copy2(path.parent / original, destination)
                row['package_path'] = str(destination.relative_to(folder))
                row['sha256'] = hashlib.sha256(destination.read_bytes()).hexdigest()
            attachments.append(row)
        metadata = {
            'platform':platform, 'channel':PLATFORMS[platform][0],
            'format':PLATFORMS[platform][1], 'title':title,
            'author':data.get('author',''), 'summary':variant.get('summary',''),
            'description':variant.get('description',body), 'tags':variant.get('tags',[]),
            'adaptation':'authored-platform-variant' if variant else 'shared-master-needs-editorial-adaptation',
            'publication_state':'local_only', 'originality':'review-in-platform-editor',
            'attachments':attachments,
        }
        (folder/'metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        path_map = {a['original_path']: a['package_path'] for a in attachments if a['package_path']}
        packaged_body = re.sub(r'(!\[[^\]]*\]\()([^)]+)(\))',
                               lambda m: m[1] + path_map.get(m[2], m[2]) + m[3], body)
        (folder/'article.md').write_text(f'# {title}\n\n{packaged_body}\n',encoding='utf-8')
        if PLATFORMS[platform][1] in ('article','cards'):
            # Missing copied media must not silently become an empty image slot.
            if any(a['package_path'] is None for a in attachments) and '![' in body:
                (folder/'preview-needed.txt').write_text('Run pack --copy-assets to make a working local image preview.\n', encoding='utf-8')
            else:
                (folder/'preview.html').write_text(article_html(body,title,attachments),encoding='utf-8')
        if platform == 'x':
            posts = variant.get('posts', [body])
            (folder/'thread.json').write_text(json.dumps({'posts':posts,'lengths':[len(x) for x in posts], 'length_note':'Unicode code points only; verify weighted/account limits in the editor.'},ensure_ascii=False,indent=2),encoding='utf-8')
        if PLATFORMS[platform][1] == 'video':
            (folder/'description.txt').write_text(metadata['description']+'\n',encoding='utf-8')
        (folder/'handoff.txt').write_text(
            f'{PLATFORMS[platform][0]} · local publishing package\n'
            'Open the matching official creator editor or configured connector.\n'
            'Check the account, audience/visibility, asset order, cover, captions, originality and preview.\n'
            'This export has not uploaded, drafted or published anything.\n'
            'Use the toolkit publishing guide for the exact next action; keep the resulting ID/URL as a receipt.\n'
            'An article preview is local HTML, not a guarantee of editor compatibility.\n',encoding='utf-8')
        receipts.append({'platform':platform,'directory':str(folder.relative_to(output)),'state':'local_only'})
    (output/'manifest.json').write_text(json.dumps({'version':1,'title':data['title'],'packages':receipts},ensure_ascii=False,indent=2),encoding='utf-8')
    return receipts


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command',required=True)
    init = sub.add_parser('init');init.add_argument('directory');init.add_argument('--demo',action='store_true')
    validate = sub.add_parser('validate');validate.add_argument('brief');validate.add_argument('--check-files',action='store_true')
    export = sub.add_parser('pack');export.add_argument('brief');export.add_argument('--output',required=True);export.add_argument('--platforms',nargs='+',choices=list(PLATFORMS));export.add_argument('--copy-assets',action='store_true')
    sub.add_parser('platforms')
    args=ap.parse_args()
    try:
        if args.command=='platforms':result=PLATFORMS
        elif args.command=='init':
            directory=Path(args.directory);directory.mkdir(parents=True,exist_ok=True)
            target=directory/'brief.json'
            if target.exists():raise ValueError('brief.json already exists')
            template=Path(__file__).resolve().parents[1]/'templates'/('demo-brief.json' if args.demo else 'brief.json')
            shutil.copy2(template,target)
            result={'brief':str(target),'next':'Edit the brief, then validate and pack. Nothing was uploaded.'}
        elif args.command=='validate':
            path=Path(args.brief);errors=errors_for(read_json(path),path.resolve().parent,args.check_files)
            if errors:raise ValueError('\n'.join(errors))
            result={'valid':True,'note':'Structural/evidence-reference validation only; the agent must verify source accuracy and actual media.'}
        else:result=pack(args.brief,args.output,args.platforms,args.copy_assets)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ValueError,OSError,TypeError,KeyError) as e:
        print(f'Error: {e}',file=sys.stderr);return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
