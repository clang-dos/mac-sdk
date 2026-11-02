#!/usr/bin/env python3
"""Which System, ROM and machine each Toolbox call needs, measured on the
real Systems by tools/probe/trapprobe.c.

    python3 tools/availability.py --import DIR   # .trp files -> data/probe.tsv
    python3 tools/availability.py                # data/probe.tsv -> data/availability.tsv,
                                                 #   docs/systems.md

The probe records, on each System it runs on, which OS and Toolbox trap
table entries differ from _Unimplemented, which PACK resources exist and
what some Gestalt selectors answer. A call's availability is that of the
trap word it executes. For calls that go through a dispatcher trap
(_HFSDispatch, _Pack8, _ScriptUtil and so on), that is the dispatcher's:
a selector added later can need a later System, and the tables say so.
"""
import argparse
import glob
import importlib.util
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROBE_TSV = os.path.join(ROOT, "data", "probe.tsv")
AVAIL_TSV = os.path.join(ROOT, "data", "availability.tsv")
DOC = os.path.join(ROOT, "docs", "systems.md")

# Probe runs: file label -> (System, version word, machine class, machine, emulator)
# Machine classes, oldest first: the 64K ROM (Mac 128K/512K), the 128K
# ROM (Mac Plus, 68000), the Mac II ROM (Color QuickDraw), the Quadra 800
# ROM, and PowerPC.
RUNS = [
    ("0.1", "0.1", 0x0010, "64K", "Mac 128K", "MAME"),
    ("0.3", "0.3", 0x0030, "64K", "Mac 128K", "MAME"),
    ("0.5", "0.5", 0x0050, "64K", "Mac 128K", "MAME"),
    ("1.0", "1.0", 0x0100, "64K", "Mac 512K", "MAME"),
    ("0.7", "0.7", 0x0070, "Plus", "Mac Plus", "MAME"),
    ("1.0e", "1.0", 0x0100, "Plus", "Mac Plus", "MAME"),
    ("1.1", "1.1", 0x0110, "Plus", "Mac Plus", "MAME"),
    ("2.0", "2.0", 0x0200, "Plus", "Mac Plus", "MAME"),
    ("2.0.1", "2.0.1", 0x0201, "Plus", "Mac Plus", "MAME"),
    ("5.0", "5.0", 0x0500, "Plus", "Mac Plus", "MAME"),
    ("5.1", "5.1", 0x0510, "Plus", "Mac Plus", "MAME"),
    ("6.0", "6.0", 0x0600, "Plus", "Mac Plus", "MAME"),
    ("6.0.2", "6.0.2", 0x0602, "Plus", "Mac Plus", "MAME"),
    ("6.0.3", "6.0.3", 0x0603, "Plus", "Mac Plus", "MAME"),
    ("6.0.4", "6.0.4", 0x0604, "Plus", "Mac Plus", "MAME"),
    ("6.0.5", "6.0.5", 0x0605, "Plus", "Mac Plus", "MAME"),
    ("6.0.8", "6.0.8", 0x0608, "Plus", "Mac Plus", "MAME"),
    ("7.0-Plus", "7.0", 0x0700, "Plus", "Mac Plus", "MAME"),
    ("7.0.1-Plus", "7.0.1", 0x0701, "Plus", "Mac Plus", "MAME"),
    ("5.0-II", "5.0", 0x0500, "II", "Mac II", "MAME"),
    ("6.0.5-II", "6.0.5", 0x0605, "II", "Mac II", "MAME"),
    ("6.0.8-II", "6.0.8", 0x0608, "II", "Mac II", "MAME"),
    ("7.0-IIx", "7.0", 0x0700, "II", "Mac IIx", "MAME"),
    ("7.0.1-IIx", "7.0.1", 0x0701, "II", "Mac IIx", "MAME"),
    ("7.1-IIx", "7.1", 0x0710, "II", "Mac IIx", "MAME"),
    ("7.1-Q800", "7.1", 0x0710, "Q800", "Quadra 800", "QEMU"),
    ("7.6.1-Q800", "7.6.1", 0x0761, "Q800", "Quadra 800", "QEMU"),
    ("8.1-Q800", "8.1", 0x0810, "Q800", "Quadra 800", "QEMU"),
    ("9.2.1-PPC", "9.2.1", 0x0921, "PPC", "Power Mac G4 (mac99)", "QEMU"),
]
CLASSES = ["64K", "Plus", "II", "Q800", "PPC"]
CLASS_TEXT = {
    "64K": "every Mac",
    "Plus": "the 128K ROM (Mac Plus) and later",
    "II": "Color QuickDraw Macs (Mac II and later)",
    "Q800": "a Quadra 800",
    "PPC": "PowerPC",
}
GESTALT = ["sysv", "mach", "proc", "fpu ", "mmu ", "qd  ", "rom ", "romv", "ram ",
           "lram", "vm  ", "addr", "fs  ", "alis", "evnt", "ppc ", "help", "edtn",
           "fold", "cpnt", "qtim", "snd ", "sm  ", "tmgr", "os  ", "kbd ", "dict",
           "drag", "appr", "menu", "cntl", "wind", "dlgx", "thds", "mpsc", "cfrg",
           "icmp", "ttsc", "tsmv", "nlup", "font", "qdtx", "ctbv", "cmtb", "atlk",
           "mtcp", "scsi", "sysa", "sysu", "hfs+", "nav ", "cmnu", "kcmr", "icon"]
