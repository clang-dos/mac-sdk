#!/usr/bin/env python3
"""Turn C prototypes into definitions for defs/, with the 68k trap details
taken from data/trapinfo.json (what the ROM's InterfaceLib glue does).

    python3 tools/add-protos.py defs/Foo.yaml < protos.h

Each input line is a prototype as in Apple's documentation:

    pascal OSErr NewGestaltValue(OSType selector, long newValue);

For each one, the tool looks up the function in data/trapinfo.json and
writes its trap word, dispatcher and selector, or the register of each
argument for register-based traps. It checks every argument's size
against the procInfo and refuses a mismatch. Functions with no glue
entry (native-only, or 68k glue we do not know) get no 68k trap: they
are PowerPC-only until someone adds the trap. Lines starting with //
are copied as comments; a line `# Title` starts a section comment.

Dispatchers the definitions do not name yet are added under the names
in DISPATCHER_NAMES.
"""
import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DISPATCHER_NAMES = {
    0xA82A: "ComponentDispatch", 0xAA54: "TSMDispatch",
    0xA82F: "Pack13", 0xAADB: "CursorDeviceDispatch",
    0xA815: "SCSIDispatch", 0xA88F: "OSDispatch", 0xA8B5: "ScriptUtil",
    0xAA53: "DictionaryDispatch", 0xA825: "MenuDispatch",
    0xA9C9: "SysErrorDispatch", 0xA82B: "Pack9", 0xA08B: "CommToolboxDispatch",
    0xA06E: "SlotManager", 0xA08F: "DeferredTask", 0xA0AC: "FSMDispatch",
    0xA0DD: "PPCDispatch", 0xA05D: "MemoryDispatch", 0xA08D: "DebugUtil",
    0xA085: "PowerDispatch", 0xA0AE: "VADBProc", 0xA089: "SCSIAtomic",
    0xA0BD: "FlushCodeCacheRange",
}

TYPE_MAP = {
    "long": "int32_t", "signed long": "int32_t", "unsigned long": "uint32_t",
    "short": "INTEGER", "signed short": "INTEGER",
    "unsigned short": "uint16_t", "int": "int32_t", "unsigned int": "uint32_t",
    "unsigned char": "uint8_t", "signed char": "int8_t", "char": "char",
    "void": "void",
}


def load_defs():
    """Return (dispatchers by trap, type sizes, defined names)."""
    disp, sizes, names = {}, {
        "uint8_t": 1, "int8_t": 1, "char": 1, "uint16_t": 2, "int16_t": 2,
        "uint32_t": 4, "int32_t": 4, "uint64_t": 8, "int64_t": 8, "bool": 1,
        "void": 0, "Point": 4, "ProcPtr": 4, "double": 8}, set()
    typedefs = []
    for f in sorted(os.listdir(os.path.join(ROOT, "defs"))):
        if not f.endswith(".yaml"):
            continue
        for it in yaml.safe_load(open(os.path.join(ROOT, "defs", f))) or []:
            only = it.get("only-for")
            if only and "cincludes" not in str(only).lower():
                continue
            for k, v in it.items():
                if not isinstance(v, dict):
                    continue
                if v.get("name"):
                    names.add(v["name"])
                    names.update(v.get("variants") or [])
                if k == "dispatcher":
                    disp[v["trap"]] = v
                elif k == "typedef":
                    typedefs.append((v["name"], v["type"]))
                elif k == "funptr":
                    sizes[v["name"]] = 4
                    base = re.sub(r"(ProcPtr|UPP)$", "", v["name"])
                    sizes[base + "UPP"] = sizes[base + "ProcPtr"] = 4
                elif k in ("struct", "union") and v.get("size"):
                    sizes[v["name"]] = v["size"]
                elif k == "enum" and v.get("name"):
                    sizes.setdefault(v["name"], 2)
    for _ in range(4):
        for n, t in typedefs:
            s = size_of(t, sizes)
            if s is not None:
                sizes[n] = s
    return disp, sizes, names


def size_of(t, sizes):
    t = t.replace("const ", "").strip()
    if "*" in t or "[" in t:
        return 4
    return sizes.get(t)


