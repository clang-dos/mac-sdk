#!/usr/bin/env python3
"""Generate the classic Mac OS headers from the API definitions in defs/.

    python3 tools/gen-headers.py [--defs defs] [--out include]

defs/*.yaml describe the Toolbox: types, constants, structs, traps and
the shared-library functions. They come from Multiversal Interfaces (see
defs/COPYING.multiversal), in the format its README documents; only the
data is used here.

The output is one header per definition file, under include/mv/, in
dependency order, plus Multiverse.h that includes them all and the
headers that Apple's Universal Interfaces name (Quickdraw.h, Windows.h,
...), which include Multiverse.h. The same headers work for clang's
m68k-apple-macos and powerpc-apple-macos9 targets:

  - On 68k, Toolbox calls are `pascal` functions with the trap words as
    __attribute__((raw_inline(...))). Register-based traps (most OS
    traps) become static inline functions that load the registers and
    emit the trap words with inline asm.
  - On PowerPC, every call is a plain `pascal` declaration that the
    linker imports from InterfaceLib and the other shared libraries.
  - Structs use 68k alignment (#pragma options align=mac68k) on both,
    like Apple's headers, except those marked `align: power`.
"""
import argparse
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FILTER = "cincludes"
BUILTIN = {"uint8_t", "uint16_t", "uint32_t", "uint64_t", "int8_t",
           "int16_t", "int32_t", "int64_t", "char", "ProcPtr", "void",
           "const", "bool", "sizeof", "double", "float", "long", "short",
           "int", "unsigned", "signed", "struct", "union", "enum"}
TYPE_SIZE = {"uint8_t": 1, "uint16_t": 2, "uint32_t": 4, "uint64_t": 8,
             "int8_t": 1, "int16_t": 2, "int32_t": 4, "int64_t": 8,
             "char": 1, "Point": 4, "ProcPtr": 4, "void": 0, "double": 8}

# Headers from Apple's Universal Interfaces that programs include. Each
# one includes the whole set.
APPLE_NAMES = [
    "AppleEvents", "Aliases", "CodeFragments", "Components", "CursorDevices", "DatabaseAccess",
    "ConditionalMacros", "Connections", "CommResources", "CTBUtilities", "Displays", "ADSP", "ENET", "FileTransfers", "Terminals", "AppleTalk", "Dictionary", "MIDI", "Power", "PPCToolbox", "SCSI", "Slots", "TextServices",
    "Appearance", "Collections", "ControlDefinitions", "ContextualMenu", "Controls", "Devices", "Dialogs", "DiskInit", "Drag", "DriverServices", "Multiprocessing", "Threads", "TextCommon", "TextEncodingConverter", "UnicodeConverter", "URLAccess", "Keychain",
    "Movies", "ImageCompression", "QuickTimeComponents", "MediaHandler", "ImageCodec", "MoviesFormat",
    "Errors", "Events", "Files", "Finder", "FixMath", "Folders", "Fonts",
    "Gestalt", "Icons", "Interrupts", "Kernel", "Lists", "LowMem",
    "MacErrors", "MacMemory", "MacTypes", "MacWindows", "Memory", "Menus",
    "MixedMode", "NameRegistry", "Navigation", "Notification",
    "NumberFormatting", "OSUtils", "Packages", "PCI", "Printing",
    "Processes", "Quickdraw", "QuickdrawText", "Resources", "Retrace",
    "Scrap", "Script", "SegLoad", "Serial", "ShutDown", "Sound",
    "StandardFile", "Strings", "TextEdit", "TextUtils", "Timer",
    "ToolUtils", "Traps", "Types", "Windows",
]