PACK_OF = {t: n for n, t in enumerate([0xA9E7, 0xA9E8, 0xA9E9, 0xA9EA, 0xA9EB, 0xA9EC, 0xA9ED,
                                       0xA9EE, 0xA816, 0xA82B, 0xA82C, 0xA82D, 0xA82E, 0xA82F,
                                       0xA830, 0xA831])}
# Toolbox entries A800-A84F that are real before System 6.0 (the same masks
# as TrapAvailable in defs/OSUtil.yaml): the Mac Plus under System 2.0 and
# the Mac II under 5.0 and 6.0.5, from the trap addresses in the probe files.
REAL_LOW = {
    "Plus": [0x00, 0xFF, 0xFF, 0xC9, 0xC3, 0x9F, 0xDF, 0xFF, 0xFF, 0xF7],
    "II": [0x7F, 0xFF, 0xFF, 0xC9, 0xC3, 0x9F, 0xDF, 0xFF, 0xFF, 0xFF],
}
# Managers reached through a shared dispatcher trap, which an older System
# may fill with something else: a call needs its manager's Gestalt selector
# to answer as well.
HEADER_GESTALT = {
    "Components": "cpnt", "QuickTime": "qtim", "EditionMgr": "edtn", "AppleEvents": "evnt",
    "HelpMgr": "help", "AliasMgr": "alis", "PPC": "ppc ", "DragMgr": "drag",
    "Appearance": "appr", "Threads": "thds", "Dictionary": "dict", "SpeechManager": "ttsc",
    "Navigation": "nav ", "ContextualMenus": "cmnu", "Keychain": "kcmr", "CommTool": "ctbv",
    "Connections": "ctbv", "Terminals": "ctbv", "FileTransfers": "ctbv", "CTBUtilities": "ctbv",
    "TextServices": "tsmv", "Multiprocessing": "mpsc", "CodeFragments": "cfrg",
}


def vtext(v):
    major, minor, bug = v >> 8, (v >> 4) & 15, v & 15
    return f"{major}.{minor}" + (f".{bug}" if bug else "")


def read_trp(path):
    d = open(path, "rb").read()
    magic, rom85, romv, sysv, cpu = struct.unpack(">4shHHB", d[:11])
    assert magic == b"TRP2", path
    os_, tb, pk = d[12:268], d[268:1292], d[1292:1308]
    n = struct.unpack(">H", d[1308:1310])[0]
    gest = {}
    for i in range(n):
        s, e, r = struct.unpack(">4shI", d[1310 + 10 * i:1320 + 10 * i])
        gest[s.decode("mac_roman")] = None if e else r
    return dict(rom85=rom85 & 0xFFFF, romv=romv, sysv=sysv, cpu=cpu, os=os_, tb=tb,
                pack=pk, gestalt=gest)


