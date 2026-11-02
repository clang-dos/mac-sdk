#!/usr/bin/env python3
"""Print a C file that takes the address of every 68k register-trap
inline function, so the compiler generates code for all of them (and
checks every register constraint). tests/run.sh compiles it for 68k."""
import os
import re

root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "include", "mv")
names = []
for f in sorted(os.listdir(root)):
    text = open(os.path.join(root, f)).read()
    names += re.findall(r"static __inline__ __attribute__\(\(__always_inline__\)\) "
                        r"[^(]*?\b(\w+)\(", text)
print("#include <Multiverse.h>")
print("void *const inline_traps[] = {")
for n in names:
    print(f"    (void *){n},")
print("};")
