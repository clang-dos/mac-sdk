#!/usr/bin/env python3
"""Compare the 68k code of every call in include/ with the inline code in
a copy of Apple's MPW C interfaces (CIncludes), such as the June 1992
interfaces on the Developer CD Series.

    python3 tools/check-mpw.py path/to/CIncludes [more dirs...]

Apple's headers are not part of this repository; point the tool at your
own copy. For each function both declare, it compares the trap word and
the words around it (selector loads, register moves). It prints the
calls that differ and, with -m, the ones the MPW interfaces declare
with inline code that the SDK lacks.
"""
import argparse
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

HEX = r"0x[0-9A-Fa-f]+"


def words_of(text):
    return [int(w, 16) & 0xFFFF for w in re.findall(HEX, text)]


def trap_names(dirs):
    """_Name -> word, from #define _Name 0xAxxx lines (Traps.h)."""
    names = {}
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*.h")):
            for m in re.finditer(r"#define\s+(_\w+)\s+(" + HEX + ")",
                                 open(f, encoding="mac_roman").read()):
                names[m.group(1)] = int(m.group(2), 16)
    return names


def enum_values(dirs):
    """Name -> value for simple enum constants (Name = number)."""
    vals = {}
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*.h")):
            src = open(f, encoding="mac_roman").read()
            for m in re.finditer(r"\b([A-Za-z]\w*)\s*=\s*(-?(?:0x[0-9A-Fa-f]+|\d+))\b", src):
                vals.setdefault(m.group(1), int(m.group(2), 0))
    return vals


def word_value(t, names):
    """The 16-bit word an inline code item stands for: a number, a trap
    name (_Pack14), an enum constant, or a sum of them (1+0x500)."""
    total = 0
    for part in t.replace(" ", "").split("+"):
        if re.fullmatch(r"-?(0x[0-9A-Fa-f]+|\d+)", part):
            total += int(part, 0)
        elif part in names:
            total += names[part]
        else:
            return None
    return total & 0xFFFF


def normalize(ws):
    """(trap, selector) pairs: each A-line word with the constant loaded
    just before it, whatever instruction loaded it (moveq, move.w #,
    move.l #, clr.w -(sp), move.w #,-(sp))."""
    out, i, sel = [], 0, None
    while i < len(ws):
        w = ws[i]
        if 0xA000 <= w <= 0xAFFF:
            out.append((w, sel)); sel = None; i += 1; continue
        if w & 0xF100 == 0x7000:                      # moveq #n,d0
            sel = (w & 0xFF) - (0x100 if w & 0x80 else 0); i += 1
        elif w in (0x303C, 0x3F3C) and i + 1 < len(ws):   # move.w #n,d0 / -(sp)
            v = ws[i + 1]; sel = v - 0x10000 if v & 0x8000 else v; i += 2
        elif w in (0x203C, 0x2F3C) and i + 2 < len(ws):   # move.l #n
            v = (ws[i + 1] << 16) | ws[i + 2]
            sel = v - (1 << 32) if v & 0x80000000 else v; i += 3
        elif w in (0x4267, 0x42A7):                   # clr.w/clr.l -(sp)
            sel = 0; i += 1
        else:
            i += 1
    return out


def loose(ws):
    """normalize(), ignoring the parameter-size byte of a _SoundDispatch
    selector, which the 1992 interfaces leave zero for some calls and
    later ones (and the ROM's glue) fill in."""
    return [(t, s & 0x00FFFFFF if t == 0xA800 and s is not None else s)
            for t, s in normalize(ws)]


def mpw_inlines(dirs):
    """name -> (words, file) for every MPW declaration with inline code."""
    out = {}
    names = {**enum_values(dirs), **trap_names(dirs)}
    for d in dirs:
        for f in sorted(glob.glob(os.path.join(d, "*.h"))):
            src = open(f, encoding="mac_roman").read()
            src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
            # pascal T Name(args) = 0xA000; or = {0x...,0x...};
            for m in re.finditer(
                    r"\b(\w+)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*=\s*"
                    r"(\{[^}]*\}|" + HEX + r")\s*;", src):
                name, code = m.group(1), m.group(3)
                items = [t.strip() for t in code.strip("{} ").split(",")]
                w = []
                for t in items:
                    v = word_value(t, names)
                    if v is None:
                        w = None
                        break
                    w.append(v)
                if w:
                    out.setdefault(name, (w, os.path.basename(f)))
    return out


def sdk_inlines():
    """name -> words for every SDK function with 68k code."""
    out = {}
    for f in glob.glob(os.path.join(ROOT, "include", "mv", "*.h")):
        src = open(f).read()
        for m in re.finditer(r"\b(\w+)\s*\([^;{\n]*\)\s*M68K_INLINE\(([^)]*)\)", src):
            out[m.group(1)] = words_of(m.group(2))
        # register-based traps: static inline functions with .short words
        for m in re.finditer(
                r"static __inline__[^\n]*?\b(\w+)\s*\([^)]*\)\s*\{(.*?)\n\}", src, re.S):
            body = m.group(2)
            shorts = re.findall(r"\.short ((?:" + HEX + r"\s*,?\s*)+)", body)
            if shorts:
                out.setdefault(m.group(1), words_of(" ".join(shorts)))
    # old routine names and other aliases: #define Old(args) New(args)
    for f in glob.glob(os.path.join(ROOT, "include", "mv", "*.h")):
        for m in re.finditer(r"#define (\w+)(?:\([^)]*\))? \(?(\w+)\b", open(f).read()):
            if m.group(2) in out:
                out.setdefault(m.group(1), out[m.group(2)])
    return out


def traps(ws):
    return [w for w in ws if 0xA000 <= w <= 0xAFFF]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("-m", "--missing", action="store_true",
                    help="also list MPW calls the SDK does not declare with 68k code")
    a = ap.parse_args()
    mpw, sdk = mpw_inlines(a.dirs), sdk_inlines()
    same = differ = 0
    for name in sorted(mpw):
        if name not in sdk:
            continue
        mw, f = mpw[name]
        sw = sdk[name]
        if mw == sw or normalize(mw) == normalize(sw) or loose(mw) == loose(sw):
            same += 1
            continue
        differ += 1
        print(f"{name} ({f}): MPW {' '.join('%04X' % w for w in mw)}"
              f"  SDK {' '.join('%04X' % w for w in sw)}")
    missing = [n for n in sorted(mpw) if n not in sdk]
    if a.missing:
        for n in missing:
            mw, f = mpw[n]
            print(f"missing: {n} ({f}) {' '.join('%04X' % w for w in mw)}")
    print(f"check-mpw: {same} calls match, {differ} differ, "
          f"{len(missing)} MPW calls with inline code not in the SDK", file=sys.stderr)
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
