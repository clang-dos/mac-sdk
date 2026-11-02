#!/usr/bin/env python3
"""Append type definitions to a defs file from a compact text form.

    python3 tools/add-types.py defs/Foo.yaml < types.txt

    struct Name [size]        members follow, indented: `type name`
      int16_t[4] counts
      common COMMONFSQUEUEDEFS   (a shared member block)
    union Name [size]
    typedef Name type
    enum [Name]               values follow, indented: `name value`
      kFoo 1
      kBar 'abcd'
    funptr NameProcPtr ret (type name, type name)

A line `# text` puts a comment on the next definition. Struct sizes are
checked by tests/sizes.c only where listed there, so give the size from
Apple's headers when you know it.
"""
import glob
import os
import re
import sys

import yaml


def defined_names():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "defs")
    names = set()
    for f in glob.glob(os.path.join(root, "*.yaml")):
        names |= set(re.findall(r"name: (\w+)", open(f).read()))
    return names


def main():
    items, cur, comment = [], None, None
    known = defined_names()
    for raw in sys.stdin:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("#"):
            comment = line[1:].strip()
            continue
        if raw[0] in " \t":
            body = line.split()
            kind, v = cur
            if kind in ("struct", "union") and body[0] == "common":
                v.setdefault("members", []).append({"common": body[1]})
            elif kind in ("struct", "union"):
                v.setdefault("members", []).append(
                    {"name": body[-1], "type": " ".join(body[:-1])})
            else:
                val = " ".join(body[1:])
                try:
                    val = int(val, 0)
                except ValueError:
                    if re.fullmatch(r"'.{4}'", val):
                        val = val
                if body[0] in known:    # constants are often repeated
                    print(f"{body[0]}: already defined, skipped", file=sys.stderr)
                else:
                    v["values"].append({"name": body[0], "value": val})
            continue
        word = line.split()
        kind = word[0]
        if kind in ("struct", "union"):
            v = {"name": word[1]}
            if len(word) > 2:
                v["size"] = int(word[2], 0)
        elif kind == "typedef":
            v = {"name": word[1], "type": " ".join(word[2:])}
        elif kind == "enum":
            v = {"name": word[1]} if len(word) > 1 else {}
            v["values"] = []
        elif kind == "funptr":
            m = re.match(r"funptr\s+(\w+)\s+(.+?)\s*\((.*)\)\s*$", line)
            v = {"name": m.group(1)}
            if m.group(2) != "void":
                v["return"] = m.group(2)
            args = []
            for a in filter(None, (x.strip() for x in m.group(3).split(","))):
                t, n = a.rsplit(None, 1)
                args.append({"name": n, "type": t})
            if args:
                v["args"] = args
        else:
            raise SystemExit(f"cannot parse: {line}")
        if comment:
            v["comment"] = comment
            comment = None
        cur = (kind, v)
        items.append({kind: v})
    with open(sys.argv[1], "a", encoding="utf-8") as f:
        for it in items:
            f.write("\n# ####\n\n")
            f.write(yaml.safe_dump([it], sort_keys=False, width=100))


if __name__ == "__main__":
    main()
