#!/usr/bin/env python3
"""Copy the self-contained skill into an explicitly selected agent skill directory."""
import argparse
from pathlib import Path
import shutil


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',required=True,help='Agent skill directory; creates its storytelling child')
    args=parser.parse_args()
    source=Path(__file__).resolve().parents[1]/'skills/storytelling'
    target=Path(args.target).expanduser().resolve()/'storytelling'
    if target.exists():parser.error('Destination already exists; keep or archive the previous version explicitly')
    if target.is_relative_to(source):parser.error('Destination must be outside the source skill')
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source,target,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.venv','node_modules','.env*','receipts','outputs','media','models','checkpoints'))
    print(target/'SKILL.md')

if __name__=='__main__':main()
