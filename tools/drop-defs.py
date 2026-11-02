#!/usr/bin/env python3
"""Remove the named functions from a defs file: drop-defs.py defs/F.yaml A B"""
import sys

path, names = sys.argv[1], set(sys.argv[2:])
chunks = open(path).read().split("\n# ####\n")
keep = []
for c in chunks:
    lines = [l.strip() for l in c.strip().splitlines()]
    if len(lines) > 1 and lines[0] == "- function:" and \
            any(l == f"name: {n}" for n in names for l in lines[1:3]):
        print("dropped", lines[1], file=sys.stderr)
        continue
    keep.append(c)
open(path, "w").write("\n# ####\n".join(keep))
