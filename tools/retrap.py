#!/usr/bin/env python3
"""Give declared functions that have no 68k code yet their trap, when the
glue data (data/trapinfo*.json) now describes them.

    python3 tools/retrap.py [Name ...]

It checks each function's argument sizes against the glue the same way
tools/add-protos.py does, and rewrites only the functions it can give a
trap. With names, only those functions are considered.
"""
import glob
import importlib.util
import json
import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location(
    "add_protos", os.path.join(HERE, "add-protos.py"))
ap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ap)

CODE_KEYS = ("trap", "dispatcher", "m68k-inline", "m68k-body", "inline",
             "executor", "m68k")


def main():
    want = set(sys.argv[1:])
    info = {}
    for f in ("trapinfo.json", "trapinfo-os8.json", "trapinfo-os9.json"):
        info.update(json.load(open(os.path.join(ROOT, "data", f))))
    disp, sizes, _ = ap.load_defs()
    new_disp = {}
    report = []
    for path in sorted(glob.glob(os.path.join(ROOT, "defs", "*.yaml"))):
        text = open(path, encoding="utf-8").read()
        chunks = text.split("\n# ####\n")
        changed = False
        for i, c in enumerate(chunks):
            data = yaml.safe_load(c)
            if not (isinstance(data, list) and len(data) == 1 and
                    "function" in data[0] and len(data[0]) == 1):
                continue
            fun = data[0]["function"]
            name = fun.get("name")
            if name not in info or (want and name not in want) or \
                    any(k in fun for k in CODE_KEYS):
                continue
            p = {"name": name, "return": fun.get("return", "void"),
                 "args": [dict(a) for a in fun.get("args", [])]}
            trial = dict(fun, args=[dict(a) for a in fun.get("args", [])])
            before = dict(new_disp)
            status = ap.attach_trap(trial, p, info[name], disp, new_disp, sizes)
            report.append(f"{name}: {status}")
            if not any(k in trial for k in ("trap", "dispatcher", "m68k-inline")):
                for k in set(new_disp) - set(before):
                    del new_disp[k]
                continue
            if not trial.get("args"):
                trial.pop("args", None)
            lead = c[:len(c) - len(c.lstrip("\n"))]
            chunks[i] = lead + yaml.safe_dump([{"function": trial}],
                                              sort_keys=False, width=100)
            changed = True
        if changed:
            open(path, "w", encoding="utf-8").write("\n# ####\n".join(chunks))
    if new_disp:
        report.append("new dispatchers, add them to a defs file: " +
                      ", ".join(f"{d['name']} {t:#06x}" for t, d in new_disp.items()))
    print("\n".join(report), file=sys.stderr)


if __name__ == "__main__":
    main()