def import_trp(src):
    rows = {}
    labels = []
    for label, *_ in RUNS:
        p = os.path.join(src, label + ".trp")
        if not os.path.exists(p):
            print(f"availability: no {p}", file=sys.stderr)
            continue
        labels.append(label)
        rows[label] = read_trp(p)
    with open(PROBE_TSV, "w") as f:
        f.write("# Measured by tools/probe/trapprobe.c; see tools/availability.py.\n")
        f.write("# 1 implemented, 0 unimplemented, - no such table entry on that ROM.\n")
        f.write("entry\t" + "\t".join(labels) + "\n")
        for key, fmt in (("rom85", "%04X"), ("romv", "%04X"), ("sysv", "%04X"), ("cpu", "%d")):
            f.write(key + "\t" + "\t".join(fmt % rows[l][key] for l in labels) + "\n")
        sym = {0: "0", 1: "1", 2: "-"}
        for i in range(256):
            f.write(f"A{0x000 + i:03X}\t" + "\t".join(sym[rows[l]["os"][i]] for l in labels) + "\n")
        for i in range(1024):
            f.write(f"A{0x800 + i:03X}\t" + "\t".join(sym[rows[l]["tb"][i]] for l in labels) + "\n")
        for i in range(16):
            f.write(f"PACK{i}\t" + "\t".join(str(rows[l]["pack"][i]) for l in labels) + "\n")
        for g in GESTALT:
            vals = []
            for l in labels:
                v = rows[l]["gestalt"].get(g, "-")
                vals.append("-" if v == "-" else ("err" if v is None else "%08X" % v))
            f.write(f"gestalt {g}\t" + "\t".join(vals) + "\n")
    print(f"availability: wrote {PROBE_TSV} ({len(labels)} runs)")


def load_probe():
    data, labels = {}, None
    for line in open(PROBE_TSV):
        if line.startswith("#"):
            continue
        parts = line.rstrip("\n").split("\t")
        if parts[0] == "entry":
            labels = parts[1:]
            continue
        data[parts[0]] = dict(zip(labels, parts[1:]))
    return labels, data


def entry_of(trap):
    """The probe row for a trap word: toolbox traps by their 10-bit number,
    OS traps by their 8-bit number (the flag bits 8-10 do not matter)."""
    if trap & 0x0800:
        return "A%03X" % (0x800 | (trap & 0x3FF))
    return "A%03X" % (trap & 0xFF)


def availability(trap, labels, data, gestalt=None):
    """(version, class) of the oldest run with the trap, by class then version;
    None if no run has it."""
    row = data.get(entry_of(trap))
    pack = PACK_OF.get(trap)
    runs = {r[0]: r for r in RUNS}
    # Before System 6.0 the Toolbox entries A800-A84F that the ROM does not
    # use hold copies of the OS entries' addresses (for code written for
    # the 64K ROM's single table); 6.0 points them at _Unimplemented. Count
    # those entries only where they were real (REAL_LOW, from the addresses
    # the probe recorded).
    low = (trap & 0x3FF) if trap & 0x0800 and (trap & 0x3FF) < 0x50 else None
    have = [runs[l] for l in labels if row and row[l] == "1"
            and not (low is not None and runs[l][2] < 0x0600 and runs[l][3] in REAL_LOW
                     and not REAL_LOW[runs[l][3]][low >> 3] & (0x80 >> (low & 7)))
            and (pack is None or data[f"PACK{pack}"][l] == "1"
                 or runs[l][3] in ("64K", "Plus", "II") and pack in (4, 5, 7))
            and (gestalt is None or data[f"gestalt {gestalt}"][l] not in ("-", "err"))]
    if not have:
        return None
    cls = min((r[3] for r in have), key=CLASSES.index)
    ver = min(r[2] for r in have if r[3] == cls)
    # Present in an older class only from a later System? Report the oldest
    # System on any machine too.
    first = min(r[2] for r in have)
    return ver, cls, first


