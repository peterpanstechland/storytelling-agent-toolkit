#!/usr/bin/env python3
"""Copy a self-contained skill into an explicitly selected agent skill directory."""
import argparse
from pathlib import Path
import shutil

SKILLS=('storytelling','pxl')

def copy_skill(name, target_root, parser):
    source=Path(__file__).resolve().parents[1]/'skills'/name
    target=Path(target_root).expanduser().resolve()/name
    if target.exists():parser.error('Destination already exists; keep or archive the previous version explicitly')
    if target.is_relative_to(source):parser.error('Destination must be outside the source skill')
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source,target,ignore=shutil.ignore_patterns(
        '__pycache__','*.pyc','.venv','node_modules','.env*','receipts','outputs','media','models','checkpoints','out','dist','*.tgz','._vs_*'))
    print(target/'SKILL.md')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',required=True,help='Agent skills directory; creates one child per selected skill')
    parser.add_argument('--skill',default='storytelling',choices=[*SKILLS,'all'],help='Skill to copy (default: storytelling)')
    args=parser.parse_args()
    names=SKILLS if args.skill=='all' else (args.skill,)
    for name in names:copy_skill(name,args.target,parser)

if __name__=='__main__':main()