def listify(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def main_elem(item):
    for k, v in item.items():
        if k not in ("only-for", "not-for", "api"):
            return k, v
    return None, None


def hexlit(n, bits=16):
    if isinstance(n, int):
        return "0x%0*X" % (bits // 4, n & ((1 << bits) - 1))
    return str(n)


def ctype_of(t):
    """The definitions use int32_t and uint32_t for 32-bit values. Apple's
    headers, and so all classic Mac code, use long (32 bits on both CPUs),
    and long * does not convert to int *, so use long here too."""
    t = re.sub(r"\buint32_t\b", "unsigned long", t)
    return re.sub(r"\bint32_t\b", "long", t)


def decl(ctype, name):
    """Declare `name` with type `ctype` ('Ptr', 'Str255', 'char[4]')."""
    ctype = ctype_of(ctype)
    if not name or ctype == "...":
        return ctype
    m = re.match(r"(const +)?([A-Za-z0-9_]+(?: +[A-Za-z0-9_]+)*) *((?:\* *)*)(.*)",
                 ctype)
    if not m:
        raise ValueError(f"cannot declare {name!r} of type {ctype!r}")
    const, base, stars, rest = m.groups()
    return f"{const or ''}{base} {stars.replace(' ', '')}{name}{rest}"


def comment(text, out):
    for line in str(text).rstrip().splitlines():
        out.append("// " + line.rstrip())


class Header:
    def __init__(self, path):
        self.name = os.path.splitext(os.path.basename(path))[0]
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        self.items = []
        for item in data:
            only = [x.lower() for x in listify(item.get("only-for"))]
            not_ = [x.lower() for x in listify(item.get("not-for"))]
            if (only and FILTER not in only) or FILTER in not_:
                continue
            self.items.append(item)
        self.declared, self.required = set(), set()
        for item in self.items:
            key, v = main_elem(item)
            if not isinstance(v, dict):
                continue
            if v.get("name"):
                self.declared.add(v["name"])
            if key == "enum":
                for val in v["values"]:
                    self.declared.add(val["name"])
                    self.need(val.get("value"))
            elif key == "typedef":
                self.need(v["type"])
            elif key == "define":
                self.need(v.get("value"))
            elif key in ("struct", "union"):
                self.need_members(v.get("members") or [])
            elif key in ("function", "funptr"):
                self.need(v.get("return"))
                for a in v.get("args") or []:
                    self.need(a["type"])
                for n in v.get("m68k-needs") or []:
                    self.need(n)
                self.declared.update(v.get("variants") or [])
                if key == "funptr":
                    base = re.sub(r"(ProcPtr|UPP)$", "", v["name"])
                    self.declared.update([base + "UPP", base + "ProcPtr"])
        self.required -= self.declared
        self.includes = set()

    def need(self, text):
        if text is None:
            return
        t = re.sub(r"'[^']+'", "", str(text))
        t = re.sub(r'"(?:[^"\\]|\\.)*"', "", t)
        t = re.sub(r"\b(struct|union|enum)\s+\w+", "", t)  # tags need nothing
        for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", t):
            if w not in BUILTIN:
                self.required.add(w)

    def need_members(self, members):
        for m in members:
            self.need(m.get("type"))
            self.need(m.get("common"))
            self.need_members(m.get("struct") or [])
            self.need_members(m.get("union") or [])


class Generator:
    def __init__(self, headers):
        self.headers = headers
        self.byname = {}          # declared name -> item
        self.sizes = dict(TYPE_SIZE)
        self.glue = []            # functions with no trap on 68k
        for h in headers.values():
            for item in h.items:
                _, v = main_elem(item)
                if isinstance(v, dict) and v.get("name"):
                    self.byname[v["name"]] = item

    def size_of(self, t):
        if not t:
            return None
        if t in self.sizes:
            return self.sizes[t]
        if re.search(r"[*\[\]]", t):
            return 4
        return None

    # -- items ---------------------------------------------------------

    def members(self, members, out):
        for m in members:
            sub = m.get("struct") or m.get("union")
            if sub:
                kind = "struct" if m.get("struct") else "union"
                out.append(f"{kind} {{")
                self.members(sub, out)
                out.append(f"}} {m['name']};")
            elif m.get("common"):
                common = self.byname[m["common"]]["common"]
                self.members(common["members"], out)
            else:
                line = decl(m["type"], m["name"]) + ";"
                if m.get("comment"):
                    line += " /* " + " ".join(
                        str(m["comment"]).split()).replace("*/", "* /") + " */"
                out.append("    " + line)

    def enum(self, v, out):
        out.append("typedef enum {" if v.get("name") else "enum {")
        for val in v["values"]:
            line = "    " + val["name"]
            if val.get("value") is not None:
                line += " = " + str(val["value"])
            line += ","
            if val.get("comment"):
                line += " /* " + " ".join(
                    str(val["comment"]).split()).replace("*/", "* /") + " */"
            out.append(line)
            for old in listify(val.get("old_name")):
                out.append("#if OLDROUTINENAMES")
                out.append(f"#define {old} {val['name']}")
                out.append("#endif")
        out.append(f"}} {v['name']};" if v.get("name") else "};")

    def typedef(self, v, out):
        out.append("typedef " + decl(v["type"], v["name"]) + ";")
        sz = self.size_of(v["type"])
        if sz is not None:
            self.sizes[v["name"]] = sz

    def struct(self, kind, v, out):
        name = v["name"]
        out.append(f"typedef {kind} {name} {name};")
        if v.get("members") is None:
            return
        power = v.get("align") == "power"
        if power:
            out.append("#pragma options align=power")
        out.append(f"{kind} {name} {{")
        self.members(v["members"], out)
        out.append("};")
        if power:
            out.append("#pragma options align=reset")

    def lowmem(self, v, out):
        addr = hexlit(v["address"], 32)
        m = re.match(r"^(.*)\[[^\[\]]*\]$", v["type"])
        if m:
            out.append(f"#define LMGet{v['name']}() (({ctype_of(m.group(1))} *){addr})")
            out.append(f"#define LMSet{v['name']}(val) BlockMoveData((const void *)(val), "
                       f"(void *){addr}, sizeof({ctype_of(v['type'])}))")
        else:
            e = f"(*({ctype_of(v['type'])} *){addr})"
            out.append(f"#define LMGet{v['name']}() {e}")
            out.append(f"#define LMSet{v['name']}(val) ({e} = (val))")

    def procinfo(self, ret, args):
        def enc(t):
            sz = self.size_of(t)
            return 0 if not sz else (3 if sz >= 4 else sz)
        info = enc(ret) << 4 if ret else 0
        for i, a in enumerate(args):
            info |= enc(a["type"]) << (6 + 2 * i)
        return info

    def funptr(self, v, out):
        self.sizes[v["name"]] = 4
        args = v.get("args") or []
        ret = ctype_of(v.get("return") or "void")
        params = ", ".join(decl(a["type"], a.get("name")) for a in args) or "void"
        if v.get("callconv") == "C":
            out.append(f"typedef {ret} (*{v['name']})({params});")
            return
        m = re.match(r"^([A-Za-z_][A-Za-z0-9]*)(ProcPtr|UPP)$", v["name"])
        name = m.group(1) if m else v["name"]
        out.append(f"typedef pascal {ret} (*{name}ProcPtr)({params});")
        if v.get("tvector"):
            # Called directly on both CPUs, never through Mixed Mode: the
            # Thread Manager's callbacks are TVector UPPs in Apple's headers.
            out += [
                f"typedef {name}ProcPtr {name}UPP;",
                f"#define New{name}UPP(proc) (({name}UPP)(proc))",
                f"#define Dispose{name}UPP(upp) ((void)0)",
                f"#define New{name}Proc(proc) New{name}UPP(proc)",
                f"#define Dispose{name}Proc(proc) Dispose{name}UPP(proc)",
            ]
            return
        regs = any(a.get("register") for a in args)
        info = 42 if regs else self.procinfo(v.get("return"), args)
        out += [
            "#if TARGET_RT_MAC_CFM",
            f"typedef UniversalProcPtr {name}UPP;",
            f"enum {{ upp{name}ProcInfo = {hexlit(info, 32)} }};",
            f"#define New{name}UPP(proc) (({name}UPP)NewRoutineDescriptor("
            f"(ProcPtr)(proc), upp{name}ProcInfo, GetCurrentArchitecture()))",
            f"#define Dispose{name}UPP(upp) "
            f"DisposeRoutineDescriptor((UniversalProcPtr)(upp))",
            "#else",
            f"typedef {name}ProcPtr {name}UPP;",
            f"#define New{name}UPP(proc) (proc)",
            f"#define Dispose{name}UPP(upp) ((void)0)",
            "#endif",
            f"#define New{name}Proc(proc) New{name}UPP(proc)",
            f"#define Dispose{name}Proc(proc) Dispose{name}UPP(proc)",
        ]

    # -- functions -----------------------------------------------------

    def trap_words(self, fun, trapbits):
        if fun.get("m68k-inline"):
            return list(fun["m68k-inline"])
        words = []
        if fun.get("dispatcher"):
            d = self.byname[fun["dispatcher"]]["dispatcher"]
            sel = int(fun["selector"])
            loc = d.get("selector-location", "")
            small = -128 <= sel <= 127
            if loc in ("D0W", "D0<0xFF>", "D0<0xF>"):
                words += [0x7000 | (sel & 0xFF)] if small else [0x303C, sel]
            elif loc in ("D0L", "D0<0xFFFFFF>"):
                words += [0x7000 | (sel & 0xFF)] if small else \
                    [0x203C, (sel >> 16) & 0xFFFF, sel & 0xFFFF]
            elif loc.startswith("StackW"):
                words += [0x3F3C, sel & 0xFFFF]
            elif loc == "StackL":
                words += [0x2F3C, (sel >> 16) & 0xFFFF, sel & 0xFFFF]
            elif loc == "TrapBits":         # the selector is in the trap word
                trapbits |= sel
            words.append((fun.get("trap") or d["trap"]) | trapbits)
        elif fun.get("trap"):
            words.append(fun["trap"] | trapbits)
        return words

    def pb_trap(self, fun, name, args, ret, out):
        """A call that takes its arguments as a block in memory, laid out
        like Pascal arguments on the stack under a selector word, with A0
        pointing at the block (the Communications Toolbox dispatcher)."""
        trap, sel = fun["m68k-pbtrap"]
        params = ", ".join(decl(a["type"], a.get("name")) for a in args) or "void"
        fields, inits = ["short _sel;"], [hexlit(sel)]
        for a in reversed(args):
            t = re.sub(r"^const\s+", "", a["type"])
            sz = self.size_of(t)
            if sz not in (1, 2, 4):
                raise ValueError(f"{name}: argument {a['name']} has size {sz}")
            fields.append(f"__typeof__({a['name']}) {a['name']};")
            inits.append(a["name"])
            if sz == 1:     # a byte goes in the high byte of a word
                fields.append(f"char _pad_{a['name']};")
                inits.append("0")
        rsz = self.size_of(fun["return"]) if fun.get("return") else 0
        if rsz not in (0, 1, 2, 4):
            raise ValueError(f"{name}: result has size {rsz}")
        out.append(f"{getattr(self, 'pre', '')}static __inline__ __attribute__((__always_inline__)) "
                   f"{ret} {name}({params}) {{")
        out.append(f"    struct {{ {' '.join(fields)} }} __attribute__((__packed__))"
                   f" _pb = {{ {', '.join(inits)} }};")
        out.append('    register long _ret __asm__("d0");')
        out.append('    register void *_a0 __asm__("a0") = &_pb;')
        out.append(f'    __asm__ __volatile__(".short {hexlit(trap)}"')
        out.append('        : "=r"(_ret), "+r"(_a0) : "m"(_pb)')
        out.append('        : "d1", "d2", "a1", "cc", "memory");')
        if rsz == 4:
            out.append(f"    {{ union {{ long l; {decl(ret, 'r')}; }} _u; "
                       f"_u.l = _ret; return _u.r; }}")
        elif rsz:
            out.append(f"    return ({ret})_ret;")
        else:
            out.append("    (void)_ret;")
        out.append("}")

    def inline_trap(self, fun, name, args, words, ret, out):
        """A register-based trap: a static inline function for 68k."""
        params = ", ".join(decl(a["type"], a.get("name")) for a in args) or "void"
        body, ins, outs, after = [], [], [], []
        clobbers = ["d0", "d1", "d2", "a0", "a1"]
        rr = fun.get("returnreg")
        boolean_d0 = rr == "D0Minus1Boolean"
        if rr:
            reg = "d0" if boolean_d0 else rr.lower()
            rtype = "long" if boolean_d0 else ret
            body.append(f"register {rtype} _ret __asm__(\"{reg}\");")
            outs.append('"=r"(_ret)')
            clobbers.remove(reg)
        for a in args:
            r = a.get("register")
            if not r:
                return False
            m = re.match(r"(Out|InOut)<([AD][0-7])>$", r)
            if m:
                io, reg = m.group(1), m.group(2).lower()
                base = ctype_of(a["type"]).rstrip().rstrip("*").rstrip()
                body.append(f"register {base} _{a['name']} __asm__(\"{reg}\");")
                if io == "InOut":
                    body.append(f"_{a['name']} = *{a['name']};")
                    outs.append(f'"+r"(_{a["name"]})')
                else:
                    outs.append(f'"=r"(_{a["name"]})')
                after.append(f"if ({a['name']}) *{a['name']} = _{a['name']};")
            elif re.match(r"[AD][0-7]$", r):
                reg = r.lower()
                body.append(f"register {ctype_of(a['type'])} _{a['name']} __asm__"
                            f"(\"{reg}\") = {a['name']};")
                # The trap may change any register it reads (an OS trap
                # returns its result code in D0 even when the call has no
                # result), so an input is also an output, unless it shares
                # a register with an output already.
                outregs = {("d0" if boolean_d0 else rr.lower())} if rr else set()
                outregs |= {m2.group(1).lower() for m2 in (
                    re.match(r"(?:Out|InOut)<([AD][0-7])>$", b.get("register") or "")
                    for b in args) if m2}
                if reg in outregs:
                    ins.append(f'"r"(_{a["name"]})')
                else:
                    outs.append(f'"+r"(_{a["name"]})')
            else:
                return False
            if reg in clobbers:
                clobbers.remove(reg)
        if fun.get("m68k-memerr"):
            # The 64K ROM leaves MemErr alone (MPW's Pascal glue stored D0
            # there); later ROMs store the same D0 themselves.
            words = list(words) + [0x31C0, 0x0220]     # move.w d0,MemErr
        out.append(f"{getattr(self, 'pre', '')}static __inline__ __attribute__((__always_inline__)) "
                   f"{ret} {name}({params}) {{")
        out += ["    " + b for b in body]
        out.append(f"    __asm__ __volatile__(\".short "
                   f"{', '.join(hexlit(w) for w in words)}\"")
        out.append(f"        : {', '.join(outs)}")
        out.append(f"        : {', '.join(ins)}")
        out.append(f"        : {', '.join(chr(34) + c + chr(34) for c in clobbers)}"
                   f", \"cc\", \"memory\");")
        out += ["    " + x for x in after]
        if boolean_d0:
            out.append("    return _ret == 0;")
        elif rr:
            out.append("    return _ret;")
        out.append("}")
        return True

    def function(self, fun, out, variant=None):
        if "ROMlib" in fun["name"]:
            return
        if fun.get("variants") and variant is None:
            for i in range(len(fun["variants"])):
                self.function(fun, out, i)
            return
        name = fun["name"]
        args = [dict(a, name=a.get("name") or f"arg{i}")
                for i, a in enumerate(fun.get("args") or [])]
        trapbits = 0
        if variant is not None:
            name = fun["variants"][variant]
            nbits = max(1, (len(fun["variants"]) - 1).bit_length())
            for b in range(nbits):
                if variant & (1 << b):
                    m = re.match(r"TrapBit<(.*)>", args[-b - 1]["register"])
                    trapbits |= {"SYSBIT": 0x400, "CLRBIT": 0x200}.get(
                        m.group(1)) or int(m.group(1), 0)
            args = args[:-nbits]
        ret = ctype_of(fun.get("return") or "void")
        if fun.get("trap") and not fun.get("selector"):
            out.append(f"enum {{ _{name} = {hexlit(fun['trap'] | trapbits)} }};")
        words = self.trap_words(fun, trapbits)
        regs = [a for a in args if a.get("register")] or fun.get("returnreg")
        params = ", ".join(decl(a["type"], a.get("name")) for a in args) or "void"
        # Variadic functions (CallUniversalProc) use the C convention.
        cc = "" if any(a["type"] == "..." for a in args) or \
            fun.get("callconv") == "C" else "pascal "
        pre = AVAIL.get(name, "")
        self.pre = pre
        proto = f"{pre}{cc}{ret} {name}({params})"

        if fun.get("m68k") == "none":
            # A library that never ran on 68k Macs (Mac OS 8.5 and later).
            out += ["#if !TARGET_CPU_68K", proto + ";", "#endif"]
        elif fun.get("inline"):
            names = ", ".join(a["name"] for a in args)
            macro = f"#define {name}({names}) ({fun['inline']})"
            cond = {"carbon": "!TARGET_API_MAC_CARBON", "ppc": "TARGET_CPU_68K",
                    "m68k": "!TARGET_CPU_68K"}.get(
                        str(fun.get("noinline", "")).lower())
            if cond:
                out += [f"#if {cond}", macro, "#else", proto + ";", "#endif"]
            else:
                out.append(macro)
        elif fun.get("m68k-body"):
            # Glue that is short enough to inline: C code for 68k.
            # The body may call functions declared later in the header,
            # so only the prototype goes here; the definition goes last.
            head = f"static __inline__ {ret} {name}({params})"
            out += ["#if TARGET_CPU_68K", pre + head + ";", "#else", proto + ";",
                    "#endif"]
            body = [head + " {"]
            body += ["    " + l for l in fun["m68k-body"].rstrip().splitlines()]
            body.append("}")
            self.deferred.append((self.api, body))
        elif fun.get("m68k-pbtrap"):
            out.append("#if TARGET_CPU_68K")
            self.pb_trap(fun, name, args, ret, out)
            out += ["#else", proto + ";", "#endif"]
        elif regs and words:
            out.append("#if TARGET_CPU_68K")
            if not self.inline_trap(fun, name, args, words, ret, out):
                out.append(proto + ";")
                self.glue.append(name)
            out += ["#else", proto + ";", "#endif"]
        elif words:
            out.append(f"{proto} M68K_INLINE({', '.join(hexlit(w) for w in words)});")
        else:
            out.append(proto + ";")
            self.glue.append(name)
        for old in listify(fun.get("old_name")):
            names = ", ".join(a["name"] for a in args)
            out += ["#if OLDROUTINENAMES",
                    f"#define {old}({names}) {name}({names})",
                    "#endif"]

    # -- files ---------------------------------------------------------

    def header(self, h):
        out = [f"/* {h.name}.h: generated by tools/gen-headers.py from "
               f"defs/{h.name}.yaml. Do not edit. */",
               f"#ifndef __MV_{h.name.upper()}__",
               f"#define __MV_{h.name.upper()}__", "",
               '#include "../ConditionalMacros.h"']
        for inc in sorted(h.includes):
            out.append(f'#include "{inc}.h"')
        out += ["", "#pragma options align=mac68k",
                "/* The headers' own inline code may call newer calls behind a",
                "   check; the MAC_MIN_SYSTEM warnings are for the program's calls. */",
                "#pragma clang diagnostic push",
                '#pragma clang diagnostic ignored "-Wuser-defined-warnings"', ""]
        self.deferred = []
        for item in h.items:
            key, v = main_elem(item)
            api = str(item.get("api", "")).lower()
            self.api = api
            if api == "carbon":
                out.append("#if TARGET_API_MAC_CARBON")
            elif api == "classic":
                out.append("#if !TARGET_API_MAC_CARBON")
            if isinstance(v, dict) and v.get("comment"):
                comment(v["comment"], out)
            if key == "enum":
                self.enum(v, out)
            elif key in ("struct", "union"):
                self.struct(key, v, out)
            elif key == "dispatcher":
                if v.get("selector-location") != "TrapBits":
                    out.append(f"enum {{ _{v['name']} = {hexlit(v['trap'])} }};")
            elif key == "typedef":
                self.typedef(v, out)
            elif key == "function":
                self.function(v, out)
            elif key == "lowmem":
                self.lowmem(v, out)
            elif key == "funptr":
                self.funptr(v, out)
            elif key == "define":
                out.append(f"#define {v['name']} {v['value']}")
            elif key == "verbatim":
                out.append(str(v).strip())
            if api in ("carbon", "classic"):
                out.append("#endif")
            out.append("")
        if self.deferred:
            out.append("#if TARGET_CPU_68K")
            for api, body in self.deferred:
                cond = {"carbon": "TARGET_API_MAC_CARBON",
                        "classic": "!TARGET_API_MAC_CARBON"}.get(api)
                out += ([f"#if {cond}"] if cond else []) + body + \
                    (["#endif"] if cond else []) + [""]
            out += ["#endif", ""]
        out += ["#pragma clang diagnostic pop", "#pragma options align=reset", "", "#endif", ""]
        return "\n".join(out)


def load_availability():
    """call -> 'MAC_SINCE(...) ' prefix, from data/availability.tsv."""
    path = os.path.join(ROOT, "data", "availability.tsv")
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        if line.startswith("#"):
            continue
        name, _hdr, _trap, _sel, since, cls, _disp, gest = line.rstrip("\n").split("\t")[:8]
        if since == "-":
            continue
        v = int(since, 16)
        pre = ""
        if v > 0x0010 or cls not in ("64K",):
            if v > 0x0010:
                text = f"{v >> 8}.{(v >> 4) & 15}" + (f".{v & 15}" if v & 15 else "")
                if gest:
                    pre += f"MAC_SINCE_GESTALT(0x{v:04X}, \"{text}\", \"'{gest}'\") "
                else:
                    pre += f"MAC_SINCE(0x{v:04X}, \"{text}\") "
            if cls == "II":
                pre += "MAC_COLOR_QD "
        if pre:
            out[name] = pre
    return out


AVAIL = {}


def topsort(headers):
    order, done = [], set()

    def visit(n, stack):
        if n in stack:
            sys.exit("include cycle: " + " -> ".join(stack + [n]))
        if n in done:
            return
        done.add(n)
        for inc in sorted(headers[n].includes):
            visit(inc, stack + [n])
        order.append(n)
    for n in sorted(headers):
        visit(n, [])
    return order


CONDITIONAL_MACROS = """\
/* ConditionalMacros.h: which compiler, CPU and runtime. Generated by
   tools/gen-headers.py. */
#ifndef __CONDITIONALMACROS__
#define __CONDITIONALMACROS__

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#if defined(__m68k__)
#  define TARGET_CPU_68K 1
#  define TARGET_CPU_PPC 0
#  define TARGET_RT_MAC_CFM 0
#  define TARGET_RT_MAC_68881 0
#  define M68K_INLINE(...) __attribute__((__raw_inline__(__VA_ARGS__)))
#  define GetCurrentArchitecture() ((ISAType)0)
#elif defined(__powerpc__) || defined(__ppc__)
#  define TARGET_CPU_68K 0
#  define TARGET_CPU_PPC 1
#  define TARGET_RT_MAC_CFM 1
#  define M68K_INLINE(...)
#  define GetCurrentArchitecture() ((ISAType)1)
#else
#  error "classic Mac OS headers: unknown CPU"
#endif

#define TARGET_OS_MAC 1
#define TARGET_RT_BIG_ENDIAN 1
#define TARGET_RT_LITTLE_ENDIAN 0
#ifndef TARGET_API_MAC_CARBON
#  define TARGET_API_MAC_CARBON 0
#endif
#ifndef TARGET_API_MAC_OS8
#  define TARGET_API_MAC_OS8 (!TARGET_API_MAC_CARBON)
#endif
#ifndef OLDROUTINENAMES
#  define OLDROUTINENAMES 0
#endif

#ifndef pascal
#  define pascal
#endif

/* Opt-in checks against the oldest System a program supports: build with
   -DMAC_MIN_SYSTEM=0x0605 (for example) to get a warning at each call whose
   trap no measured System older than that implements, and add
   -DMAC_NO_COLOR_QD to also warn about calls only Color QuickDraw Macs
   have. docs/systems.md lists the measurements. Calls you guard with
   TrapAvailable() or Gestalt still warn; silence those with
   #pragma clang diagnostic ignored "-Wuser-defined-warnings". */
#if defined(MAC_MIN_SYSTEM)
#  define MAC_SINCE(v, s) __attribute__((__diagnose_if__(MAC_MIN_SYSTEM < (v), \
       "needs System " s " or later", "warning")))
#  define MAC_SINCE_GESTALT(v, s, g) __attribute__((__diagnose_if__(MAC_MIN_SYSTEM < (v), \
       "needs a manager Gestalt selector " g " reports; the oldest measured System that had it is " s, \
       "warning")))
#else
#  define MAC_SINCE(v, s)
#  define MAC_SINCE_GESTALT(v, s, g)
#endif
#if defined(MAC_NO_COLOR_QD)
#  define MAC_COLOR_QD __attribute__((__diagnose_if__(1, \
       "needs a Color QuickDraw Mac (Mac II or later)", "warning")))
#else
#  define MAC_COLOR_QD
#endif

#define nil NULL
typedef struct RoutineDescriptor *ProcPtr;

#endif
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--defs", default="defs")
    ap.add_argument("--out", default="include")
    a = ap.parse_args()
    AVAIL.update(load_availability())

    headers = {}
    for f in sorted(os.listdir(a.defs)):
        if f.endswith(".yaml"):
            h = Header(os.path.join(a.defs, f))
            headers[h.name] = h
    where = {}
    for h in headers.values():
        for n in h.declared:
            where.setdefault(n, h.name)
    missing = set()
    for h in headers.values():
        for n in h.required:
            if n in where:
                if where[n] != h.name:
                    h.includes.add(where[n])
            else:
                missing.add(n)
    if missing:
        print("not declared anywhere: " + " ".join(sorted(missing)),
              file=sys.stderr)

    gen = Generator(headers)
    os.makedirs(os.path.join(a.out, "mv"), exist_ok=True)
    order = topsort(headers)
    for n in order:
        if n == "MPW":      # MPW's own extras, not Universal Interfaces
            continue
        with open(os.path.join(a.out, "mv", n + ".h"), "w") as f:
            f.write(gen.header(headers[n]))
    with open(os.path.join(a.out, "ConditionalMacros.h"), "w") as f:
        f.write(CONDITIONAL_MACROS)
    with open(os.path.join(a.out, "Multiverse.h"), "w") as f:
        f.write("/* Multiverse.h: the whole classic Mac OS API. Generated by "
                "tools/gen-headers.py. */\n#ifndef __MULTIVERSE__\n"
                "#define __MULTIVERSE__\n")
        for n in order:
            if n != "MPW":
                f.write(f'#include "mv/{n}.h"\n')
        f.write("\nextern QDGlobals qd;\n#endif\n")
    for n in APPLE_NAMES:
        if n == "ConditionalMacros":
            continue
        with open(os.path.join(a.out, n + ".h"), "w") as f:
            f.write(f"/* {n}.h: generated by tools/gen-headers.py. */\n"
                    '#include "Multiverse.h"\n')
    with open(os.path.join(a.out, "needs-glue.txt"), "w") as f:
        f.write("".join(n + "\n" for n in gen.glue))
    print(f"gen-headers: {len(order)} headers, "
          f"{len(gen.glue)} functions without a 68k trap", file=sys.stderr)


if __name__ == "__main__":
    main()
