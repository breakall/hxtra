"""Decode and execute native VISA instructions for allocation/callback checks.

Encoding: ADI SHARC Programming Reference rev2.4, chapters9/10/12.
https://www.analog.com/media/en/dsp-documentation/processor-manuals/ADSP-2136x_2137x_214xx_pgr_rev2.4.pdf
"""
from dataclasses import dataclass
import struct

import microlooper_adapter as adapter
import ssim


class UnsupportedVisa(ValueError):
    pass


@dataclass(frozen=True)
class Instruction:
    length: int                     # short words, not simulator cycles
    isa: int                        # equivalent supported traditional encoding
    form: str


def decode(parcels, *, immediate16_extension=None):
    """Decode only supported forms for the bounded inspection paths."""
    if immediate16_extension not in (None, 'sign-extend', 'zero-extend'):
        raise ValueError('unknown immediate16 extension hypothesis')
    if not parcels:
        raise UnsupportedVisa('missing instruction parcel')
    p = parcels[0]
    if p == 1:
        return Instruction(1, 0, '21c:NOP')
    if p == 0x1901:
        return Instruction(1, 0x190000000000, '25c:RFRAME')
    if p >> 12 == 0xc:
        op, n, x = p >> 8 & 15, p >> 4 & 15, p & 15
        if op == 15:
            return Instruction(1, (0x13e << 32) | (1 << 20) | (0x30 << 12) |
                               (n << 8) | (n << 4) | x, '2c:float-multiply')
        alu = {0: 1, 1: 2, 2: 0x21, 3: 0x0a, 4: 0x43, 5: 0x29, 6: 0x2a,
               8: 0x81, 9: 0x82, 10: 0xca, 11: 0x8a, 12: 0x40, 13: 0x41, 14: 0x42}.get(op)
        if alu is None:
            raise UnsupportedVisa('short multiply form is not implemented')
        binary = op in (0, 1, 3, 8, 9, 11, 12, 13, 14)
        compute = (alu << 12) | (n << 8) | ((n if binary else x) << 4) | (x if binary else 0)
        return Instruction(1, (0x13e << 32) | compute, '2c:short-ALU')
    if p >> 12 == 9 and p & 0x10:
        i, m, direction, reg = p >> 9 & 7, p >> 6 & 7, p >> 5 & 1, p & 15
        word = ((2 << 45) | (1 << 44) | (i << 41) | (m << 38) |
                (31 << 33) | (direction << 31) | (reg << 23))
        return Instruction(1, word, '3c:DM-postmodify')
    if len(parcels) < 2:
        raise UnsupportedVisa('missing second instruction parcel')
    q = parcels[1]
    if p >> 12 == 9 and p & 0x1f == 4:
        if q & 0x8000:
            if immediate16_extension is None:
                raise UnsupportedVisa('negative memory-immediate16 extension is not established here')
            value = ssim.sx(q, 16) & ssim.M32 if immediate16_extension == 'sign-extend' else q
            form = '16b:assumed-' + immediate16_extension
        else:
            value, form = q, '16b:positive-memory-immediate16'
        i, m, g = p >> 9 & 7, p >> 6 & 7, p >> 5 & 1
        return Instruction(2, (9 << 44) | (i << 41) | (m << 38) | (g << 37) | value, form)
    if p >> 12 == 9 and p & 0x1f == 8:
        if p & 0xc0 or q & 0xc000:
            raise UnsupportedVisa('LW/reserved offset-move fields are unsupported')
        # Type15b: G is bit37 of the manual's left-aligned32-bit diagram,
        # hence bit5 of the first parcel.  The 010 selector is bits36..34.
        # Nonzero L/reserved fields remain outside this bounded decoder.
        i, direction, g, reg = p >> 9 & 7, p >> 8 & 1, p >> 5 & 1, q >> 7 & 127
        offset = ssim.sx(q & 127, 7)
        return Instruction(2, (5 << 45) | (g << 44) | (i << 41) | (direction << 40) |
                           (reg << 32) | (offset & ssim.M32),
                           '15b:' + ('PM' if g else 'DM') + '-offset7')
    if p >> 8 == 0xf and p & 0x80:
        if q & 0x8000:
            if immediate16_extension is None:
                raise UnsupportedVisa('negative immediate16 extension is not established here')
            value = ssim.sx(q, 16) & ssim.M32 if immediate16_extension == 'sign-extend' else q
            return Instruction(2, (0xf << 40) | ((p & 127) << 32) | value,
                               '17b:assumed-' + immediate16_extension)
        return Instruction(2, (0xf << 40) | ((p & 127) << 32) | q, '17b:positive-immediate16')
    if p >> 8 == 1 and p & 0x80:
        return Instruction(2, (0x13e << 32) | ((p & 127) << 16) | q, '2b:compute')
    if p >> 13 in (2, 3) and q & 127 == 63:
        return Instruction(2, ((p << 32) | (q << 16)) & ~0x7fffff,
                           '3b/4b/5b:move-without-compute')
    if p >> 13 == 1 and q & 127 == 63:
        if p & 0x1020:
            raise UnsupportedVisa('compact dual-memory stores are not implemented')
        return Instruction(2, ((p << 32) | (q << 16)) & ~0x7fffff, '1b:dual-load')
    if p >> 8 in (8, 9) and q & 127 == 63:
        return Instruction(2, ((p << 32) | (q << 16)) & ~0x7fffff,
                           '9b:branch-without-compute')
    if p >> 8 == 4 and q & 127 == 63:
        return Instruction(2, ((p << 32) | (q << 16)) & ~0x7fffff,
                           '7b:modify-without-compute')
    # These are documented traditional48-bit classes, with compact selectors
    # excluded first. Type7 and other unresolved compact groups are rejected.
    op8, top = p >> 8, p >> 13
    if (op8 == 4 or top == 1) and q & 127 == 63:
        raise UnsupportedVisa('compact modify/dual-memory form is not implemented')
    if p >> 12 == 9 and p & 0x1f:
        raise UnsupportedVisa('unresolved compact9-prefix selector')
    allowed = (top in (1, 2, 3, 4, 5) or
               op8 in (1, 2, 4, 6, 7, 8, 9, 0xc, 0xd, 0xe, 0xf, 0x10, 0x11,
                       0x12, 0x13, 0x14, 0x16, 0x17, 0x18))
    if not allowed:
        raise UnsupportedVisa('unsupported VISA instruction class')
    if len(parcels) < 3:
        raise UnsupportedVisa('missing third instruction parcel')
    return Instruction(3, (p << 32) | (q << 16) | parcels[2], 'ISA48')


