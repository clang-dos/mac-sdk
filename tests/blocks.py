#!/usr/bin/env python3
"""Print a C file that checks each 68k call made through an argument
block (the Communications Toolbox calls) against the ROM's PowerPC glue
(data/blockinfo.json): the selector, the offset and size of every
argument in the block, and the size of the result. tests/run.sh
compiles it for 68k; a failed static assertion names the call."""
import json
import os
import re

here = os.path.dirname(os.path.abspath(__file__))
rom = json.load(open(os.path.join(here, "..", "data", "blockinfo.json")))
root = os.path.join(here, "..", "include", "mv")
pat = re.compile(r"static __inline__ __attribute__\(\(__always_inline__\)\) "
                 r"(.*?)\b(\w+)\((.*?)\) \{\n    struct \{ (.*?) \} __attribute__\(\(__packed__\)\)"
                 r" _pb = \{ (0x[0-9A-F]+)")
print("#include <Multiverse.h>")
seen = 0
for f in sorted(os.listdir(root)):
    for ret, name, params, fields, sel in pat.findall(open(os.path.join(root, f)).read()):
        r = rom.get(name)
        if r is None:
            print(f"#error {name}: not in data/blockinfo.json")
            continue
        seen += 1
        if int(sel, 16) != int(r["selector"], 16):
            print(f"#error {name}: selector {sel}, the ROM uses {r['selector']}")
        ret = ret.strip()
        names = [m for m in re.findall(r"__typeof__\(\w+\) (\w+);", fields)]
        if len(names) != len(r["args"]):
            print(f"#error {name}: {len(names)} arguments, the ROM passes {len(r['args'])}")
            continue
        print(f"static void check_{name}({params}) {{")
        print(f"    struct {{ {fields} }} __attribute__((__packed__)) _pb;")
        for n, (off, size) in zip(names, r["args"]):
            print(f"    _Static_assert(__builtin_offsetof(__typeof__(_pb), {n}) == {off} && "
                  f"sizeof(_pb.{n}) == {size}, \"{name}: {n}\");")
        if ret == "void":
            if r["result"]:
                print(f"#error {name}: no result, the ROM returns {r['result']} bytes")
        else:
            print(f"    _Static_assert(sizeof({ret}) == {r['result']}, \"{name}: result\");")
        print("    (void)_pb;")
        print("}")
print(f"/* {seen} calls checked */")
