#!/usr/bin/env python3
"""Print a C file that takes the address of every 68k register-trap
inline function, and of the inline C glue, so the compiler generates code for all of them (and
checks every register constraint). tests/run.sh compiles it for 68k."""
import os
import re

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "include", "mv")
# (name, condition): functions inside "#if TARGET_API_MAC_CARBON" (or its
# negation) keep that condition in the output.
names = []
pat = re.compile(r"static __inline__ (?:__attribute__\(\(__always_inline__\)\) )?"
                 r"[^(]*?\b(\w+)\(")
for f in sorted(os.listdir(root)):
    stack = []
    for line in open(os.path.join(root, f)):
        if line.startswith("#if"):
            stack.append(line.split(None, 1)[1].strip() if "TARGET_API_MAC_CARBON" in line else None)
        elif line.startswith("#endif"):
            stack.pop()
        else:
            m = pat.match(re.sub(r"^(MAC_SINCE(?:_GESTALT)?\([^()]*\) |MAC_COLOR_QD )+", "", line))
            if m:
                conds = [c for c in stack if c]
                names.append((m.group(1), conds[-1] if conds else None))
print("#include <Multiverse.h>")
print("void *const inline_traps[] = {")
for n, cond in names:
    if cond:
        print(f"#if {cond}")
    print(f"    (void *){n},")
    if cond:
        print("#endif")
print("};")
