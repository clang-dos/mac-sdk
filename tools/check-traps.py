#!/usr/bin/env python3
"""Check the 68k code of every call in include/mv against what the ROM's
PowerPC glue does (data/trapinfo.json): the trap word and the selector.

    python3 tools/check-traps.py [-v]

Prints each mismatch and a summary; exits 1 if any call disagrees.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def words_by_function():
    """Map function name -> list of 68k code words, from the headers."""
    out = {}
    inc = os.path.join(ROOT, "include", "mv")
    for f in sorted(os.listdir(inc)):
        text = open(os.path.join(inc, f)).read()
        for m in re.finditer(r"\b(\w+)\([^;{\n]*\)\s*M68K_INLINE\(([^)]*)\);", text):
            out[m.group(1)] = [int(w, 16) for w in m.group(2).split(",")]
        for m in re.finditer(
                r"__always_inline__\)\) [^(]*?\b(\w+)\([^)]*\) \{.*?"
                r"__asm__ __volatile__\(\"\.short ([^\"]*)\"", text, re.S):
            out[m.group(1)] = [int(w, 16) for w in m.group(2).split(",")]
    return out


def immediates(words):
    """The immediate values the code loads or pushes, in order."""
    vals, i = [], 0
    while i < len(words) - 1:
        w = words[i]
        if w & 0xF100 == 0x7000:                       # moveq #n,Dn
            vals.append(((w & 0xFF) ^ 0x80) - 0x80)
            i += 1
        elif w in (0x303C, 0x3F3C) or w & 0xF1FF == 0x303C:   # move.w #
            vals.append(words[i + 1])
            i += 2
        elif w in (0x203C, 0x2F3C) or w & 0xF1FF in (0x203C, 0x207C):
            vals.append(words[i + 1] << 16 | words[i + 2])
            i += 3
        else:
            i += 1
    return vals


def main():
    verbose = "-v" in sys.argv
    info = json.load(open(os.path.join(ROOT, "data", "trapinfo.json")))
    code = words_by_function()
    ok, bad, skipped = 0, [], 0
    for name, o in sorted(info.items()):
        w = code.get(name)
        if not w:
            skipped += 1
            continue
        want_trap = int(o["trap"], 16)
        problems = []
        traps = [x for x in w if x & 0xF000 == 0xA000]
        if want_trap not in traps:
            problems.append(f"trap {[hex(x) for x in traps]}, ROM uses {want_trap:#06x}")
        sel = o.get("selector")
        if sel is None and o["conv"] == "register":
            consts = [p["value"] for p in o["params"] if "value" in p]
            sel = consts[0] if consts else None
        if sel is not None:
            want = int(sel, 16)
            imms = immediates(w)
            if not any((v & 0xFFFFFFFF) == want or (v & 0xFFFF) == (want & 0xFFFF)
                       for v in imms):
                problems.append(f"selector {[hex(v & 0xFFFFFFFF) for v in imms]}, "
                                f"ROM uses {sel}")
        if problems:
            bad.append(f"{name}: " + "; ".join(problems))
        else:
            ok += 1
            if verbose:
                print(f"{name}: ok")
    for b in bad:
        print(b)
    print(f"check-traps: {ok} calls match the ROM, {len(bad)} differ, "
          f"{skipped} glue entries not declared with 68k code", file=sys.stderr)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