def step(sim, instruction):
    """Run one translated form, correcting supported short-word PC metadata.

    CALL/RTS require additional return-address semantics and are excluded. The
    inspected C path uses CJUMP plus explicit return literals instead.
    """
    pc, word = sim.pc, instruction.isa
    op8 = word >> 40
    if op8 in (0xa, 0xb) or (op8 in (6, 7, 8, 9) and word >> 39 & 1):
        raise UnsupportedVisa('CALL/return semantics are outside the bounded path')
    if op8 in (0xc, 0xd):
        count = word >> 24 & 0xffff if op8 == 0xc else sim.get(word >> 32 & 127)
        if ssim.s32(count) <= 0:
            raise UnsupportedVisa('nonpositive VISA DO count is outside the bounded path')
    old_loops, pending = len(sim.loops), sim.pending_branch
    immediate_transfer = (op8 in (6, 7, 8, 9) and sim.cond(word >> 33 & 31)
                          and not (word >> 26 & 1))
    sim.pm[pc] = word
    sim.step()
    if len(sim.loops) > old_loops:
        sim.loops[-1][0] = pc + instruction.length
    completed_delay = pending is not None and pending[1] == 1
    # Delayed CJUMP's first two following *instructions* can have different
    # short-word lengths. Existing ssim already counts delay instructions.
    if sim.pc == pc + 1 and not immediate_transfer and not completed_delay:
        sim.pc = pc + instruction.length


def load(e2, *, parcel_order, external_parcel_order=None):
    if parcel_order not in ('high-first', 'low-first'):
        raise ValueError('select high-first or low-first INIT16 parcel order explicitly')
    if external_parcel_order not in (None, 'high-first', 'low-first'):
        raise ValueError('select a valid external VISA parcel order')
    sim, short = ssim.Sim(), {}
    for tag, count, base, payload in adapter.ldr_blocks(e2):
        if tag == 5:
            raw = struct.pack('<%dI' % len(payload), *payload)
            sim.pm.update((base + j, int.from_bytes(raw[j * 6:j * 6 + 6], 'little'))
                          for j in range(count))
        elif tag == 4:
            sim.dm.update((base + j, value) for j, value in enumerate(payload))
        elif tag == 3:
            for j in range(count):
                half = 1 - j % 2 if parcel_order == 'high-first' else j % 2
                short[base + j] = payload[j // 2] >> (16 * half) & 0xffff
        elif tag == 10 and external_parcel_order is not None:
            start = 0x600000 + 2 * (base - 0x300000)
            for j in range(2 * count):
                half = j % 2 if external_parcel_order == 'low-first' else 1 - j % 2
                short[start + j] = payload[j // 2] >> (16 * half) & 0xffff
    return sim, short
