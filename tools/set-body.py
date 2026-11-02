#!/usr/bin/env python3
"""Give functions in defs/ inline C glue for 68k (`m68k-body`).

    python3 tools/set-body.py < glue.txt

Each entry starts with a line `@@ Name [Needed, Names]`, naming the
function and anything the body uses from other headers, followed by the
body. The function is looked up in every defs/*.yaml file; an existing
body is replaced.
"""
import glob
import re
import sys


def entries(text):
    cur = None
    for line in text.splitlines():
        m = re.match(r"@@ (\w+)(?: \[(.*)\])?\s*$", line)
        if m:
            if cur:
                yield cur
            cur = [m.group(1), [n.strip() for n in (m.group(2) or "").split(",") if n.strip()], []]
        elif cur:
            cur[2].append(line)
    if cur:
        yield cur


def main():
    todo = {name: (needs, "\n".join(body).strip("\n")) for name, needs, body in entries(sys.stdin.read())}
    for path in sorted(glob.glob("defs/*.yaml")):
        text = open(path).read()
        chunks = text.split("\n# ####\n")
        changed = False
        for i, c in enumerate(chunks):
            lines = c.strip("\n").splitlines()
            if not lines or not (lines[0] == "- function:" or (
                    re.match(r"- api: \w+$", lines[0]) and lines[1:2] == ["  function:"])):
                continue
            m = next((re.match(r"    name: (\w+)$", l) for l in lines[1:3]
                      if re.match(r"    name: (\w+)$", l)), None)
            if not m or m.group(1) not in todo:
                continue
            name = m.group(1)
            needs, body = todo.pop(name)
            out, skip = [], False
            for l in lines:      # drop an earlier body
                if re.match(r"    m68k-(body|needs):", l):
                    skip = l.startswith("    m68k-body:")
                    continue
                if skip and (l.startswith("      ") or not l.strip()):
                    continue
                skip = False
                out.append(l)
            if needs:
                out.append(f"    m68k-needs: [{', '.join(needs)}]")
            out.append("    m68k-body: |")
            out += ["      " + l if l.strip() else "" for l in body.splitlines()]
            pre = c[:len(c) - len(c.lstrip("\n"))]
            post = c[len(c.rstrip("\n")):]
            chunks[i] = pre + "\n".join(out) + post
            changed = True
        if changed:
            open(path, "w").write("\n# ####\n".join(chunks))
    for name in todo:
        print(f"set-body: {name} not found", file=sys.stderr)
    if todo:
        sys.exit(1)


if __name__ == "__main__":
    main()
