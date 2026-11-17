#!/usr/bin/env python3
"""Bounded replay of native composite-member DM/PM/SDRAM arena carving.

The loaded firmware code is executed, not reimplemented. Entry context is
explicitly synthetic: I1 is the selected 20-word member record, I0/I4 address
its parent's arenas, and I3 addresses an already-created child descriptor.
The selected native descriptor-copy caller is executed; outer graph traversal
and the process dispatcher are not executed.
No hardware, firmware patching, or model registration is performed.

Encoding source: ADI SHARC Programming Reference rev2.4 chapters9/10/12:
https://www.analog.com/media/en/dsp-documentation/processor-manuals/ADSP-2136x_2137x_214xx_pgr_rev2.4.pdf
"""
import hashlib

import microlooper_visa as visa
import sasm
import ssim

ENTRY = 0x177f8c
SUCCESS = 0x17801d
FAILURE = 0x178132
# The native composite constructor selects the member array from header field3.
MEMBER_ARRAY_LOAD = 0x177f22


def _replay_member_arenas(e2, *, dm_words=199, pm_words=0, sdram_words=48000,
                         dm_begin=0xb3000, dm_end=0xb3400,
                         pm_begin=0xe1000, pm_end=0xe1100,
                         sdram_begin=0x400000, sdram_end=0x463000,
                         parcel_order='high-first', external_parcel_order='low-first',
                         limit=256):
    """Execute original member fields13/14/15 -> descriptor0..8 carving.

    The fixture supplies the parent arena record. Native code aligns its SDRAM
    current, calls the original27-word memcpy, resets child begins to currents,
    and performs all three extent assignments. It also
    executes the three original instructions that derive I8=member+20 (so the
    PM(-7,I8) count read really selects member field13). The two bounded code
    spans are entered explicitly; intervening graph traversal is not executed.
    """
    values = (dm_words, pm_words, sdram_words, dm_begin, dm_end,
              pm_begin, pm_end, sdram_begin, sdram_end)
    if any(type(value) is not int or not 0 <= value <= ssim.M32 for value in values):
        raise ValueError('counts and arena addresses must be unsigned32 integers')
    sim, short = visa.load(e2, parcel_order=parcel_order,
                           external_parcel_order=external_parcel_order)
    parent, member, child, stack = 0xb4000, 0xb5000, 0xb6000, 0xc7000
    # Explicit pre-existing parent arenas. Child words must be copied by code.
    arenas = [dm_begin, dm_end, dm_begin, pm_begin, pm_end, pm_begin,
              sdram_begin, sdram_end, sdram_begin] + [0] * 18
    for offset, value in enumerate(arenas):
        sim.wr(parent + offset, value)
        sim.wr(child + offset, 0xa5a5a5a5)
    for address in (parent-1,parent+28,child-1,child+27):
        sim.wr(address,0xdeadbeef)
    sim.wr(member + 13, dm_words)
    sim.wr(member + 14, pm_words)
    sim.wr(member + 15, sdram_words)
    sim.wr(stack + 1, parent)
    sim.wr(stack - 3, parent)
    for code, value in ((0x10, parent + 8), (0x11, member), (0x13, child),
                        (0x14, parent), (0x16, stack), (0x17, stack),
                        (13,child),(1, pm_begin),(0x25, 0),(0x26, 1),
                        (0x27, ssim.M32),(0x2d,0),(0x2e,1),(0x2f,ssim.M32)):
        sim.set(code, value)
    sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x40000
    sim.strict_cbufen = True
    setup_addresses = []
    sim.pc = 0x177f54
    for _ in range(3):
        pc = sim.pc
        instruction = visa.decode([short[pc + j] for j in range(3)])
        setup_addresses.append(pc)
        visa.step(sim, instruction)
    member_tail = sim.get(0x18)
    writes, reads, executed = [], [], []
    original_read, original_write = sim.rd, sim.wr
    def read(address):
        reads.append((sim.pc, address & ssim.M32))
        return original_read(address)
    def write(address, value):
        writes.append((sim.pc, address & ssim.M32, value & ssim.M32))
        original_write(address, value)
    sim.rd, sim.wr = read, write
    sim.pc = ENTRY
    reason = 'instruction bound'
    for _ in range(limit):
        if sim.pc in (SUCCESS, FAILURE):
            reason = 'allocated' if sim.pc == SUCCESS else 'arena exhausted'
            break
        pc = sim.pc
        executed.append(pc)
        if pc in short:
            instruction = visa.decode([short[pc + j] for j in range(3) if pc + j in short],
                                      immediate16_extension='sign-extend')
            visa.step(sim, instruction)
        elif pc in sim.pm:
            sim.step()
        else:
            raise visa.UnsupportedVisa('allocator code is absent from loaded records')
    descriptor = [original_read(child + offset) for offset in range(9)]
    def provenance_read(pc, address):
        return (pc, address) in reads
    report = {
        'entry2_sha256': hashlib.sha256(e2).hexdigest(),
        'synthetic_context': True,
        'init16_parcel_order_assumed': parcel_order,
        'external_visa_parcel_order_assumed': external_parcel_order,
        'negative_literal_extension_assumed': 'sign-extend',
        'complete_prefix': sim.pc == SUCCESS,
        'stop_address': sim.pc, 'stop_reason': reason,
        'executed_addresses': executed,
        'member_tail_setup_addresses': setup_addresses,
        'member_tail_i8': member_tail,
        'member_count_reads': {
            'dm_field13': provenance_read(0x177fd4, member + 13),
            'pm_field14': provenance_read(0x177fee, member + 14),
            'sdram_field15': provenance_read(0x178006, member + 15)},
        'pm_descriptor_begin_end': descriptor[3:5],
        'sdram_descriptor_begin_end': descriptor[6:8],
        'dm_descriptor_begin_end_current': descriptor[:3],
        'parent_dm_current': original_read(parent + 2),
        'parent_pm_current': original_read(parent + 5),
        'parent_sdram_current': original_read(parent + 8),
        'memory_guards_intact': all(original_read(address)==0xdeadbeef
                                   for address in (parent-1,parent+28,child-1,child+27)),
        'writes': writes,
        'native_allocation_verified': False,
        'private_dm_allocation_executed': 0x177fd4 in executed,
        'private_dm_extent_assigned': 0x177fea in executed,
        'descriptor_copy_executed': all(pc in executed for pc in (0x177fa8,0x8c69f,0x177faf)),
        'native_init_caller_verified': False,
        'process_i0_verified': False,
    }
    return report, sim, short


