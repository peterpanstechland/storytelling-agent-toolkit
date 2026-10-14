#!/usr/bin/env python3
"""Audit code-only public releases. No private media, models, sessions or secrets."""
import argparse
import re
import subprocess
import sys
from pathlib import Path

TEXT_EXTENSIONS = {'.py','.mjs','.js','.json','.md','.txt','.toml','.yaml','.yml','.html','.css','.sh'}
TEXT_NAMES = {'LICENSE','.gitignore','run','AGENTS.md'}
FORBIDDEN_PARTS = {'node_modules','.venv','venv','__pycache__','models','checkpoints','outputs','media','receipts','.sessions','.aws','.ssh'}
PATTERNS = {
 'GitHub token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,})\b'),
 'cloud access key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
 'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
 'machine-specific home': re.compile(r'/(?:home|Users)/[A-Za-z0-9_.-]+/'),
 'private LAN address': re.compile(r'\b192\.168\.\d{1,3}\.\d{1,3}\b'),
 'JWT credential': re.compile(r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\b'),
}


def findings(root, files):
    errors=[]
    for relative in files:
        rel=Path(relative);p=root/rel
        if p.is_symlink():errors.append((str(rel),'symlink not permitted'));continue
        if not p.is_file():errors.append((str(rel),'missing tracked file'));continue
        if any(part in FORBIDDEN_PARTS for part in rel.parts):errors.append((str(rel),'runtime/media directory'))
        if p.name.startswith('.env') or re.search(r'(?:credentials|session|cookies|token-store)',p.name,re.I):
            errors.append((str(rel),'credential/session filename'))
        if p.suffix.lower() not in TEXT_EXTENSIONS and p.name not in TEXT_NAMES:
            errors.append((str(rel),'not an approved source-text extension'))
        if p.stat().st_size>512_000:errors.append((str(rel),'file exceeds code-only size budget'))
        try:text=p.read_text(encoding='utf-8')
        except UnicodeError:errors.append((str(rel),'binary file'));continue
        for name, pattern in PATTERNS.items():
            if pattern.search(text):errors.append((str(rel),name))
        # All relative Markdown reference links must stay in this repository.
        if p.suffix=='.md':
            for link in re.findall(r'\]\(([^)]+)\)',text):
                link=link.split('#',1)[0].strip('<>')
                if not link or re.match(r'^[a-z]+:',link,re.I):continue
                if any(c in link for c in ('{','*','\n',' ')):continue
                target=(p.parent/link).resolve()
                if not target.is_relative_to(root.resolve()):errors.append((str(rel),'link escapes repository: '+link))
                elif not target.exists():errors.append((str(rel),'broken relative link: '+link))
    return errors


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',default=Path(__file__).resolve().parents[1]);ap.add_argument('--tracked',action='store_true');args=ap.parse_args();root=Path(args.root).resolve()
    if args.tracked:
        files=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0');files=[p for p in files if p]
    else:
        files=[str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and not any(x in {'.git','node_modules','__pycache__','.venv'} for x in p.relative_to(root).parts)]
    if not files:print('ERROR: no release files',file=sys.stderr);return 1
    problems=findings(root,files)
    for file,reason in problems:print(f'ERROR {file}: {reason}',file=sys.stderr)
    if problems:return 1
    print(f'PASS: {len(files)} source-text files; no bundled media, models, sessions, common secrets or machine-specific paths.');return 0
if __name__=='__main__':raise SystemExit(main())