def parse(line):
    m = re.match(r"\s*(pascal\s+)?(.+?)\s*\b([A-Za-z_]\w*)\s*\((.*)\)\s*;?\s*$",
                 line)
    if not m:
        raise ValueError(f"cannot parse: {line}")
    ret = norm_type(m.group(2))
    args = []
    params = m.group(4).strip()
    if params and params != "void":
        for i, p in enumerate(params.split(",")):
            p = p.strip()
            if p == "...":
                args.append({"type": "..."})
                continue
            am = re.match(r"(.+?)\s*\b([A-Za-z_]\w*)\s*(\[\s*\d*\s*\])?$", p)
            if not am or am.group(1).strip() in ("", "const", "unsigned"):
                args.append({"name": f"arg{i}", "type": norm_type(p)})
            else:
                t = norm_type(am.group(1))
                if am.group(3):
                    t += "*"
                args.append({"name": am.group(2), "type": t})
    return {"name": m.group(3), "return": ret, "args": args,
            "pascal": bool(m.group(1))}


def norm_type(t):
    t = " ".join(t.replace("*", " * ").split())
    stars = t.count("*")
    base = t.replace("*", "").strip()
    const = base.startswith("const ")
    if const:
        base = base[6:]
    base = TYPE_MAP.get(base, base)
    return ("const " if const else "") + base + "*" * stars


def main():
    out_path = sys.argv[1]
    info = json.load(open(os.path.join(ROOT, "data", "trapinfo.json")))
    disp, sizes, names = load_defs()
    items, new_disp, report = [], {}, []
    pending_comment = None
    for line in sys.stdin:
        line = line.rstrip()
        if not line.strip():
            continue
        if line.startswith("#"):
            pending_comment = line.lstrip("# ").strip()
            continue
        if line.startswith("//"):
            pending_comment = (pending_comment + "\n" if pending_comment
                               else "") + line[2:].strip()
            continue
        p = parse(line)
        name = p["name"]
        if name in names:
            report.append(f"{name}: already defined, skipped")
            continue
        fun = {"name": name}
        if p["return"] != "void":
            fun["return"] = p["return"]
        if p["args"]:
            fun["args"] = [dict(a) for a in p["args"]]
        if not p["pascal"]:
            fun["callconv"] = "C"
        if pending_comment:
            fun["comment"] = pending_comment
            pending_comment = None
        o = info.get(name)
        status = "PowerPC only (no glue entry)"
        if o:
            status = attach_trap(fun, p, o, disp, new_disp, sizes)
        report.append(f"{name}: {status}")
        items.append({"function": fun})
    head = []
    for trap, d in sorted(new_disp.items()):
        head.append({"dispatcher": d})
        disp[trap] = d
    with open(out_path, "a", encoding="utf-8") as f:
        for it in head + items:
            f.write("\n# ####\n\n")
            f.write(yaml.safe_dump([it], sort_keys=False, width=100))
    print("\n".join(report), file=sys.stderr)


