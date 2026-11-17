#!/usr/bin/env python3
"""Read-only Cosmos Echo declarations and bounded stock-code replay.

No device access or firmware patching. Parent arenas, graph buffer bindings,
audio bases and C caller context are supplied fixtures, not native boot proof.
Uses the existing conditional high-first INIT16 / low-first external VISA
interpretation. Output is derived facts, never firmware bytes or instructions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import microlooper_adapter as adapter
import microlooper_allocation as allocation
import microlooper_init as caller
import microlooper_visa as visa
import ssim
import cosmos_echo_allocation as buffers
import cosmos_echo_lifecycle as lifecycle

STOCK_MD5 = 'a2cd8f4ae56f49415380270ebc484bf1'
NAMES = ('HD2_DelayCosmosEchoMono', 'HD2_DelayCosmosEchoStereo')
STATE, INSTANCE, PM = 0xb3000, 0xb6000, 0xe1000
STACK, FRAME = 0xc6d98, 0xc6e98
BINDING, CURSOR, INPUT = 0xb8000, 0xb9000, 0xba000


def registry(e2, primitive):
    for offset in range(0, 2256, 8):
        address = 0x200000 + offset
        if adapter.ldr_word(e2, address) == primitive:
            row = [adapter.ldr_word(e2, address + j) for j in range(8)]
            return dict(address=address, init=row[1], control=row[4],
                        process=row[5], dm_words=row[6], pm_words=row[7])
    raise ValueError(f'primitive {primitive:#x} is absent')


def parameter_schema(e3, model, blob):
    defaults = {}
    for j in range(blob[11]):
        path, pid, value, kind = blob[blob[10]+j*4:blob[10]+(j+1)*4]
        if blob[path:path+2] == [1, 0] and kind == 1:
            assert pid not in defaults
            defaults[pid] = blob[value+1]
    pmap = blob[blob[6]:blob[6]+blob[7]]
    slots = [pmap[pmap[6]+4*j+2] for j in range(pmap[21])]
    assert set(slots) == set(defaults) == {p['slot'] for p in model['params']}
    schema = []
    for parameter in model['params']:
        raw = struct.unpack_from('<3I', e3, parameter['off']+20)
        assert raw[2] == defaults[parameter['slot']]
        values = [ssim.b2f(value) if parameter['type'] == 3 else value for value in raw]
        schema.append(dict(name=parameter['name'], slot=parameter['slot'],
                           type=parameter['type'], minimum=values[0], maximum=values[1],
                           default=values[2]))
    return dict(parameters=schema, root_defaults_match=True,
                parameter_map_slot_set_matches=True, control_nodes=pmap[18], control_edges=pmap[20])


def native_binding(e2, *, init, dm_words, pm_words, ring, length):
    sim, short = visa.load(e2, parcel_order='high-first', external_parcel_order='low-first')
    for code, value in ((0x25, 0), (0x26, 1), (0x27, 0xffffffff),
                        (0x2d, 0), (0x2e, 1), (0x2f, 0xffffffff),
                        (0x37, 0), (0x16, FRAME), (0x17, STACK), (4, INSTANCE)):
        sim.set(code, value)
    sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x10000
    sim.strict_cbufen = True
    for base, count in ((STATE, dm_words), (PM, pm_words)):
        sim.wr(base-1, 0xdeadbeef)
        for j in range(count):
            sim.wr(base+j, 0xa5a5a5a5)
        sim.wr(base+count, 0xdeadbeef)
    sim.wr(INSTANCE, STATE)
    sim.wr(INSTANCE+3, PM)
    sim.wr(INSTANCE+36, BINDING)
    for j, value in enumerate((CURSOR, 0, 0, 0, ring, length)):
        sim.wr(BINDING+j, value)
    reads = []
    original_read = sim.rd

    def read(address):
        reads.append((sim.pc, address))
        return original_read(address)

    sim.rd = read
    caller.invoke_from_stock_c_caller(sim, short, init, limit=512)
    sim.rd = original_read
    assert sim.pc == caller.RETURN_SITE
    assert all(sim.rd(base-1) == sim.rd(base+count) == 0xdeadbeef
               for base, count in ((STATE, dm_words), (PM, pm_words)))
    assert any(address == INSTANCE+36 for _, address in reads)
    assert all(any(address == BINDING+j for _, address in reads) for j in (0, 4, 5))
    return sim


def replay_buffer_bindings(e2, writer, reader):
    results = []
    for ring, length in ((0x400000, 0x5dc00), (0x500000, 0x2f000)):
        sim = native_binding(e2, init=writer['init'], dm_words=3, pm_words=0,
                             ring=ring, length=length)
        assert [sim.rd(STATE+j) for j in range(3)] == [CURSOR, ring, length]
        assert sim.rd(CURSOR) == ring
        sim.wr(ring-1, 0xdeadbeef)
        sim.wr(ring+length, 0xdeadbeef)
        samples = [ssim.f2b((j+1)/32) for j in range(16)]
        for j, value in enumerate(samples):
            sim.wr(INPUT+j, value)
        for position, expected_next in ((ring, ring+16),
                                         (ring+length-16, ring),
                                         (ring, ring+16)):
            sim.wr(CURSOR, position)
            for code, value in ((0x10, STATE), (0x11, INPUT), (0x41, INPUT)):
                sim.set(code, value)
            sim.call(writer['process'], limit=1024)
            begin = position
            assert [sim.rd(begin+j) for j in range(16)] == samples
            assert sim.rd(CURSOR) == expected_next
            assert sim.rd(ring-1) == sim.rd(ring+length) == 0xdeadbeef
        sim = native_binding(e2, init=reader['init'], dm_words=5, pm_words=6,
                             ring=ring, length=length)
        assert sim.rd(PM) == CURSOR
        assert [sim.rd(STATE+j) for j in range(2)] == [ring, length]
        results.append(dict(ring_words=length, writer_initial_binding_verified=True,
                            reader_initial_binding_verified=True,
                            writer_sample_copy_verified=True,
                            writer_end_and_wrap_verified=True))
    return dict(synthetic_context=True, native_graph_buffer_allocator_executed=False,
                physical_audio_layout_verified=False, cases=results)


def inspect(path):
    kit = adapter.kit
    if hashlib.md5(path.read_bytes()).hexdigest() != STOCK_MD5:
        raise ValueError('expected the unchanged HX Stomp 3.80.0 stock HXF')
    image, _ = kit.load_l6ia_from_any(str(path))
    entry = kit.l6ia.parse(image)[2]
    e2 = image[entry['payload_off']:entry['payload_off']+entry['payload_len']]
    e3 = kit.get_entry_swapped(image, 3)
    info = kit.parse_entry3_full(e3)
    e4 = kit.get_entry_swapped(image, 4)
    words = struct.unpack(f'<{len(e4)//4}I', e4)
    b0 = kit.entry4_blob.blob(words, 0)
    variants = []
    primitives = {}
    for name in NAMES:
        model = kit.find_model(info, name)
        blob = kit.entry4_blob.blob(words, model['blob_index'])
        nodes = list(kit.entry4_blob.nodes(blob))
        assert all(node[1] == 0xffffffff for node in nodes[1:])
        composite = kit.entry4_blob.parse_composite(b0, kit.entry4_blob.top_type(blob))
        sizes = [0, 0, 0]
        declarations_match = True
        for j, member in enumerate(composite['members']):
            if member['flags'] != 0:
                continue
            primitive = member['type_id']
            record = b0[composite['members_off']+j*20:composite['members_off']+(j+1)*20]
            row = primitives.setdefault(primitive, registry(e2, primitive))
            declarations_match &= record[13:15] == [row['dm_words'], row['pm_words']]
            sizes = [a+b for a, b in zip(sizes, record[13:16])]
        # The parser's header n_in/n_out labels do not establish external ports.
        ports = {key: [member['n_out' if flag == 4 else 'n_in']
                       for member in composite['members'] if member['flags'] == flag]
                 for key, flag in (('input_widths', 4), ('output_widths', 8))}
        offset = composite['buffers_off']
        records = [b0[offset+4*j:offset+4*(j+1)] for j in range(composite['n_buffers'])]
        buffer_sizes = [record[3] for record in records]
        header_offset = b0[0x10]+7*(composite['comp_id']-0x600000)
        buffer_allocation = buffers.inspect(e2, b0[header_offset:header_offset+7], records)
        variants.append(dict(name=name, model_index=model['idx'], blob=model['blob_index'],
                             composite=composite['comp_id'], ports=ports,
                             members=composite['n_members'], parameter_count=len(model['params']),
                             visible_parameter_count=int(model['meta']['displayParamCount']),
                             primitive_dm_pm_match_registry=declarations_match,
                             member_memory_sum=dict(zip(('dm_words', 'pm_words', 'sdram_words'), sizes)),
                             graph_buffer_lengths=buffer_sizes,
                             graph_buffer_lengths_semantics_executed=True,
                             native_buffer_allocation=buffer_allocation,
                             schema=parameter_schema(e3, model, blob)))
    arena_results = []
    for primitive, row in primitives.items():
        result = allocation.inspect_member_arenas(e2, dm_words=row['dm_words'],
                                                   pm_words=row['pm_words'], sdram_words=0)
        assert result['complete_prefix'] and result['memory_guards_intact']
        arena_results.append(dict(primitive=primitive, dm_words=row['dm_words'],
                                  pm_words=row['pm_words'], native_carving_verified=True,
                                  synthetic_parent_arenas=True))
    return dict(stock_md5=STOCK_MD5, entry2_sha256=hashlib.sha256(e2).hexdigest(),
                firmware_modified=False, hardware_accessed=False, variants=variants,
                primitive_registry=primitives, native_member_allocation=arena_results,
                native_buffer_binding=replay_buffer_bindings(e2, primitives[0x2394], primitives[0x2397]),
                native_lifecycle=lifecycle.inspect(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stock', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.stock), indent=2))


if __name__ == '__main__':
    main()
