#!/usr/bin/env python3
"""Bounded, conditional inspection of AcousticSim's input copy and first float use.

This is not a general VISA emulator or native ABI proof. The caller must choose
parcel orders explicitly. The input-loop replay uses supplied private fields;
a separate replay executes the original initializer only through its dimension
assignments. Unsupported compact forms stop inspection.

Encoding source: ADI SHARC Programming Reference rev2.4, chapters9/10/12.
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


def inspect_initializer_fields(e2, *, parcel_order, external_parcel_order,
                               init_r12, init_r8=0, limit=1500):
    """Run only until original initializer has assigned private fields0..2.

    Synthetic descriptor/stack and argument values are explicit. No callbacks
    are skipped; this does not establish what the real initializer caller uses.
    """
    sim, short = load(e2, parcel_order=parcel_order,
                      external_parcel_order=external_parcel_order)
    state, instance, stack = 0xb3000, 0xb6000, 0xc6d98
    for code, value in ((4, instance), (8, init_r8), (12, init_r12),
                        (0x16, stack), (0x17, stack), (0x25, 0), (0x26, 1),
                        (0x27, 0xffffffff), (0x2d, 0), (0x2e, 1), (0x2f, 0xffffffff)):
        sim.set(code, value)
    for j, value in enumerate((state, state + 129, state, 0xe2000, 0xe2000,
                               0xe2000, 0x400000, 0x400400)):
        sim.wr(instance + j, value)
    sim.u[ssim.U_MODE1] = 0x40000
    sim.pc = 0x61525a
    events = []
    original_write = sim.wr
    def record_write(address, value):
        if state <= address < state + 3 and value:
            events.append({'pc': sim.pc, 'field': address - state, 'value': value & ssim.M32})
        original_write(address, value)
    sim.wr = record_write
    reason, complete, steps = 'instruction bound', False, 0
    for _ in range(limit):
        pc = sim.pc
        steps += 1
        try:
            if pc in short:
                step(sim, decode([short[pc + j] for j in range(3) if pc + j in short]))
            elif pc in sim.pm:
                sim.step()
            else:
                raise UnsupportedVisa('code address is not present in loaded records')
        except (UnsupportedVisa, ssim.SimError) as error:
            reason = str(error)
            break
        if pc == 0x601113:
            reason, complete = 'private fields0..2 assigned', True
            break
    return {'native_stereo_abi_verified': False, 'synthetic_context': True,
            'init16_parcel_order_assumed': parcel_order,
            'external_visa_parcel_order_assumed': external_parcel_order,
            'init_argument_r12_assumed': init_r12, 'init_argument_r8_assumed': init_r8,
            'native_init_caller_verified': False, 'initializer_prefix_complete': complete,
            'stop_reason': reason, 'stop_address': sim.pc, 'steps': steps,
            'private_prefix': [sim.rd(state + j) for j in range(3)],
            'nonzero_prefix_writes': events,
            'field0_source': 'initializer constant16 at0x615279 via global DM0x2122d0',
            'field2_source': 'initializer constant2 at0x6152a6 via global DM0x2122d2'}


def inspect_buffer_geometry(e2, *, parcel_order):
    """Validate selected decoded address expressions, without running DSP helpers."""
    _, short = load(e2, parcel_order=parcel_order)
    def at(pc):
        return decode([short[pc + j] for j in range(3)]).isa
    def compute(pc, cu, op, n, x, y):
        c = at(pc) & 0x7fffff
        return (c >> 20 & 3, c >> 12 & 255, c >> 8 & 15,
                c >> 4 & 15, c & 15) == (cu, op, n, x, y)
    def load_field(pc, offset):
        word = at(pc)
        return (word >> 45 == 3 and not (word >> 44 & 1) and
                word >> 41 & 7 == 1 and word >> 23 & 15 == 2 and
                word >> 27 & 63 == offset and not (word >> 39 & 1))
    branch = at(0x13b14e)
    checks = {
        'row_index_zero': compute(0x13ae1d, 0, 2, 13, 13, 13),
        'input_row_multiply': compute(0x13ae5d, 1, 0x70, 0, 13, 1),
        'input_base_field3': load_field(0x13ae5d, 3),
        'input_row_add': compute(0x13ae60, 0, 1, 2, 0, 2),
        'output_row_multiply': compute(0x13b126, 1, 0x70, 0, 13, 1),
        'output_base_field4': load_field(0x13b126, 4),
        'output_row_add': compute(0x13b129, 0, 1, 2, 2, 0),
        'row_index_increment': compute(0x13b147, 0, 0x29, 13, 13, 0),
        'row_bound_field2': load_field(0x13b14a, 2),
        'row_bound_compare': compute(0x13b14d, 0, 0xa, 13, 13, 2),
        'row_loop_branch': (branch >> 40 == 7 and branch >> 33 & 31 == 1 and
                            bool(branch >> 26 & 1) and
                            0x13b14e + ssim.sx(branch & 0xffffff, 24) == 0x13ae58),
    }
    # Both row setup paths read field0 through I1 with the C environment's M5=0.
    for label, pc in (('input_width_field0', 0x13ae58), ('output_width_field0', 0x13b125)):
        word = at(pc)
        checks[label] = (word >> 45 == 2 and word >> 41 & 7 == 1 and
                         word >> 38 & 7 == 5 and word >> 23 & 127 == 1 and
                         not (word >> 31 & 1))
    if not all(checks.values()):
        raise UnsupportedVisa('conditional buffer-geometry instruction checks differ: ' +
                              ', '.join(key for key, value in checks.items() if not value))
    return {'native_stereo_abi_verified': False, 'init16_parcel_order_assumed': parcel_order,
            'decoded_checks': checks, 'row_width_field': 0, 'row_count_field': 2,
            'input_base_field': 3, 'output_base_field': 4,
            'row_index_register': 13,
            'input_expression': 'incoming I1 + j * private DM[0] + k',
            'output_row_base_expression': 'incoming I2 + j * private DM[0]',
            'index_bounds': '0 <= j < private DM[2]; 0 <= k < private DM[0]',
            'field_meanings_verified': False, 'input_words_proven_float': False}


def inspect_first_input_loop(e2, *, parcel_order, private_fields, limit=512,
                             stop_after_input_loop=True, immediate16_extension=None,
                             stop_at_float_use=False, input_words=None):
    """Trace stock3.80 with explicit synthetic fields; stop before later DSP code."""
    if not all(key in private_fields for key in (0, 2, 12, 122)):
        raise ValueError('explicit private-state fields0,2,12,122 are required')
    sim, short = load(e2, parcel_order=parcel_order)
    state, call, instance, source, output = 0xb3000, 0xb4000, 0xb6000, 0xb8000, 0xb9000
    for code, value in ((0x10, state), (0x11, source), (0x12, output),
                        (0x13, call), (0x18, 0xe1000), (0x21, 1), (0x29, 1)):
        sim.set(code, value)
    sim.wr(call + 2, instance)
    sim.wr(instance, state)
    for offset, value in private_fields.items():
        sim.wr(state + offset, value)
    input_words = list(input_words) if input_words is not None else [0x3e800000 + j for j in range(64)]
    if len(input_words) < private_fields[0]:
        raise ValueError('input words must cover the first copied row')
    for j, word in enumerate(input_words):
        sim.wr(source + j, word)
    sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x40000
    sim.pc = 0x8e9e3
    addresses, pcs, reads, copy_index, staging_reads = [], [], [], None, []
    read_values, copies, register_source = {}, {}, None
    pending_input, float_use = None, None
    pointer_reads, extension_sites = [], []
    original_read = sim.rd
    original_write, original_compute = sim.wr, sim.compute1
    def record_read(address):
        reads.append(address)
        value = original_read(address)
        read_values[address] = value
        if address == input_words[0]:
            pointer_reads.append({'pc': sim.pc, 'address': address})
        return value
    def record_write(address, value):
        if sim.pc == 0x13ae6d and pending_input is not None and value & ssim.M32 == pending_input['word']:
            copies[address] = dict(pending_input, staging_address=address, staging_write_pc=sim.pc)
        original_write(address, value)
    def record_compute(compute):
        nonlocal float_use
        shape = (compute >> 20 & 3, compute >> 12 & 255, compute >> 8 & 15,
                 compute >> 4 & 15, compute & 15)
        if (sim.pc == 0x1828ab and shape == (1, 0x30, 12, 2, 4) and
                register_source is not None and sim.R(4) == register_source['word']):
            float_use = dict(register_source, compute_pc=sim.pc,
                             operation='F12 = F2 * F4', sample_register=4,
                             coefficient_register=2, coefficient_word=sim.R(2))
        original_compute(compute)
    sim.rd = record_read
    sim.wr, sim.compute1 = record_write, record_compute
    reason, complete = 'instruction bound', False
    for _ in range(limit):
        if sim.pc == 0x13ae70:
            complete = True
            if stop_after_input_loop:
                reason = 'first input-copy loop ended'
                break
        pc = sim.pc
        if pc == 0x13ae5d:
            copy_index = sim.get(13)
        pcs.append(pc)
        reads.clear()
        try:
            if pc in short:
                instruction = decode([short[pc + j] for j in range(3) if pc + j in short],
                                     immediate16_extension=immediate16_extension)
                if instruction.form.startswith('17b:assumed-'):
                    extension_sites.append({'pc': pc, 'register': instruction.isa >> 32 & 127,
                                            'value': instruction.isa & ssim.M32})
                step(sim, instruction)
            elif pc in sim.pm:
                sim.step()
            else:
                raise UnsupportedVisa('code address is not present in loaded records')
        except (UnsupportedVisa, ssim.SimError) as error:
            reason = str(error)
            break
        if pc == 0x13ae6a:
            addresses.extend(reads)
            if len(reads) == 1:
                pending_input = {'input_read_pc': pc, 'input_address': reads[0],
                                 'word': read_values[reads[0]]}
        if pc == 0x1828a9 and instruction.form == '1b:dual-load':
            word = instruction.isa
            # Validate DM input side of the dual-load; the next instruction
            # consumes its unmodified R4 as F4. No value-equality-only taint.
            shape = (word >> 41 & 7, word >> 38 & 7, word >> 33 & 15)
            matches = [address for address in reads if address in copies]
            if shape == (4, 6, 4) and len(matches) == 1 and sim.R(4) == copies[matches[0]]['word']:
                register_source = dict(copies[matches[0]], staging_read_pc=pc)
        staging_reads.extend((pc, address) for address in reads
                             if private_fields[122] <= address < private_fields[122] + private_fields[0])
        if float_use is not None and pc == float_use['compute_pc']:
            float_use['result_word'] = sim.R(12)
            if stop_at_float_use:
                reason = 'first copied input word consumed as floating-point operand'
                break
    return {'native_stereo_abi_verified': False, 'synthetic_context': True,
            'constructor_executed': False, 'init16_parcel_order_assumed': parcel_order,
            'private_fields_assumed': dict(private_fields), 'first_input_loop_complete': complete,
            'negative_immediate16_extension_assumed': immediate16_extension,
            'negative_immediate16_sites': extension_sites,
            'stop_address': sim.pc, 'stop_reason': reason, 'steps': len(pcs),
            'executed_addresses': pcs, 'input_base': source, 'input_reads': addresses,
            'input_offsets': [address - source for address in addresses],
            'copy_index_r13': copy_index,
            'input_address_expression': 'incoming I1 + R13 * private DM[0] + k; 0 <= k < private DM[0]',
            'input_stride': sim.get(0x26),
            'staging_reads': staging_reads,
            'staging_pointer_field': 122, 'output_base': output,
            'input_words_proven_float': False,
            'conditional_float_use': float_use, 'input_word_as_address_reads': pointer_reads,
            'output_loop_verified': False, 'outer_loop_verified': False}


def inspect_input_word_float_use(e2, *, parcel_order, input_words, coefficient_word,
                                 limit=512):
    """Compare both extension hypotheses, stopping at the first input-word Fmul.

    This settles the copied word's arithmetic use under the selected parcel
    order without choosing negative-immediate16 semantics. State/coefficient
    values and sample words are synthetic, not captured native context.
    """
    fields = {0: 16, 2: 2, 12: 0, 87: coefficient_word, 122: 0xbd000, 124: 0xbd100}
    runs = [inspect_first_input_loop(
        e2, parcel_order=parcel_order, private_fields=fields, limit=limit,
        stop_after_input_loop=False, stop_at_float_use=True, input_words=input_words,
        immediate16_extension=hypothesis)
        for hypothesis in ('sign-extend', 'zero-extend')]
    uses = [run['conditional_float_use'] for run in runs]
    invariant = (uses[0] is not None and uses[0] == uses[1] and
                 not any(run['input_word_as_address_reads'] for run in runs))
    return {'native_stereo_abi_verified': False, 'init16_parcel_order_assumed': parcel_order,
            'synthetic_context': True, 'private_fields_assumed': fields,
            'negative_immediate16_extension_resolved': False,
            'extension_hypotheses_tested': ['sign-extend', 'zero-extend'],
            'copied_word_float_use_invariant': invariant,
            'conditional_float_use': uses[0] if invariant else None,
            'runs': runs}