def attach_trap(fun, p, o, disp, new_disp, sizes):
    trap = int(o["trap"], 16)
    args = [a for a in p["args"] if a["type"] != "..."]
    asizes = [size_of(a["type"], sizes) for a in args]
    rsize = size_of(p["return"], sizes) if p["return"] != "void" else 0
    if o["conv"] == "register":
        consts = [prm for prm in o["params"] if "value" in prm]
        params = [prm for prm in o["params"] if "value" not in prm]
        if len(params) > len(args):
            return f"NOT ADDED to 68k: glue passes {len(params)} registers"
        extra = args[len(params):]
        for a, prm, s in zip(args, params, asizes):
            if s is not None and min(s, 4) != prm["size"] and \
                    not (s == 1 and prm["size"] == 2):
                return (f"68k skipped: {a['name']} is {s} bytes, glue "
                        f"passes {prm['size']}")
        if extra:
            return f"68k skipped: {len(extra)} output argument(s), registers unknown"
        if bool(o.get("result_reg")) != bool(rsize):
            return "68k skipped: result does not match the glue"
        for fa, prm in zip(fun.get("args", []), params):
            fa["register"] = prm["reg"]
        if o.get("result_reg"):
            fun["returnreg"] = o["result_reg"]
        if not consts:
            fun["trap"] = trap
            return f"register trap {trap:#06x}"
        # The glue loads a selector into a register: use the dispatcher
        # when one is named for it, otherwise spell out the instructions.
        if len(consts) == 1 and consts[0]["reg"] == "D0":
            sel = int(consts[0]["value"], 16)
            sel = sel - (1 << 32) if sel & 0x80000000 else sel
            for d in list(disp.values()) + list(new_disp.values()):
                if d["trap"] & 0xF8FF == trap & 0xF8FF and d.get(
                        "selector-location") in ("D0W", "D0L"):
                    fun["dispatcher"] = d["name"]
                    fun["selector"] = sel
                    fun["trap"] = trap
                    return f"register {d['name']} selector {sel}"
        words = []
        for c in consts:
            v = int(c["value"], 16)
            n = int(c["reg"][1])
            sv = v - (1 << 32) if v & 0x80000000 else v
            if c["reg"][0] == "D" and -128 <= sv <= 127:
                words.append(0x7000 | n << 9 | (v & 0xFF))
            elif c["reg"][0] == "D":
                words += [0x203C | n << 9, v >> 16, v & 0xFFFF]
            else:
                words += [0x207C | n << 9, v >> 16, v & 0xFFFF]
        fun["m68k-inline"] = words + [trap]
        return "register trap " + ", ".join(f"{w:#06x}" for w in words + [trap])
    # Stack based: compare sizes (a byte goes as 2 on the stack in the
    # procInfo's view only for Pascal? No: procInfo records 1).
    consts = []
    params = list(o["params"])
    while params and "value" in params[-1] and len(params) > len(args):
        consts.insert(0, params.pop())
    osz = [prm["size"] for prm in params]
    mine = [min(s, 4) if s is not None else None for s in asizes]
    if None in mine:
        return f"68k skipped: unknown size in {mine}"
    if mine != osz:
        return f"68k skipped: argument sizes {mine}, glue says {osz}"
    if (rsize and min(rsize, 4)) != o["result"] and not (
            rsize == 1 and o["result"] == 1):
        return f"68k skipped: result {rsize} bytes, glue says {o['result']}"
    if "selector" in o:
        d = disp.get(trap) or new_disp.get(trap)
        if not d:
            loc = {("d0-pascal", 2): "D0W", ("d0-pascal", 4): "D0L",
                   ("stack-pascal", 2): "StackW",
                   ("stack-pascal", 4): "StackL"}.get(
                       (o["conv"], o["selector_size"]))
            if not loc:
                return f"68k skipped: dispatch {o['conv']}"
            d = {"name": DISPATCHER_NAMES.get(trap, f"Dispatch{trap:04X}"),
                 "trap": trap, "selector-location": loc}
            new_disp[trap] = d
        fun["dispatcher"] = d["name"]
        fun["selector"] = int(o["selector"], 16)
        if consts:
            return push_consts(fun, consts, d, trap)
        return f"{d['name']} selector {o['selector']}"
    if consts:
        return push_consts(fun, consts, None, trap)
    fun["trap"] = trap
    return f"trap {trap:#06x}"


def push_consts(fun, consts, d, trap):
    """The glue pushes constant trailing arguments: spell out the code."""
    words = []
    for c in consts:
        v = int(c["value"], 16)
        words += [0x3F3C, v & 0xFFFF] if c["size"] <= 2 else \
            [0x2F3C, v >> 16, v & 0xFFFF]
    if d:
        sel = fun.pop("selector")
        fun.pop("dispatcher")
        loc = d["selector-location"]
        if loc.startswith("StackW"):
            words += [0x3F3C, sel & 0xFFFF]
        elif loc == "StackL":
            words += [0x2F3C, sel >> 16 & 0xFFFF, sel & 0xFFFF]
        elif loc == "D0W":
            words += [0x303C, sel & 0xFFFF]
        else:
            words += [0x203C, sel >> 16 & 0xFFFF, sel & 0xFFFF]
    fun["m68k-inline"] = words + [trap]
    return "pushes constants: " + ", ".join(f"{w:#06x}" for w in fun["m68k-inline"])


if __name__ == "__main__":
    main()
