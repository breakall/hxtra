#!/usr/bin/env python3
"""Inspect source-derived stereo host facts and decode the native-context probe.

No native channel layout is selected here. A 2-in/2-out graph does not establish
whether I1/I2 point to interleaved samples, planar samples, or pointer lists.
CLI: microlooper_adapter.py stock.hxf. No firmware is modified.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import kit_patch_amp as kit
import sasm
import ssim

ASM = HERE.parents[1] / 'src/sharc/microlooper_adapter.asm'
HOST = 'L6SPB_AcousGtrSimStereo'
MAGIC = 0x6d6c6131
SNAPSHOT_OFFSET = 160
SOURCE_SEQUENCE_OFFSET = 180
STATE_WORDS = 200
INTERNAL_DM_RANGES = ((0x92000, 0x9e000), (0xb2000, 0xbe000),
                      (0xc0000, 0xc8000), (0xe0000, 0xe8000))
FIELDS = ('magic', 'calls', 'i0', 'i1', 'i2', 'i3', 'i8', 'b1', 'l1',
          'b2', 'l2', 'mode1', 'instance_candidate', 'sdram_begin', 'sdram_end',
          'plausible_extent')


def assemble(base):
    if base < 0 or base % 2:
        raise ValueError('PM base must be nonnegative and even')
    return sasm.assemble(ASM.read_text().replace('KIT_PM_BASE', hex(base)), ASM.name)


def assemble_diagnostic(base, sidecar):
    """Absolute-DM AcousticSim diagnostic; no change to native I0/allocation.

    The builder must reserve200 words at sidecar and place every returned PM
    instruction. This reserves no memory and patches no image by itself.
    """
    if base < 0 or base % 2:
        raise ValueError('PM base must be nonnegative and even')
    if sidecar % 2 or not any(low <= sidecar and sidecar + STATE_WORDS <= high
                              for low, high in INTERNAL_DM_RANGES):
        raise ValueError('sidecar must be even and fit in internal normal-word memory')
    source = ASM.read_text().replace('KIT_PM_BASE', hex(base))
    source = re.sub(r'\bDM\(([^,\n]+), I0\)',
                    lambda match: f'DM({sidecar:#x} + ({match[1]}))', source)
    source = source.replace('MICROLOOPER_ADAPTER_CONTEXT', 'MICROLOOPER_ADAPTER_GLOBAL_CONTEXT')
    source = source.replace('MICROLOOPER_ADAPTER_ACOUSTIC_DIAGNOSTIC',
                            'MICROLOOPER_ADAPTER_GLOBAL_ACOUSTIC_DIAGNOSTIC')
    return sasm.assemble(source, 'microlooper_adapter_global.asm')


def decode_snapshot(words):
    if len(words) != len(FIELDS) or words[0] != MAGIC:
        raise ValueError('not a micro-looper native-context snapshot')
    out = dict(zip(FIELDS, words))
    out['native_stereo_abi_verified'] = False
    return out


def ldr_blocks(e2):
    """Yield validated raw boot records, without inferring a short-word lane order."""
    if len(e2) % 4 or len(e2) < 384 * 4:
        raise ValueError('truncated or unaligned LDR')
    words = struct.unpack('<%dI' % (len(e2) // 4), e2)
    sizes = {1: lambda n: 0, 2: lambda n: 0, 7: lambda n: 0, 8: lambda n: 0,
             5: lambda n: ((n + 1) & ~1) * 3 // 2, 4: lambda n: n,
             3: lambda n: (n + 1) // 2, 6: lambda n: n * 2,
             10: lambda n: n, 9: lambda n: n,
             **{tag: (lambda n: 0) for tag in (1, 2, 7, 8, 11, 12)}}
    i = 384
    while i + 3 <= len(words):
        tag, count, base = words[i:i + 3]
        if tag == 0:
            return
        if tag not in sizes:
            raise ValueError(f'unsupported LDR tag {tag}')
        size = sizes[tag](count)
        if i + 3 + size > len(words):
            raise ValueError('truncated LDR block')
        yield tag, count, base, words[i + 3:i + 3 + size]
        i += 3 + size
    raise ValueError('LDR has no FINAL_INIT')


def ldr_word(e2, address):
    """Read a normal-word INIT32 location; later boot blocks override earlier ones."""
    found = None
    for tag, count, base, payload in ldr_blocks(e2):
        if tag == 4 and base <= address < base + count:
            found = payload[address - base]
        elif tag == 1 and base <= address < base + count:
            found = 0
    return found


def trace_process_bridge(e2, process, *, input_address=0xb8000,
                         output_address=0xb8100, instance_address=0xb6000,
                         limit=256, diagnostic_base=None, diagnostic_sidecar=None,
                         include_context=False):
    """Replay only the encoded ISA bridge with explicit synthetic context.

    Stops before a short-word/VISA callee. This demonstrates register dataflow,
    not a valid native invocation, VISA execution, or an audio memory layout.
    The caller owns the returned report; no firmware bytes are included.
    """
    sim = ssim.Sim()
    short_blocks = []
    for tag, count, base, payload in ldr_blocks(e2):
        if tag == 5:
            raw = struct.pack('<%dI' % len(payload), *payload)
            for j in range(count):
                sim.pm[base + j] = int.from_bytes(raw[j * 6:j * 6 + 6], 'little')
        elif tag == 4:
            sim.dm.update((base + j, value) for j, value in enumerate(payload))
        elif tag == 3:
            short_blocks.append((base, count))
    call_record = 0xb4000
    for code, value in ((0x10, 0xb3000), (0x11, input_address),
                        (0x12, output_address), (0x13, call_record),
                        (0x18, 0xe1000), (0x21, 1), (0x29, 1)):
        sim.set(code, value)
    sim.wr(call_record + 2, instance_address)
    sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x40000
    for code, value in ((ssim.U_ASTATX, 0x40004), (ssim.U_ASTATY, 0x40008),
                        (0x78, 0x81234567), (0x79, 0x87654321)):
        sim.set(code, value)
    entry = process
    if diagnostic_base is not None:
        if diagnostic_sidecar is None:
            sections, symbols = assemble(diagnostic_base)
            symbol = 'MICROLOOPER_ADAPTER_ACOUSTIC_DIAGNOSTIC'
        else:
            sections, symbols = assemble_diagnostic(diagnostic_base, diagnostic_sidecar)
            symbol = 'MICROLOOPER_ADAPTER_GLOBAL_ACOUSTIC_DIAGNOSTIC'
        sim.load(sections)
        entry = symbols[symbol]
    reads, pcs, jumps = [], [], []
    native_context = None
    def context():
        return ([sim.get(code) for code in range(0x60)] +
                [sim.get(code) for code in (ssim.U_MODE1, ssim.U_ASTATX,
                                            ssim.U_ASTATY, 0x78, 0x79)])
    read = sim.rd
    def record_read(address):
        reads.append(address)
        return read(address)
    sim.rd = record_read
    sim.pc = entry
    for _ in range(limit):
        if sim.pc == process and native_context is None:
            native_context = context()
        if sim.pc not in sim.pm:
            containing = next(((base, count) for base, count in short_blocks
                               if base <= sim.pc < base + count), None)
            if containing is None:
                raise ValueError(f'ISA bridge reached absent code at {sim.pc:#x}')
            report = {'synthetic_context': True, 'isa_steps': len(pcs),
                    'visa_entry': sim.pc, 'visa_boot_block': list(containing),
                    'cjump_addresses': jumps, 'read_addresses': reads,
                    'c_argument_registers': {'r4': sim.get(4), 'r8': sim.get(8),
                                             'r12': sim.get(12)},
                    'native_stereo_abi_verified': False}
            if include_context:
                report.update(handoff_context=context(), native_entry_context=native_context,
                              pc_stack=list(sim.pcstk), loop_stack=list(sim.loops))
            return report
        pcs.append(sim.pc)
        if sim.pm[sim.pc] >> 40 == 0x18:
            jumps.append(sim.pc)
        sim.step()  # Unsupported instructions fail visibly; none are bypassed.
    raise ValueError('ISA bridge exceeded instruction bound')


def inspect(image_path):
    path = Path(image_path)
    data, _ = kit.load_l6ia_from_any(str(path))
    e3 = kit.parse_entry3_full(kit.get_entry_swapped(data, 3))
    model = kit.find_model(e3, HOST)
    e4 = kit.get_entry_swapped(data, 4)
    w4 = struct.unpack('<%dI' % (len(e4) // 4), e4)
    b0 = kit.entry4_blob.blob(w4, 0)
    comp_id = kit.entry4_blob.top_type(kit.entry4_blob.blob(w4, model['blob_index']))
    comp = kit.entry4_blob.parse_composite(b0, comp_id)
    if comp is None:
        raise ValueError('stereo host composite is missing')
    member = comp['members'][1]
    if (member['n_in'], member['n_out']) != (2, 2):
        raise ValueError('host no longer has two input and output ports')
    entry = kit.l6ia.parse(data)[2]
    raw_e2 = data[entry['payload_off']:entry['payload_off'] + entry['payload_len']]
    registry = next((addr for addr in range(0x200000, 0x2008d0, 8)
                     if ldr_word(raw_e2, addr) == member['type_id']), None)
    if registry is None:
        raise ValueError('host primitive is missing from INIT32 registry')
    process = ldr_word(raw_e2, registry + 5)
    # The helper retains explicit, unresolved parcel-order assumptions. This
    # report is conditional decoding evidence, never registration enablement.
    import microlooper_visa
    geometry = microlooper_visa.inspect_buffer_geometry(raw_e2, parcel_order='high-first')
    initializer = microlooper_visa.inspect_initializer_fields(
        raw_e2, parcel_order='high-first', external_parcel_order='low-first', init_r12=0)
    float_use = microlooper_visa.inspect_input_word_float_use(
        raw_e2, parcel_order='high-first', input_words=[0x3e800000] * 32,
        coefficient_word=0x3f400000)
    return {'input_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'host': HOST, 'composite': comp_id, 'primitive': member['type_id'], 'registry_address': registry,
            'process_address': process,
            'process_bridge': trace_process_bridge(raw_e2, process),
            'conditional_buffer_geometry': geometry,
            'conditional_initializer_prefix': initializer,
            'conditional_input_float_use': float_use,
            'root_ports': [comp['n_in'], comp['n_out']],
            'primitive_ports': [member['n_in'], member['n_out']],
            'input_buffers': list(b0[member['in_off']:member['in_off'] + member['n_in']]),
            'output_buffers': list(b0[member['out_off']:member['out_off'] + member['n_out']]),
            'native_stereo_abi_verified': False,
            'channel_memory_layout': 'unknown: graph ports are not runtime pointers',
            'instance_descriptor_evidence': 'NAM: DM(2,I3), SDRAM begin/end at words6/7',
            'context_probe_words': STATE_WORDS}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('image')
    print(json.dumps(inspect(p.parse_args().image), indent=2))


if __name__ == '__main__':
    main()
