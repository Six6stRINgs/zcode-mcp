#!/usr/bin/env python3
"""Copy the skills shipped in this repository into a Codex-style skills dir.

Usage:
    python install_skills.py                # install to ~/.codex/skills
    python install_skills.py --dest PATH    # install somewhere else
    python install_skills.py --list         # show what would be installed

Every subdirectory of ./skills (each containing a SKILL.md) is copied into
the destination, overwriting previous copies of the same skill.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

REPO_SKILLS = Path(__file__).resolve().parent / "skills"
DEFAULT_DEST = Path(
    os.environ.get("CODEX_HOME", os.path.expanduser("~"))
) / ".codex" / "skills"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                        help=f"skills directory (default: {DEFAULT_DEST})")
    parser.add_argument("--list", action="store_true",
                        help="only list the available skills")
    args = parser.parse_args()

    if not REPO_SKILLS.is_dir():
        print(f"error: {REPO_SKILLS} not found — run this from a repo checkout",
              file=sys.stderr)
        return 1

    skills = sorted(
        d for d in REPO_SKILLS.iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file()
    )
    if not skills:
        print("no skills found in ./skills", file=sys.stderr)
        return 1

    for d in skills:
        print(d.name)
    if args.list:
        return 0

    args.dest.mkdir(parents=True, exist_ok=True)
    for d in skills:
        target = args.dest / d.name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(d, target)
        print(f"installed {d.name} -> {target}")
    print(f"\ndone: {len(skills)} skill(s) installed to {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
