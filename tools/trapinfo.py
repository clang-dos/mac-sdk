#!/usr/bin/env python3
"""Extract each InterfaceLib function's 68k trap from its PowerPC glue.

    python3 tools/trapinfo.py ROM_OR_PEF > trapinfo.json

On System 7.x and Mac OS 8.0-8.1, most InterfaceLib exports are glue that
calls the 68k trap through the Mixed Mode Manager:

    CallUniversalProc(trap table entry, procInfo, args...)
    CallOSTrapUniversalProc(trap table entry, procInfo, args...)

The trap table entry is a low-memory address, which gives the trap
number; the procInfo gives the calling convention, the result size and
the size (and register) of each argument; a D0- or stack-dispatched call
passes its selector as the first argument. Pass the InterfaceLib PEF, or
an OldWorld ROM image that contains it.
"""
import json
import struct
import sys

import pefglue

CONV = {0: "pascal", 1: "C", 2: "register", 8: "d0-pascal",
        9: "d0-c", 12: "d1-pascal", 14: "stack-pascal", 15: "special"}
REGS = ["D0", "D1", "D2", "D3", "A0", "A1", "A2", "A3"]
SIZE = {0: 0, 1: 1, 2: 2, 3: 4}


def trap_of(addr):
    if 0x400 <= addr < 0x800 and addr % 4 == 0:
        return 0xA000 | ((addr - 0x400) // 4)
    if 0xE00 <= addr < 0x1E00 and addr % 4 == 0:
        return 0xA800 | ((addr - 0xE00) // 4)
    return None


def decode(info):
    conv = info & 15
    res = SIZE[(info >> 4) & 3]
    out = {"conv": CONV.get(conv, str(conv)), "result": res}
    if conv == 2:
        out["result_reg"] = REGS[(info >> 6) & 7] if res else None
        params = []
        v = info >> 11
        while v:
            params.append({"size": SIZE[v & 3], "reg": REGS[(v >> 2) & 7]})
            v >>= 5
        out["params"] = params
    else:
        params = []
        v = info >> 6
        while v:
            params.append({"size": SIZE[v & 3]})
            v >>= 2
        out["params"] = params
    return out


def find_interfacelib(blob):
    if blob[:8] == b"Joy!peff":
        return blob
    best = None
    pos = blob.find(b"Joy!peff")
    while pos >= 0:
        try:
            p = pefglue.Pef(blob[pos:])
            if "DrawString" in p.exports and "NewWindow" in p.exports:
                if best is None or len(p.exports) > len(best.exports):
                    best = p
        except Exception:
            pass
        pos = blob.find(b"Joy!peff", pos + 8)
    return best


def main():
    blob = open(sys.argv[1], "rb").read()
    p = find_interfacelib(blob)
    if not isinstance(p, pefglue.Pef):
        p = pefglue.Pef(p)
    out = {}
    for name in sorted(p.exports):
        r = p.code_of(name)
        g = pefglue.run_glue(*r) if r else None
        if not g:
            continue
        _, regs = g
        upp, info = regs.get(3), regs.get(4)
        if not (upp and info and upp.kind == "lowmem" and info.kind == "const"):
            continue
        trap = trap_of(upp.v)
        if trap is None:
            continue
        d = decode(info.v)
        d["trap"] = "0x%04X" % trap
        d["procinfo"] = "0x%08X" % info.v
        args = [regs.get(i) for i in range(5, 11)]
        if d["conv"] == "register":
            # Register params the glue fills with constants: the trap word
            # (OS traps get it in D1, with flag bits) or a selector.
            keep, kargs = [], []
            for prm, a in zip(d["params"], args):
                if a is not None and a.kind == "const":
                    if prm["reg"] == "D1" and (a.v & 0xF000) == 0xA000:
                        d["trap"] = "0x%04X" % (a.v & 0xFFFF)
                        continue
                    prm = dict(prm, value="0x%X" % a.v)
                keep.append(prm)
                kargs.append(a)
            d["params"], args = keep, kargs + [None] * 6
        if d["conv"] in ("d0-pascal", "d0-c", "d1-pascal", "stack-pascal") \
                and args[0] is not None and args[0].kind == "const":
            d["selector"] = "0x%X" % args[0].v
            d["selector_size"] = d["params"][0]["size"]
            d["params"] = d["params"][1:]
            args = args[1:]
        if d["conv"] != "register":
            # Stack arguments the glue fills with constants (a version
            # number, or a routine code for a shared selector).
            d["params"] = [dict(prm, value="0x%X" % a.v)
                           if a is not None and a.kind == "const" else prm
                           for prm, a in zip(d["params"], args + [None] * 6)]
        out[name] = d
    json.dump(out, sys.stdout, indent=1, sort_keys=True)
    print(f"trapinfo: {len(out)} functions", file=sys.stderr)


if __name__ == "__main__":
    main()
