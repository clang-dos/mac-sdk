#!/usr/bin/env python3
"""Record the argument blocks of the Communications Toolbox calls from
their PowerPC glue in the ROM's InterfaceLib.

    python3 tools/blockinfo.py ROM > data/blockinfo.json

On 68k these calls take their arguments as a block laid out like Pascal
arguments on the stack under a selector word, with A0 pointing at it,
and call _CommToolboxDispatch (0xA08B). The PowerPC glue builds the
same block in its stack frame and passes it to the 68k trap. For each
call this records the selector, the offset and size of each argument
in the block (relative to the selector word) and the result size.

It disassembles with llvm-mc, so it needs an LLVM with the PowerPC
target. tests/blocks.py turns the result into static assertions on the
headers' argument blocks.
"""
import json
import re
import subprocess
import sys

import trapinfo


def disassemble(code, start, n=48):
    data = code[start:start + 4 * n]
    text = subprocess.run(
        ["llvm-mc", "--disassemble", "-triple=powerpc"],
        input=" ".join("0x%02x" % b for b in data),
        capture_output=True, text=True, check=True).stdout.splitlines()[1:]
    out = []
    for i, line in enumerate(text):
        line = line.strip()
        m = re.match(r"bl\s+\.([+-]\d+)", line)
        if m:
            line = "bl 0x%x" % (start + 4 * i + int(m.group(1)))
        out.append(line)
        if line == "blr":
            break
    return out


def helper_info(code, addr, trap):
    """If the helper at addr calls CallOSTrapUniversalProc for `trap` (whose
    trap table entry it loads), return the result size from its procInfo."""
    text = disassemble(code, addr, 16)
    entry = 0x400 + 4 * (trap & 0xFF) if trap < 0xA800 else 0xE00 + 4 * (trap & 0x3FF)
    if not any(re.fullmatch(r"lwz \d+, %d\(0\)" % entry, l) for l in text):
        return None
    hi = lo = None
    for l in text:
        m = re.fullmatch(r"lis 0, (\d+)", l)
        if m:
            hi = int(m.group(1))
        m = re.fullmatch(r"addic 4, (?:0|4), (-?\d+)", l)
        if m:
            lo = int(m.group(1))
    if hi is None or lo is None:
        return None
    info = (hi << 16) + lo
    return {0: 0, 1: 1, 2: 2, 3: 4}[(info >> 4) & 3]


def block_call(code, addr, helpers):
    lines = disassemble(code, addr)
    consts, stores = {}, set()
    sel = base = helper = frame = None
    post = []
    for i, line in enumerate(lines):
        m = re.match(r"stwu 1, -(\d+)\(1\)$", line)
        if m:
            frame = int(m.group(1))
        m = re.match(r"li (\d+), (\d+)$", line)
        if m:
            consts[m.group(1)] = int(m.group(2))
        m = re.match(r"st([whb]) (\d+), (\d+)\(1\)$", line)
        if m and helper is None:
            kind, reg, off = m.group(1), m.group(2), int(m.group(3))
            if kind == "h" and consts.get(reg, 0) > 0x100:
                sel, base = consts[reg], off
            else:
                stores.add((off, {"w": 4, "h": 2, "b": 1}[kind]))
        m = re.match(r"bl 0x(\w+)$", line)
        if m and helper is None:
            helper, post = int(m.group(1), 16), lines[i + 1:]
    if sel is None or helper is None or frame is None:
        return None
    if helper not in helpers:
        helpers[helper] = helper_info(code, helper, 0xA08B)
    result = helpers[helper]
    if result is None:
        return None
    # The trap returns a long in D0; the glue narrows it to the result type.
    if any(l.startswith("extsh 3, 3") for l in post):
        result = 2
    elif any(l.startswith("clrlwi\t3, 3, 24") for l in post):
        result = 1
    args = sorted((off - base, size) for off, size in stores if base < off < frame)
    return {"selector": "0x%X" % sel, "args": args, "result": result}


def main():
    blob = open(sys.argv[1], "rb").read()
    p = trapinfo.find_interfacelib(blob)
    out, helpers = {}, {}
    for name in sorted(p.exports):
        r = p.code_of(name)
        if not r:
            continue
        b = block_call(r[0], r[1], helpers)
        if b:
            out[name] = b
    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    print(f"blockinfo: {len(out)} functions", file=sys.stderr)


if __name__ == "__main__":
    main()