def sdk_calls():
    spec = importlib.util.spec_from_file_location("check_mpw", os.path.join(HERE, "check-mpw.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    calls = m.sdk_inlines()
    # which header each call is in
    where = {}
    inc = os.path.join(ROOT, "include", "mv")
    import re
    for f in sorted(os.listdir(inc)):
        for mm in re.finditer(r"\b(\w+)\s*\(", re.sub(r"MAC_SINCE(?:_GESTALT)?\([^()]*\) |MAC_COLOR_QD ", "", open(os.path.join(inc, f)).read())):
            where.setdefault(mm.group(1), f[:-2])
    return calls, where, m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--import", dest="src")
    a = ap.parse_args()
    if a.src:
        import_trp(a.src)
        return 0
    labels, data = load_probe()
    calls, where, cm = sdk_calls()
    rows = []
    for name in sorted(calls):
        words = calls[name]
        pairs = cm.normalize(words)
        if not pairs:
            continue
        trap, sel = pairs[-1]
        disp = sel is not None or trap in PACK_OF
        hdr = where.get(name, "?")
        g = HEADER_GESTALT.get(hdr)
        av = availability(trap, labels, data, g)
        rows.append((name, hdr, trap, sel, av, disp, g))
    with open(AVAIL_TSV, "w") as f:
        f.write("# Generated by tools/availability.py from data/probe.tsv.\n")
        f.write("# call\theader\ttrap\tselector\tsince\tmachines\tdispatcher\tgestalt\n")
        for name, hdr, trap, sel, av, disp, g in rows:
            since = "%04X" % av[0] if av else "-"
            cls = av[1] if av else "-"
            f.write(f"{name}\t{hdr}\t{trap:04X}\t{'' if sel is None else sel}\t{since}\t{cls}\t"
                    f"{'yes' if disp else ''}\t{g or ''}\n")
    write_doc(labels, data, rows)
    n_none = sum(1 for r in rows if not r[4])
    print(f"availability: {len(rows)} calls, {n_none} with a trap no probed System implements")
    return 0


def write_doc(labels, data, rows):
    runs = {r[0]: r for r in RUNS}
    out = ["# Systems and Toolbox availability", "",
           "Generated by `tools/availability.py`; do not edit.", "",
           "Every System on Apple's 1989-92 Developer CDs, and the later ones",
           "in the project's library, was booted in an emulator with",
           "`tools/probe/trapprobe.c` in place of the Finder. The probe records",
           "which trap table entries are implemented, which `PACK` resources",
           "exist and what Gestalt says. `data/probe.tsv` has the raw results",
           "and `data/availability.tsv` the result for every call.", "",
           "## Systems tested", "",
           "| System | Machine | ROM | Emulator | OS traps | Toolbox traps | Gestalt |",
           "|---|---|---|---|---|---|---|"]
    for l in labels:
        _, sv, _, cls, mach, emu = runs[l]
        nos = sum(1 for i in range(256) if data["A%03X" % i][l] == "1")
        ntb = sum(1 for i in range(1024) if data["A%03X" % (0x800 + i)][l] == "1")
        ntot = sum(1 for i in range(1024) if data["A%03X" % (0x800 + i)][l] != "-")
        romv = data["romv"][l]
        rom = {"0069": "64K ($69)", "0075": "128K ($75)", "0178": "256K ($178)",
               "067C": "1M ($67C)", "0000": "New World"}.get(romv, romv)
        g = data.get("gestalt sysv", {}).get(l, "-")
        gest = "no" if g in ("-", "err") else "$" + g[-4:]
        out.append(f"| {sv} | {mach} | {rom} | {emu} | {nos} | {ntb} of {ntot} | {gest} |")
    out += ["",
            "Notes:", "",
            "- System 0.7 and the 1.0 and 1.1 800K disks only boot with the 128K",
            "  ROM, so they ran on a Mac Plus; the 400K MFS disks ran on a Mac",
            "  128K or 512K.",
            "- System 7.0 is the base System file from the Install 1 disk, which",
            "  the Installer completes, so its packages are fewer than a real",
            "  install has. 7.0, 7.0.1 and 7.1 on the Mac Plus and Mac IIx booted",
            "  from an emulated SCSI hard disk.",
            "- 7.6.1 and 8.1 booted from their CDs on QEMU's Quadra 800 and sent",
            "  the results out of the modem port. 9.2.1 ran the PowerPC build.", "",
            "## Checking at run time", "",
            "`TrapAvailable(trap)` (in `<OSUtils.h>`) is true when the trap is",
            "implemented, on every ROM from the Mac 128K's on. Check before",
            "calling anything newer than the oldest System you support:", "",
            "```c",
            "if (TrapAvailable(_Gestalt))           /* System 6.0.4 and later */",
            "    err = Gestalt(gestaltSystemVersion, &sysv);",
            "```", "",
            "For a call that goes through a dispatcher trap, the trap being there",
            "only says the dispatcher is; ask Gestalt about the feature (for",
            "example `gestaltFSAttr` for `FSMakeFSSpec`).", "",
            "## Compile-time checks", "",
            "Build with `-DMAC_MIN_SYSTEM=0x0605` (any System version) and the",
            "headers warn at every call whose trap no measured System older",
            "than that implements. Add `-DMAC_NO_COLOR_QD` to also warn about",
            "calls that only Color QuickDraw Macs have.", "",
            "## New in each System", "",
            "The calls whose trap first appears in each System, on the oldest",
            "machine that has it. Calls through a dispatcher are marked *; for",
            "those the System given is the dispatcher's.", ""]
    by = {}
    gated = {}
    for name, hdr, trap, sel, av, disp, g in rows:
        if g:
            gated.setdefault((hdr, g), []).append(av)
            continue
        if not av:
            continue
        ver, cls, _ = av
        by.setdefault((ver, cls), []).append((name, disp))
    for (ver, cls) in sorted(by, key=lambda k: (k[0], CLASSES.index(k[1]))):
        names = sorted(by[(ver, cls)])
        out.append(f"### System {vtext(ver)}, {CLASS_TEXT[cls]} ({len(names)} calls)")
        out.append("")
        if ver == 0x0010 and cls == "64K":
            out.append("Everything in the Mac 128K's 64K ROM: available on every Mac.")
            out.append("")
            continue
        out.append(", ".join(f"`{n}`" + ("*" if d else "") for n, d in names))
        out.append("")
    out += ["## Managers checked with Gestalt", "",
            "These managers share dispatcher traps that older Systems fill",
            "with other code, so the tables count a call as available only",
            "where its manager's Gestalt selector answers too. Some of them",
            "came as extensions before they were built in (QuickTime, the",
            "Communications Toolbox, the Drag Manager, Threads); the System",
            "given is the oldest measured one that had the manager.", "",
            "| Header | Gestalt | First measured System | Calls |", "|---|---|---|---|"]
    for (hdr, g), avs in sorted(gated.items()):
        have = [a for a in avs if a]
        if have:
            ver, cls, _ = min(have, key=lambda a: (a[0], CLASSES.index(a[1])))
            first = f"{vtext(ver)}, {CLASS_TEXT[cls]}"
        else:
            first = "none (an extension none of them had)"
        out.append(f"| {hdr} | `'{g}'` | {first} | {len(avs)} |")
    out.append("")
    missing = [(n, t) for n, h, t, s, av, d, g in rows if not av and not g]
    out += ["## Not implemented by any measured System", "",
            "Calls whose trap word no probed System implements: traps of",
            "optional extensions (for example the Communications Toolbox,",
            "Speech Manager or Drag Manager before they were built in) and",
            "machine-specific ones (Power Manager, PowerBook calls).", "",
            ", ".join(f"`{n}` (${t:04X})" for n, t in sorted(missing)), ""]
    open(DOC, "w").write("\n".join(out))


if __name__ == "__main__":
    sys.exit(main())
