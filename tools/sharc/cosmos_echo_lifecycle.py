#!/usr/bin/env python3
"""Read-only bounded native Cosmos lifecycle callback and traversal proofs.

Entry, graph-descriptor, arena, C-frame and ring contexts are supplied fixtures.
Original native callback-linking, reset and teardown instructions execute with
existing conditional VISA parcel interpretation; no firmware/device mutation.
This does not prove outer slot reclamation, replacement rollback or tail policy.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

import cosmos_echo_allocation as buffers
import microlooper_adapter as adapter
import microlooper_init as caller
import microlooper_visa as visa
import ssim

INSTANCE, STATE, PM = 0xb6000, 0xb3000, 0xe1000
ROOT, META, VECTOR = 0xbb000, 0xbc000, 0xbd000
BINDING, CURSOR, RING = 0xb8000, 0xb9000, 0x400000
PRIMITIVES = (0x80, 0x89, 0x102, 0x258, 0x832, 0x2397, 0x2394)
SENTINEL = 0xa5a5a5a5
FRAME, STACK = 0xc6e98, 0xc6d98
STOCK_MD5 = 'a2cd8f4ae56f49415380270ebc484bf1'


def registry(e2, primitive):
    for offset in range(0, 2256, 8):
        address = 0x200000 + offset
        if adapter.ldr_word(e2, address) == primitive:
            row = [adapter.ldr_word(e2, address+j) for j in range(8)]
            return dict(address=address, dm_words=row[6], pm_words=row[7])
    raise ValueError(f'primitive {primitive:#x} absent')


def context(e2):
    sim, short = visa.load(e2, parcel_order='high-first', external_parcel_order='low-first')
    for register, value in ((0x25, 0), (0x26, 1), (0x27, ssim.M32),
                            (0x2d, 0), (0x2e, 1), (0x2f, ssim.M32),
                            (0x37, 0), (0x16, FRAME), (0x17, STACK)):
        sim.set(register, value)
    sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x10000
    sim.strict_cbufen = True
    return sim, short


def step(sim, short):
    if sim.pc in short:
        visa.step(sim, visa.decode([short[sim.pc+j] for j in range(3)],
                                   immediate16_extension='sign-extend'))
    else:
        sim.step()


def run(sim, short, stop, limit=4096):
    executed, reads, writes = [], [], []
    original_read, original_write = sim.rd, sim.wr
    def read(address):
        reads.append((sim.pc, address))
        return original_read(address)
    def write(address, value):
        writes.append((sim.pc, address, value & ssim.M32))
        original_write(address, value)
    sim.rd, sim.wr = read, write
    try:
        for _ in range(limit):
            if sim.pc in stop:
                return dict(stop_address=sim.pc, executed_addresses=executed,
                            reads=reads, writes=writes)
            executed.append(sim.pc)
            step(sim, short)
        raise ValueError(f'lifecycle instruction bound at {sim.pc:#x}')
    finally:
        sim.rd, sim.wr = original_read, original_write


def invoke(sim, short, entry, *, argument=INSTANCE, stop=()):
    sim.set(4, argument)
    instruction = visa.decode([short[caller.CALLSITE+j] for j in range(3)])
    assert instruction.isa >> 40 == 0x18
    sim.pc = caller.CALLSITE
    visa.step(sim, visa.Instruction(instruction.length,
                                   (instruction.isa & ~0xffffff) | entry,
                                   instruction.form))
    report = run(sim, short, {caller.RETURN_SITE, *stop})
    report['balanced_c_frame'] = (sim.pc == caller.RETURN_SITE and
                                  sim.get(0x16) == FRAME and
                                  sim.get(0x17) == STACK)
    return report


def link(sim, short, row, instance=INSTANCE, state=STATE, pm=PM):
    for j in range(37):
        sim.wr(instance+j, 0)
    sim.wr(instance, state)
    sim.wr(instance+3, pm)
    sim.wr(instance+36, BINDING)
    for base, count in ((state, row['dm_words']), (pm, row['pm_words'])):
        for j in range(-1, count+1):
            sim.wr(base+j, SENTINEL)
    # Enter the actual primitive constructor's linkage slice with its lookup
    # result and already-carved descriptor; stop before its init callback call.
    sim.set(0x14, row['address'])
    sim.set(0x15, instance)
    sim.pc = 0x177a55
    result = run(sim, short, {0x177a7c})
    expected = [sim.rd(row['address']+j) or 0x1779e7 for j in range(1, 5)]
    assert [sim.rd(instance+j) for j in range(31, 35)] == expected
    return result


def primitive_cases(e2):
    results = []
    for primitive in PRIMITIVES:
        row = registry(e2, primitive)
        sim, short = context(e2)
        linkage = link(sim, short, row)
        before = dict(sim.dm)
        reset = invoke(sim, short, 0x177b87)
        assert reset['balanced_c_frame']
        nonstack = [write for write in reset['writes']
                    if not STACK-0x100 <= write[1] <= FRAME+0x100]
        expected = {0x102: [(PM+j, 0) for j in range(4)], 0x2397: [(PM+3, 0)]}.get(primitive, [])
        assert [(address, value) for _, address, value in nonstack] == expected
        assert all(sim.rd(STATE+j) == before.get(STATE+j, 0) for j in range(-1, row['dm_words']+1))
        assert all(sim.rd(PM+j) == SENTINEL for j in (-1, row['pm_words']))
        teardown = invoke(sim, short, 0x17871a)
        assert teardown['balanced_c_frame']
        assert 0x1779e7 in teardown['executed_addresses']
        assert not [write for write in teardown['writes']
                    if not STACK-0x100 <= write[1] <= FRAME+0x100]
        results.append(dict(primitive=primitive, callback_linkage=linkage,
                            reset=reset, teardown=teardown,
                            private_dm_preserved=True, pm_guards_preserved=True))
    return results


def graph_cases(e2):
    results = []
    for operation, entry in (('reset', 0x177b87), ('teardown', 0x17871a)):
        sim, short = context(e2)
        rows = [registry(e2, primitive) for primitive in (0x2397, 0x102)]
        for j, row in enumerate(rows):
            instance, state, pm = INSTANCE+j*0x100, STATE+j*0x100, PM+j*0x100
            link(sim, short, row, instance, state, pm)
            sim.wr(VECTOR+j*8+2, instance)
            sim.wr(VECTOR+j*8, 0xbe000+j*32)
            sim.wr(0xbe000+j*32+6, 1)
        for j in range(37):
            sim.wr(ROOT+j, 0)
        sim.wr(ROOT+27, 1)  # native composite flag
        sim.wr(ROOT+29, META)
        sim.wr(META+1, VECTOR)
        sim.wr(META+2, 2)
        for j in range(6):
            sim.wr(BINDING+j, SENTINEL)
        for address in (CURSOR, RING-1, RING, RING+383999, RING+384000):
            sim.wr(address, SENTINEL)
        protected = [BINDING+j for j in range(6)] + [CURSOR, RING-1, RING, RING+383999, RING+384000]
        report = invoke(sim, short, entry, argument=ROOT)
        assert report['balanced_c_frame']
        assert all(sim.rd(address) == SENTINEL for address in protected)
        if operation == 'reset':
            assert sim.rd(PM+3) == 0
            assert [sim.rd(PM+0x100+j) for j in range(4)] == [0]*4
        assert report['executed_addresses'].count(entry) == 3
        report.update(operation=operation, synthetic_two_child_composite=True,
                      ring_and_binding_preserved=True)
        results.append(report)
    # A native flag bit suppresses the primitive's reset callback.
    sim, short = context(e2)
    link(sim, short, registry(e2, 0x2397))
    sim.wr(INSTANCE+27, 2)
    report = invoke(sim, short, 0x177b87)
    assert report['balanced_c_frame'] and sim.rd(PM+3) == SENTINEL
    report.update(operation='reset_suppressed', descriptor_flag=2)
    results.append(report)
    # Stop before the additional framework operation needs a live RTOS/object
    # registry; do not pretend a zero-filled context proves its completion.
    sim, short = context(e2)
    link(sim, short, registry(e2, 0x2397))
    sim.wr(INSTANCE+27, 8)
    report = invoke(sim, short, 0x17871a, stop=(0x175ab9,))
    assert report['stop_address'] == 0x175ab9
    report.update(operation='teardown_framework_boundary', descriptor_flag=8)
    results.append(report)
    return results


def arena_rebuild_case(e2):
    sim, short = context(e2)
    # Retained descriptor owns nine arena triples. Its current may differ
    # from its begin: each build starts at that retained current frontier.
    retained = []
    for j in range(9):
        base = 0x300000 + j*0x10000
        retained.extend((base, base+0x8000, base+0x100))
    for j, value in enumerate(retained):
        sim.wr(INSTANCE+j, value)
    sim.wr(INSTANCE+27, 0)
    sim.wr(INSTANCE+28, META)
    sim.wr(META, 0)
    local = STACK-28
    expected = [value for j in range(9)
                for value in (retained[j*3+2], retained[j*3+1], retained[j*3+2])]
    reports = []
    for _ in range(2):
        # Dirty every local triple, as prior graph construction would do.
        for j in range(27):
            sim.wr(local+j, SENTINEL)
        sim.set(0x16, FRAME)
        sim.set(0x17, STACK)
        report = invoke(sim, short, 0x177d3d, stop=(0x177d93,))
        assert [sim.rd(INSTANCE+j) for j in range(27)] == retained
        assert [sim.rd(local+j) for j in range(27)] == expected
        reports.append(report)
    # Execute the native selector's original branch/call into that constructor.
    sim, short = context(e2)
    sim.set(4, INSTANCE)
    sim.set(8, 0x600024)
    sim.wr(INSTANCE+28, META)
    sim.wr(META+15, 0x100)
    sim.wr(0x965ed, META)
    selected = invoke(sim, short, 0x1779ed, stop=(0x177d3d,))
    assert selected['stop_address'] == 0x177d3d
    sim, short = context(e2)
    link(sim, short, registry(e2, 0x2397))
    sim.set(0xe, INSTANCE)
    sim.set(0xf, INSTANCE)
    sim.set(0xd, 0x600024)
    sim.wr(INSTANCE+28, META)
    sim.wr(META+15, 0x100)
    sim.wr(0x965ed, META)
    replacement = invoke(sim, short, 0x178636, stop=(0x177d3d,))
    assert replacement['stop_address'] == 0x177d3d
    assert sim.get(4) == INSTANCE
    assert all(pc in replacement['executed_addresses'] for pc in
               (0x178636, 0x17871a, 0x178642, 0x1779ed, 0x177a2a))
    sim, short = context(e2)
    for j, value in enumerate(retained):
        sim.wr(0x9d5db+j, value)
    sim.wr(0x9d5f6, ROOT)
    sim.set(0xd, 0)
    task_copy = invoke(sim, short, 0x178a1c, stop=(0x178a55,))
    assert [sim.rd(ROOT+j) for j in range(27)] == expected
    assert [sim.rd(0x9d5db+j) for j in range(27)] == retained
    return dict(repeated_prefix_reports=reports,
                selector_to_composite_constructor=selected,
                replacement_teardown_to_rebuild_same_descriptor=replacement,
                native_task_arena_copy_prefix=task_copy,
                all_nine_local_begins_and_currents_reset_from_retained_current=True,
                retained_descriptor_arenas_unchanged=True,
                graph_memory_clear_or_individual_free_executed=False,
                limit='Build prefix only; retained descriptor creation and outer task reclamation unexecuted.')


def buffer_member_join(e2, image):
    """Compose original buffer allocation, member selection/carving and init.

    Traversal/slot validation and the member's already-reserved descriptor
    address are supplied entry context. No binding pointer is manually written
    to the child: the native selector and store must establish child[36].
    """
    kit = adapter.kit
    e3 = kit.get_entry_swapped(image, 3)
    e4 = kit.get_entry_swapped(image, 4)
    info = kit.parse_entry3_full(e3)
    words = struct.unpack(f'<{len(e4)//4}I', e4)
    b0 = kit.entry4_blob.blob(words, 0)
    cases = []
    for name in ('HD2_DelayCosmosEchoMono', 'HD2_DelayCosmosEchoStereo'):
        model = kit.find_model(info, name)
        blob = kit.entry4_blob.blob(words, model['blob_index'])
        composite = kit.entry4_blob.parse_composite(b0, kit.entry4_blob.top_type(blob))
        header_offset = b0[0x10]+7*(composite['comp_id']-0x600000)
        header = b0[header_offset:header_offset+7]
        offset = composite['buffers_off']
        records = [b0[offset+4*j:offset+4*(j+1)]
                   for j in range(composite['n_buffers'])]
        for index, member in enumerate(composite['members']):
            primitive = member['type_id']
            if primitive not in (0x2397, 0x2394):
                continue
            record_offset = composite['members_off']+index*20
            record = b0[record_offset:record_offset+20]
            allocation, sim, short = buffers._replay(e2, header, records)
            assert allocation['complete_buffer_prefix']
            # The preceding native prefix reserves all 37-word descriptors
            # at output[3]. Enter the selected member, without graph traversal.
            at, child = 0xbd000, sim.rd(buffers.RESULT+3)+37*index
            for j, value in enumerate(record):
                sim.wr(at+j, value)
            for j in range(37):
                sim.wr(child+j, 0)
            sim.wr(child+36, SENTINEL)
            sim.wr(child-1, SENTINEL)
            sim.wr(child+37, SENTINEL)
            sim.wr(STACK-3, buffers.PARENT)
            sim.wr(STACK+1, buffers.PARENT)
            for register, value in ((0x10, buffers.PARENT+8), (0x11, at),
                                    (0x13, child), (0x15, buffers.RESULT+16),
                                    (13, child), (14, 0), (0x24, 0),
                                    (0x16, STACK), (0x17, STACK)):
                sim.set(register, value)
            # Execute the stock constant and member-tail setup instead of
            # implementing their address arithmetic in Python.
            sim.pc = 0x177f4c
            step(sim, short)
            sim.pc = 0x177f54
            tail = run(sim, short, {0x177f5b})
            assert sim.get(0x14) == sim.get(0x18) == at+20
            sim.pc = 0x177f6e
            selection = run(sim, short, {0x1780b9, 0x178132})
            assert selection['stop_address'] == 0x1780b9
            binding_id = record[19]
            binding = allocation['bindings'][binding_id-1]
            assert sim.rd(child+36) == binding['address']
            assert (0x177f6e, at+19) in selection['reads']
            assert (0x177f73, buffers.RESULT+5) in selection['reads']
            assert (0x1780b7, child+36, binding['address']) in selection['writes']
            dm, pm = sim.rd(child), sim.rd(child+3)
            assert sim.rd(child+1)-dm == record[13]
            assert sim.rd(child+4)-pm == record[14]
            init = adapter.ldr_word(e2, registry(e2, primitive)['address']+1)
            sim.set(0x16, FRAME)
            sim.set(0x17, STACK)
            initialization = invoke(sim, short, init, argument=child)
            assert initialization['balanced_c_frame']
            assert any(address == child+36 for _, address in initialization['reads'])
            if primitive == 0x2394:
                assert [sim.rd(dm+j) for j in range(3)] == [
                    binding['cursor'], binding['ring_base'], binding['ring_words']]
                assert sim.rd(binding['cursor']) == binding['ring_base']
            else:
                assert [sim.rd(dm+j) for j in range(2)] == [
                    binding['ring_base'], binding['ring_words']]
                assert sim.rd(pm) == binding['cursor']
            assert sim.rd(child-1) == sim.rd(child+37) == SENTINEL
            cases.append(dict(model=name, member_path=index+1, primitive=primitive,
                              member_record_blob0_word=record_offset,
                              member_record_sha256=hashlib.sha256(
                                  struct.pack('<20I', *record)).hexdigest(),
                              declared_buffer_id=binding_id, selected_binding=binding,
                              native_member_tail_setup=tail,
                              native_selection_and_member_allocation=selection,
                              native_init=initialization,
                              child_word36_written_only_by_native_selector=True,
                              initialized_state_matches_created_buffer=True))
    assert len(cases) == 12
    return dict(entry4_swapped_sha256=hashlib.sha256(e4).hexdigest(), cases=cases,
                complete_graph_traversal_executed=False,
                supplied_context='Selected stock member, native-reserved descriptor address, parent local arenas and C frame.',
                negative_immediate16_extension_assumed='sign-extend')


def inspect(path):
    if hashlib.md5(path.read_bytes()).hexdigest() != STOCK_MD5:
        raise ValueError('expected unchanged HX Stomp 3.80.0 stock HXF')
    image, _ = adapter.kit.load_l6ia_from_any(str(path))
    entry = adapter.kit.l6ia.parse(image)[2]
    e2 = image[entry['payload_off']:entry['payload_off']+entry['payload_len']]
    return dict(entry2_sha256=hashlib.sha256(e2).hexdigest(),
                synthetic_context=True,
                init16_parcel_order_assumed='high-first',
                external_visa_parcel_order_assumed='low-first',
                negative_immediate16_extension_assumed='sign-extend',
                primitive_cases=primitive_cases(e2), graph_cases=graph_cases(e2),
                arena_rebuild=arena_rebuild_case(e2),
                buffer_member_binding_join=buffer_member_join(e2, image),
                limits=['No hardware execution or complete Cosmos graph audio rendering.',
                        'Constructor linkage slice supplied registry lookup and carved descriptor.',
                        'Graph traversal uses a synthetic two-child composite.',
                        'Teardown flag8 stops before RTOS/framework operation 0x175ab9.',
                        'Parent slot arenas, graph removal and replacement rollback not executed.',
                        'Root pid0 and audible bypass/trails/spillover policy unproved.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware', type=Path)
    print(json.dumps(inspect(parser.parse_args().firmware), indent=2))
