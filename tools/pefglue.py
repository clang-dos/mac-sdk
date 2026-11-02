#!/usr/bin/env python3
"""Read a PEF shared library and find where each exported function's code is.

Used to check 68k trap and selector numbers: on 7.x/8.x, most InterfaceLib
exports are short PowerPC glue routines that call the 68k trap through
the Mixed Mode Manager, so the glue holds the trap word, the selector and
the procInfo (the size of each argument).
"""
import struct


def unpack_pidata(src, size):
    """Expand a PEF pattern-initialized data section."""
    out = bytearray()
    i = 0

    def count():
        nonlocal i
        n = 0
        while True:
            b = src[i]
            i += 1
            n = (n << 7) | (b & 0x7F)
            if not b & 0x80:
                return n
    while i < len(src) and len(out) < size:
        b = src[i]
        i += 1
        op, n = b >> 5, b & 0x1F
        if n == 0:
            n = count()
        if op == 0:                       # zero
            out += bytes(n)
        elif op == 1:                     # block
            out += src[i:i + n]
            i += n
        elif op == 2:                     # repeat block
            r = count() + 1
            blk = src[i:i + n]
            i += n
            out += blk * r
        elif op == 3:                     # interleave block with block
            custom, rep = count(), count()
            common = src[i:i + n]
            i += n
            for _ in range(rep):
                out += common + src[i:i + custom]
                i += custom
            out += common
        elif op == 4:                     # interleave zeros with block
            custom, rep = count(), count()
            for _ in range(rep):
                out += bytes(n) + src[i:i + custom]
                i += custom
            out += bytes(n)
        else:
            raise ValueError(f"pidata opcode {op}")
    return bytes(out)


class Pef:
    def __init__(self, blob):
        assert blob[:8] == b"Joy!peff"
        self.blob = blob
        n = struct.unpack_from(">H", blob, 32)[0]
        self.sections = []
        for k in range(n):
            (_, _, exec_size, init_size, raw_size, off, kind, _, _,
             _) = struct.unpack_from(">iIIIIIBBBB", blob, 40 + 28 * k)
            raw = blob[off:off + raw_size]
            if kind == 2:
                data = unpack_pidata(raw, init_size)
            else:
                data = raw
            self.sections.append((kind, data + bytes(max(0, exec_size - len(data)))))
        loader = next(d for k, d in self.sections if k == 4)
        (_, _, _, _, _, _, nlibs, nimp, nrel, _, strings, hash_off, power,
         nexp) = struct.unpack_from(">iIiIiIIIIIIIII", loader, 0)
        keys = hash_off + 4 * (1 << power)
        syms = keys + 4 * nexp
        self.exports = {}
        for e in range(nexp):
            length = struct.unpack_from(">I", loader, keys + 4 * e)[0] >> 16
            word, value, sect = struct.unpack_from(">IIh", loader, syms + 10 * e)
            nm = loader[strings + (word & 0xFFFFFF):][:length].decode("mac_roman")
            self.exports[nm] = ((word >> 24) & 0xF, sect, value)

    def code_of(self, name):
        """Return (code bytes, offset) for an exported function."""
        cls, sect, value = self.exports[name]
        if cls != 2:
            return None
        data = self.sections[sect][1]
        target = struct.unpack_from(">I", data, value)[0]
        code = next(d for k, d in self.sections if k == 0)
        return code, target


class Sym:
    """A value the glue computes: a constant, an argument, or a load."""
    def __init__(self, kind, v):
        self.kind, self.v = kind, v

    def __repr__(self):
        return f"{self.kind}:{self.v:#x}" if isinstance(self.v, int) \
            else f"{self.kind}:{self.v}"


def s16(x):
    return x - 0x10000 if x & 0x8000 else x


def run_glue(code, off, limit=40):
    """Interpret the glue up to its first call. Returns (call target, regs)
    or None. Arguments arrive in r3-r10."""
    regs = {i: Sym("arg", i - 3) for i in range(3, 11)}
    regs[0] = Sym("const", 0)
    for k in range(limit):
        pc = off + 4 * k
        if not 0 <= pc <= len(code) - 4:
            return None
        w = struct.unpack_from(">I", code, pc)[0]
        op = w >> 26
        rd, ra, imm = (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF

        def get(r, zero_is_0=True):
            if r == 0 and zero_is_0:
                return Sym("const", 0)
            return regs.get(r, Sym("unknown", r))
        if op in (14, 15, 12):            # addi, addis, addic
            base = get(ra, op != 12)
            add = s16(imm) << 16 if op == 15 else s16(imm)
            if base.kind == "const":
                regs[rd] = Sym("const", (base.v + add) & 0xFFFFFFFF)
            elif add == 0:
                regs[rd] = base
            else:
                regs[rd] = Sym("unknown", None)
        elif op in (24, 25):              # ori, oris: rA = rS | imm
            src = regs.get(rd, Sym("unknown", rd))
            if src.kind == "const":
                regs[ra] = Sym("const", src.v | (imm << 16 if op == 25 else imm))
            elif imm == 0:
                regs[ra] = src
            else:
                regs[ra] = Sym("unknown", None)
        elif op == 32:                    # lwz
            base = get(ra)
            if base.kind == "const":
                regs[rd] = Sym("lowmem", (base.v + s16(imm)) & 0xFFFFFFFF)
            else:
                regs[rd] = Sym("unknown", None)
        elif op == 31 and ((w >> 1) & 0x3FF) == 444:   # or (mr)
            rs, rb = rd, (w >> 11) & 31
            if rs == rb:
                regs[ra] = regs.get(rs, Sym("unknown", rs))
        elif op == 18:                    # b, bl
            li = w & 0x03FFFFFC
            if li & 0x02000000:
                li -= 0x04000000
            if w & 1:
                return pc + li, regs
            return None                   # a jump: not simple glue
        elif op == 19 and ((w >> 1) & 0x3FF) == 16:    # blr
            return None
        elif op in (36, 37, 31, 21, 10, 11, 32, 34, 40, 44, 46, 47, 7):
            if op == 31 and ((w >> 1) & 0x3FF) in (339,):   # mfspr
                continue
            if op in (36, 37, 44, 47):    # stores
                continue
            if op == 31 and ((w >> 1) & 0x3FF) in (922, 954):  # extsh, extsb
                regs[ra] = regs.get(rd, Sym("unknown", rd))
                continue
            if op == 21:                  # rlwinm
                regs[ra] = regs.get(rd, Sym("unknown", rd))
                continue
            if op in (10, 11):            # compares
                continue
            regs[rd] = Sym("unknown", None)
    return None
