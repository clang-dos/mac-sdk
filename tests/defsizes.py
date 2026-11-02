#!/usr/bin/env python3
"""Print a C file that checks the size of every record whose definition
gives one (`size:` in defs/). tests/run.sh compiles it for both CPUs."""
import os
import sys

import yaml

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
print("#include <Multiverse.h>")
for f in sorted(os.listdir(os.path.join(root, "defs"))):
    if not f.endswith(".yaml") or f == "MPW.yaml":  # MPW.h is separate
        continue
    for it in yaml.safe_load(open(os.path.join(root, "defs", f))) or []:
        if it.get("only-for") or it.get("not-for"):
            continue
        for kind in ("struct", "union"):
            v = it.get(kind)
            if isinstance(v, dict) and v.get("name") and v.get("size"):
                print(f"_Static_assert(sizeof({v['name']}) == {v['size']}, "
                      f"\"{v['name']} ({f})\");")
