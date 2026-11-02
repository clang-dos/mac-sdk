#!/usr/bin/env python3
"""Write definitions for defs/ from Apple's MPW C interfaces, such as the
QuickTime 1.5 interfaces on the 1992 Developer CD Series.

    python3 tools/mpw2defs.py -I path/to/CIncludes -I path/to/QuickTime \\
        -o defs/QuickTime.yaml Movies.h ImageCompression.h ...

The headers are parsed with clang (CLANG, default clang), so the types,
record layouts and enum values are what a compiler sees. Each function's
68k inline code (`= {0x303C,0x0001,0xAAAA}` in MPW's syntax) becomes its
m68k-inline words. Declarations already in defs/ are left alone, and the
new ones are appended to the output file. Apple's headers are not part of
this repository: point the tool at your own copy.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import tempfile

import yaml

import importlib.util
_spec = importlib.util.spec_from_file_location(
    "check_mpw", os.path.join(os.path.dirname(os.path.abspath(__file__)), "check-mpw.py"))
check_mpw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_mpw)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

BASE = {
    "short": "INTEGER", "signed short": "INTEGER", "unsigned short": "uint16_t",
    "long": "int32_t", "signed long": "int32_t", "unsigned long": "uint32_t",
    "int": "int32_t", "unsigned int": "uint32_t", "char": "char",
    "signed char": "int8_t", "unsigned char": "uint8_t", "void": "void",
    "long double": "extended80", "long long": "int64_t",
    "unsigned long long": "uint64_t",
}


def defined_names():
    names = set()
    for f in glob.glob(os.path.join(ROOT, "defs", "*.yaml")):
        names |= set(re.findall(r"name: (\w+)", open(f).read()))
    return names


def preprocess(dirs, out):
    """Copy the headers, turning MPW inline code into annotations clang
    keeps, and dropping #pragma parameter (register calls keep their
    inline words, and the words name the registers)."""
    regs, inlines = {}, {}
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*.h")):
            s = open(f, encoding="mac_roman").read().replace("\r", "\n")
            for m in re.finditer(r"^#pragma parameter\s+(__\w+)?\s*(\w+)\(([^)]*)\)", s, re.M):
                regs[m.group(2)] = (m.group(1), [r.strip() for r in m.group(3).split(",") if r.strip()])
            s = re.sub(r"^#pragma parameter.*$", "", s, flags=re.M)
            # pascal T Name(args) = {0x...}; or = 0xA000; (clang's JSON
            # dump drops annotation text, so keep the code by name here)
            nocomments = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
            for m in re.finditer(r"\b(\w+)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*=\s*"
                                 r"(\{[^}]*\}|0x[0-9A-Fa-f]+|_\w+)\s*;", nocomments):
                inlines.setdefault(m.group(1), re.sub(r"[\s{}]+", "", m.group(3)))
            s = re.sub(r"\)\s*=\s*(\{[^}]*\}|0x[0-9A-Fa-f]+|_\w+)\s*;", ");", s)
            name = os.path.basename(f)
            open(os.path.join(out, name), "w", encoding="latin-1").write(s)
            low = name.lower()
            if low != name and not os.path.exists(os.path.join(out, low)):
                os.symlink(name, os.path.join(out, low))
    if os.path.exists(os.path.join(out, "Quickdraw.h")):
        os.symlink("Quickdraw.h", os.path.join(out, "QuickDraw.h"))
    return regs, inlines


def defines(dirs, headers):
    """Object-like #define names with a body, in header order, with the
    body when it is a four-character code (kept as written)."""
    out = []
    for h in headers:
        for d in dirs:
            p = os.path.join(d, h)
            if os.path.exists(p):
                s = open(p, encoding="mac_roman").read().replace("\r", "\n")
                s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
                for m in re.finditer(r"^#define\s+(\w+)[ \t]+(\S[^\n]*)$", s, re.M):
                    body = m.group(2).strip()
                    code = re.fullmatch(r"\(?('[^'\n]{4}')\)?", body)
                    out.append((m.group(1), code.group(1) if code else None))
                break
    return out


def macro_values(clang, inc, headers, names):
    """The integer value of each macro clang can fold to a constant."""
    src = os.path.join(inc, "macros.c")
    with open(src, "w") as f:
        f.write("".join(f'#include "{h}"\n' for h in headers))
        for n in names:
            f.write(f"enum {{ mpw2defs_{n} = ({n}) }};\n")
    js = subprocess.run(
        [clang, "--target=m68k-apple-macos", "-I", inc, "-Dextended=long double",
         "-Dcomp=long long", "-fsyntax-only", "-w", "-ferror-limit=0",
         "-Xclang", "-ast-dump=json", src], capture_output=True).stdout
    vals = {}
    for n in json.loads(js)["inner"]:
        if n.get("kind") == "EnumDecl":
            for c in n.get("inner", []):
                name = c.get("name", "")
                if name.startswith("mpw2defs_") and not c.get("isInvalid"):
                    v = first_value(c)
                    if v is not None:
                        vals[name[9:]] = v
    return vals


def ytype(t):
    """An MPW type spelling as the definitions write it."""
    t = t.replace("struct ", "struct ").strip()
    t = re.sub(r"\s+", " ", t)
    m = re.fullmatch(r"(const )?(.*?)((?: ?\*)*)", t)
    const, base, stars = m.group(1) or "", m.group(2).strip(), m.group(3).replace(" ", "")
    base = BASE.get(base, base)
    return f"{const}{base}{stars}"


class Walker:
    def __init__(self, ast, want):
        self.cur = None
        self.want = want
        self.items = []
        self.ast = ast

    def track(self, n):
        for k in ("loc", "range"):
            v = n.get(k)
            if not isinstance(v, dict):
                continue
            for sub in ([v] if k == "loc" else [v.get("begin", {}), v.get("end", {})]):
                for s2 in (sub, sub.get("spellingLoc", {}), sub.get("expansionLoc", {})):
                    if "file" in s2:
                        self.cur = os.path.basename(s2["file"])

    def walk_all(self, n, out):
        self.track(n)
        out.append((self.cur, n))
        for c in n.get("inner", []):
            self.walk_all(c, [])

    def top(self):
        res = []
        for n in self.ast["inner"]:
            self.track(n)
            f = self.cur
            # descend to keep the file tracking right
            for c in n.get("inner", []):
                self.walk_all(c, [])
            if f in self.want:
                res.append((f, n))
        return res


def first_value(n):
    """The value clang computed for an enum constant's initializer, which
    sits in a ConstantExpr, sometimes under an ImplicitCastExpr."""
    for e in n.get("inner", []):
        if "value" in e:
            return int(e["value"])
        v = first_value(e)
        if v is not None:
            return v
    return None


def funptr_args(qual):
    """'pascal OSErr (*)(Movie, long)' -> (ret, [types])"""
    q = qual.replace("__attribute__((pascal))", "").replace("((*))", "(*)").strip()
    m = re.fullmatch(r"(?:pascal )?(.*?) ?\(\*\)\((.*)\)", q)
    if not m:
        return None
    args = [a.strip() for a in m.group(2).split(",")] if m.group(2).strip() not in ("", "void") else []
    return m.group(1).strip(), args


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-I", dest="dirs", action="append", required=True)
    ap.add_argument("-o", dest="out", required=True)
    ap.add_argument("headers", nargs="+")
    a = ap.parse_args()
    clang = os.environ.get("CLANG", "clang")
    known = defined_names()
    names = {**check_mpw.enum_values(a.dirs), **check_mpw.trap_names(a.dirs)}
    with tempfile.TemporaryDirectory() as tmp:
        regs, inlines = preprocess(a.dirs, tmp)
        src = os.path.join(tmp, "all.c")
        open(src, "w").write("".join(f'#include "{h}"\n' for h in a.headers))
        js = subprocess.run(
            [clang, "--target=m68k-apple-macos", "-I", tmp, "-Dextended=long double",
             "-Dcomp=long long", "-fsyntax-only", "-w", "-Xclang", "-ast-dump=json", src],
            check=True, capture_output=True).stdout
        macros = defines(a.dirs, a.headers)
        mvals = macro_values(clang, tmp, a.headers, [n for n, code in macros if not code])
    ast = json.loads(js)
    w = Walker(ast, set(a.headers))
    items, skipped, no_code = [], [], []
    records = {}
    for f, n in w.top():
        k, name = n.get("kind"), n.get("name")
        if k == "RecordDecl" and n.get("completeDefinition"):
            records[n.get("id")] = n
    seen = set()
    pending = None
    todo = w.top()
    while todo:
        f, n = todo.pop(0)
        k, name = n.get("kind"), n.get("name")
        unnamed, pending = pending, None    # the record just before, if unnamed
        if name and (name in known or name in seen or name.startswith("__")):
            continue
        if k == "EnumDecl":
            vals, nxt = [], 0
            for c in n.get("inner", []):
                if c.get("kind") != "EnumConstantDecl" or c["name"] in known:
                    continue
                v = first_value(c)
                v = nxt if v is None else v
                nxt = v + 1
                vals.append({"name": c["name"], "value": v})
                seen.add(c["name"])
            if vals:
                items.append({"enum": {"values": vals}})
        elif k == "RecordDecl" and n.get("completeDefinition") and not name:
            pending = n           # typedef struct { ... } Name;
        elif k == "RecordDecl" and n.get("completeDefinition") and name:
            mem = []
            ok = True
            anon = None
            for c in n.get("inner", []):
                if c.get("kind") == "RecordDecl":
                    anon = [x for x in c.get("inner", []) if x.get("kind") == "FieldDecl"]
                elif c.get("kind") == "FieldDecl":
                    t = c["type"]["qualType"]
                    if "(anonymous" in t or "unnamed" in t:
                        # struct { T x; } a[n] has the layout of T a[n]
                        if anon and len(anon) == 1:
                            t = re.sub(r"^struct \((?:anonymous|unnamed)[^)]*\)",
                                       anon[0]["type"]["qualType"], t)
                        else:
                            ok = False
                            break
                    am = re.fullmatch(r"(.*?) ?((?:\[\d+\])+)", t)
                    mem.append({"name": c.get("name", "_pad"), "type":
                                f"{ytype(am.group(1))}{am.group(2)}" if am else ytype(t)})
            if not ok:
                skipped.append(name)
                continue
            kind = "union" if n.get("tagUsed") == "union" else "struct"
            items.append({kind: {"name": name, "members": mem}})
            seen.add(name)
        elif k == "TypedefDecl" and name and unnamed is not None and \
                n["type"]["qualType"] in ("struct " + name, "union " + name):
            todo.insert(0, (f, dict(unnamed, name=name)))
            continue
        elif k == "TypedefDecl" and name:
            q = n["type"]["qualType"]
            fp = funptr_args(q) if "(*)" in q else None
            if fp:
                ret, args = fp
                pascal = "pascal" in q
                # SGDataProc becomes SGDataProcPtr and SGDataUPP, the
                # later names, with SGDataProc kept as a typedef
                base = re.sub(r"(ProcPtr|UPP|Proc)$", "", name)
                if pascal and base + "ProcPtr" != name and (base + "ProcPtr" in known or base + "UPP" in known):
                    # MPW's 1992 name for a type defs/ already has
                    items.append({"typedef": {"name": name, "type": base + (
                        "ProcPtr" if base + "ProcPtr" in known else "UPP")}})
                    seen.add(name)
                    continue
                items.append({"funptr": {"name": base + "ProcPtr" if pascal else name,
                              "return": ytype(ret),
                              "args": [{"type": ytype(t)} for t in args]}})
                if not pascal:
                    items[-1]["funptr"]["callconv"] = "C"
                elif base + "ProcPtr" != name:
                    items.append({"typedef": {"name": name, "type": base + "ProcPtr"}})
            elif q in ("struct " + name, "union " + name) or q == name:
                continue          # typedef struct X X: the struct defines X
            else:
                items.append({"typedef": {"name": name, "type": ytype(q)}})
            seen.add(name)
        elif k == "FunctionDecl" and name:
            inline = inlines.get(name)
            if not inline:
                no_code.append(name)    # implemented by components, or glue
                continue
            ret = n["type"]["qualType"].split("(")[0].replace("pascal", "").strip()
            args = [{"name": c.get("name") or f"arg{i}", "type": ytype(c["type"]["qualType"])}
                    for i, c in enumerate(x for x in n.get("inner", []) if x.get("kind") == "ParmVarDecl")]
            fn = {"name": name, "return": ytype(ret)}
            if args:
                fn["args"] = args
            if inline:
                words = []
                for t in inline.split(","):
                    v = check_mpw.word_value(t, names)
                    words.append(t if v is None else v)
                if all(isinstance(x, int) for x in words):
                    if name in regs:
                        r, ar = regs[name]
                        for arg, reg in zip(fn.get("args", []), ar):
                            arg["register"] = reg.strip("_").upper()
                        if r:
                            fn["returnreg"] = r.strip("_").upper()
                    fn["m68k-inline"] = words
                else:
                    skipped.append(name)
                    continue
            if "pascal" not in n["type"]["qualType"]:
                fn["callconv"] = "C"
            items.append({"function": fn})
            seen.add(name)
    vals = []
    for n, code in macros:
        if n in known or n in seen or n.startswith("__"):
            continue
        if code or n in mvals:
            vals.append({"name": n, "value": code or mvals[n]})
            seen.add(n)
    if vals:
        items.append({"enum": {"values": vals}})
    with open(a.out, "a") as fo:
        for it in items:
            fo.write("\n# ####\n\n")
            yaml.safe_dump([it], fo, sort_keys=False, default_flow_style=None, width=78)
    print(f"mpw2defs: {sum(1 for i in items if 'function' in i)} functions, "
          f"{len(items)} definitions; skipped {', '.join(skipped) or 'none'}; "
          f"{len(no_code)} functions without inline code left out", file=sys.stderr)


if __name__ == "__main__":
    main()