def inspect_member_arenas(e2, **context):
    """Replay selected stock member allocation; see explicit context above."""
    return _replay_member_arenas(e2, **context)[0]


def inspect_process_private_binding(e2, *, process_entry=0xe3000, **context):
    """Compose native allocation, process-record creation and native dispatch.

    All three spans execute original code on the same simulator state. Outer
    graph traversal, input/output port resolution and registry lookup remain
    explicit context. The process is stopped at entry, before executing audio.
    """
    report, sim, short = _replay_member_arenas(e2, **context)
    if not report['complete_prefix']:
        raise ValueError('process binding requires a successful member allocation')
    child, member, call_record, program = 0xb6000, 0xb5000, 0xb8000, 0xb9000
    input_address, output_address = 0xba000, 0xbb000
    if type(process_entry) is not int or not 0 <= process_entry <= 0xffffff:
        raise ValueError('process entry must be an unsigned24 PM address')
    sim.wr(child + 35, process_entry)  # Registry callback assignment is separate.
    sim.wr(call_record + 1, 0)
    sim.set(0x12, call_record + 2)
    sim.set(0x1b, member)
    sim.set(6, 4)
    sim.set(2, 5)
    sim.set(3, 0)
    sim.set(5, 0)
    sim.set(14, 0)
    def run_until(start, end, limit=64):
        sim.pc = start
        addresses = []
        for _ in range(limit):
            if sim.pc == end:
                return addresses
            pc = sim.pc
            addresses.append(pc)
            if pc in short:
                instruction = visa.decode([short[pc + j] for j in range(3)],
                                          immediate16_extension='sign-extend')
                visa.step(sim, instruction)
            elif pc in sim.pm:
                sim.step()
            else:
                raise visa.UnsupportedVisa('binding code absent from loaded records')
        raise ValueError('native process-binding span exceeded instruction bound')
    creation = run_until(0x178139, 0x178155)
    # The intervening port-resolution span leaves I2 at record+10. This test
    # does not infer its audio layout: input/output buffer pointers are supplied.
    sim.set(0x12, call_record + 10)
    binding = run_until(0x17827d, 0x1781b7)
    sim.wr(call_record + 6, input_address)
    sim.wr(call_record + 7, output_address)
    sim.wr(program, call_record)
    sim.set(0x17, program)
    sim.set(0, 1)
    sim.set(0x2f, 0)
    dispatch = run_until(0x8cb37, process_entry)
    report.update(
        process_record_creation_addresses=creation,
        private_binding_addresses=binding,
        process_dispatch_addresses=dispatch,
        process_record_descriptor=sim.rd(call_record+2),
        process_record_private_dm=sim.rd(call_record+4),
        process_record_pm=sim.rd(call_record+5),
        process_entry_registers={name:sim.get(code) for name,code in
                                 (('i0',0x10),('i1',0x11),('i2',0x12),
                                  ('i3',0x13),('i8',0x18))},
        process_i0_verified=(sim.get(0x10)==report['dm_descriptor_begin_end_current'][0]),
        outer_graph_traversal_executed=False,
        audio_buffer_layout_verified=False,
        registry_callback_assignment_executed=False,
    )
    return report


def inspect_constructor_member_source(e2, *, parcel_order='high-first'):
    """Check original decoded constructor selection, not inferred field numbers."""
    _, short = visa.load(e2, parcel_order=parcel_order)
    instruction = visa.decode([short[MEMBER_ARRAY_LOAD + j] for j in range(3)])
    sections, _ = sasm.assemble('.section pm 0xe0000\nI1 = DM(3,I1);')
    expected = sections[0].words[0]
    return {'member_array_selection_verified': instruction.isa == expected,
            'selection_address': MEMBER_ARRAY_LOAD,
            'decoded_instruction': 'I1 = DM(3,I1)',
            'native_allocation_verified': False}
