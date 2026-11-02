#!/usr/bin/env python3
"""Give functions in a defs file explicit 68k code words.

    python3 tools/set-inline.py defs/Foo.yaml Name=0x2F3C,0x0004,0xFFFF ...

For calls whose 68k form is known but that the ROM glue does not show
(component calls, for example).
"""
import sys

import yaml

path = sys.argv[1]
want = {}
for a in sys.argv[2:]:
    n, w = a.split("=")
    want[n] = [int(x, 0) for x in w.split(",")]
text = open(path, encoding="utf-8").read()
items = yaml.safe_load(text)
out = []
for chunk in text.split("\n# ####\n"):
    data = yaml.safe_load(chunk) or []
    if len(data) == 1 and "function" in data[0] and \
            data[0]["function"]["name"] in want:
        f = data[0]["function"]
        f["m68k-inline"] = want.pop(f["name"])
        chunk = "\n" + yaml.safe_dump(data, sort_keys=False, width=100)
    out.append(chunk)
if want:
    sys.exit(f"not found: {', '.join(want)}")
open(path, "w", encoding="utf-8").write("\n# ####\n".join(out))
