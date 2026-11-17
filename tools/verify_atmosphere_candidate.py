#!/usr/bin/env python3
"""Verify a built Atmosphere candidate before a RAM-only hardware comparison.

IMAGE is HXF or L6IA. --report is its linker report, not an allocation proof by
itself. Current NAM2/GR/click and NAM3/click reservations are independently
derived from the pinned generators and native heap setup. ISA48 sections may
span the existing Block3 gap and reserved DDR2. Other layouts fail closed.
The default additionally executes final image bytes against the C++ oracle.
This establishes bounded offline checks, never hardware timing or audio quality.
"""
import argparse
from bisect import bisect_left
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'sharc'))
import effect_model
import hxf
import hxf_ram
import kit_patch_amp as kit
import l6ia
import microlooper_native
from microlooper_definition import EFFECT, MODELS
from patch_microlooper import REGISTRY_ADDRESSES
import microlooper as layout
import microlooper_adapter as loader
import microlooper_allocation as allocation
import microlooper_bridge as bridge
import microlooper_init as callbacks
import microlooper_placement as placement
import microlooper_visa as visa
import patch_click
import patch_comp
import sasm
import ssim

ROOT = HERE.parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_image(path):
    raw = Path(path).read_bytes()
    if raw[:4] == b'FORM':
        require(struct.unpack_from('>I', raw, 4)[0] + 8 == len(raw), 'HXF FORM size mismatch')
        chunks = hxf._chunks(raw)
        require(all(pos+8+size <= len(raw) for _, pos, size, _ in chunks)
                and chunks[-1][1]+8+chunks[-1][2]+(chunks[-1][2] & 1) == len(raw),
                'HXF chunk extent mismatch')
        heads = [b for c, _, _, b in chunks if c == b'HEAD']
        payloads = [b for c, _, _, b in chunks if c == b'data']
        require(len(heads) == len(payloads) == 1, 'HXF needs one HEAD and data chunk')
        head, data = heads[0], zlib.decompress(payloads[0])
        require(len(head) >= 36 and struct.unpack_from('>H', head, 10)[0] == 6,
                'candidate must target HX Stomp')
        require(struct.unpack_from('>I', head, 16)[0] == len(data), 'HXF payload size mismatch')
        require(head[20:36] == hashlib.md5(data).digest(), 'HXF payload MD5 mismatch')
        entries = l6ia.parse(data)
        end = entries[-1]['payload_off']+entries[-1]['payload_len']
        dinf = [struct.unpack('>4I', b) for c, _, _, b in chunks if c == b'dinf']
        require(dinf == [(0, 0x10000, 0, end), (5, 0x10000, end, len(data)-end)],
                'HXF region directory differs from archive/trailer extents')
        return data
    require(raw[:4] == b'L6IA', 'candidate is neither HXF nor L6IA')
    return raw


def verify_integrity(data):
    """Use the archive's parser/checksums, checking bounds before slicing."""
    entries = l6ia.parse(data)
    require(len(entries) == len(hxf_ram.PART_START), 'expected all 15 Stomp entries')
    sizes = []
    for n, e in enumerate(entries):
        require(e['index'] == n, f'entry {n}: index mismatch')
        end = e['payload_off'] + e['payload_len']
        require(e['payload_len'] >= 0 and end <= len(data), f'entry {n}: truncated payload')
        body = data[e['off'] + l6ia.EH:end]
        require(l6ia.fletcher_words(body) == (e['h1'], e['h2']), f'entry {n}: Fletcher mismatch')
        payload = l6ia.swap32(data[e['payload_off']:end])
        require(zlib.crc32(payload) & 0xffffffff == e['crc32'], f'entry {n}: CRC mismatch')
        require(l6ia.fix_internal_crcs(payload) == payload, f'entry {n}: internal integrity mismatch')
        if len(payload) >= 24 and struct.unpack_from('<I', payload)[0] == 0x28267e5e:
            require(struct.unpack_from('<I', payload, 20)[0]*4 == len(payload),
                    f'entry {n}: blob directory size mismatch')
        if hxf_ram.PART_END[n] is not None:
            room = (hxf_ram.PART_END[n] - hxf_ram.PAYLOAD[n]) * hxf_ram.SECTOR
            require(len(payload) <= room, f'entry {n}: partition overflow')
        sizes.append(len(payload))
    hxf_ram.app_segments(kit.get_entry_swapped(data, 0))
    return sizes


def executable_sections(report):
    """Normalize the existing external report or an explicit split-section list."""
    if 'executable_sections' in report:
        sections = report['executable_sections']
    else:
        sections = [report['code_storage']]
    require(isinstance(sections, list) and sections, 'missing executable sections')
    normalized = []
    for item in sections:
        kind = item.get('kind', report.get('code_storage', {}).get('kind'))
        pm, count = item.get('code_pm'), item.get('instructions')
        require(type(pm) is int and type(count) is int and pm >= 0 and pm % 2 == 0
                and count > 0 and count % 2 == 0, 'ISA sections need even addresses/counts')
        require(kind in ('external_isa48', 'internal_isa48'), 'unsupported executable storage kind')
        normalized.append(dict(item, kind=kind, code_pm=pm, instructions=count))
    if 'executable_sections' in report and 'code_storage' in report:
        external = next((item for item in normalized if item['kind'] == 'external_isa48'), None)
        require(external is not None and all(report['code_storage'].get(key) == external.get(key)
                    for key in ('kind', 'code_pm', 'instructions', 'data_begin', 'data_end')),
                'legacy code storage contradicts executable sections')
    return normalized


def record_physical_span(record):
    """Supported LDR writes in physical16 units, including internal aliases."""
    tag, count, base, _ = record
    require(tag in (1, 2, 3, 4, 5, 10), 'unsupported loader write form for physical replay')
    if base >= 0x200000:
        return placement.physical_span(record)
    if tag in (1, 4):
        return 2*base, 2*(base+count)
    if tag in (2, 5) and 0x80000 <= base < 0x100000:
        bank = base & ~0x1ffff
        limit = 0x15556 if bank < 0xc0000 else 0x5556
        require(base+count <= bank+limit, 'internal ISA loader record exceeds its bank')
        begin = 2*bank+3*(base-bank)
        return begin, begin+3*count
    if tag == 3:
        return base, base+count
    require(tag not in (2, 5, 10), 'unsupported instruction/packed-data boot address')
    return None


def replay_physical(records, addresses):
    """Replay final halfwords only where a pinned owner needs verification."""
    wanted, final = sorted(addresses), {}
    for record in records:
        tag, _, _, payload = record
        span = record_physical_span(record)
        if not span:
            continue
        start, end = bisect_left(wanted, span[0]), bisect_left(wanted, span[1])
        for address in wanted[start:end]:
            offset = address-span[0]
            if tag in (1, 2):
                value = 0
            else:
                half = 1-offset % 2 if tag == 3 else offset % 2
                value = payload[offset//2] >> (16*half) & 0xffff
            final[address] = value
    return final


def require_pinned_neighbors(records, baseline):
    """NAM and existing native neighbors must survive every aliased boot write."""
    with layout.nam_multi.flags(['--mid-sweep']):
        source, _ = layout.nam_multi.build(baseline.slots)
    sections, _ = sasm.assemble(source, 'candidate_nam_baseline.asm')
    normal = {}
    for tag, count, base, payload in records:
        if tag in (1, 4):
            normal.update((base+i, payload[i] if tag == 4 else 0) for i in range(count))
    def registry(primitive):
        rows = [a for a in range(0x200000, 0x2008d0, 8) if normal.get(a) == primitive]
        require(len(rows) == 1, 'native neighbor registry is missing or ambiguous')
        return [normal.get(rows[0]+i) for i in range(8)]
    gr_rows = [(primitive, registry(primitive), original) for primitive, original in patch_comp.WRAPS]
    if any(row[5] != original for _, row, original in gr_rows):
        dm, pm = patch_comp.dsp_place(baseline)
        gr, symbols = sasm.assemble(patch_comp.dsp_asm(dm, pm), 'candidate_gr_baseline.asm')
        require(all(row[4] == symbols[f'CTRL_{primitive:X}'] and row[5] == symbols[f'ENTRY_{primitive:X}']
                    for primitive, row, _ in gr_rows), 'native GR neighbor callbacks differ')
        sections += gr
    click_row = registry(patch_click.PRIM[0])
    click_base = patch_click.pm_base(patch_click.kernel_size(), baseline)
    if click_row[5] == click_base:
        click, _ = sasm.assemble(Path(patch_click.ASM).read_text().replace('KIT_PM_BASE', hex(click_base)),
                                 'candidate_click_baseline.asm')
        sections += click
    else:
        require(click_row == [0x0128, 0x60aceb, 0, 0x60ad36, 0x60ac8c, 0x8ce74, 9, 4],
                'native Metronome neighbor registry differs')
    expected = {}
    for section in sections:
        if section.kind == 'pm':
            span = record_physical_span((5, len(section.words), section.addr, []))
            width = 3
        else:
            span = (2*section.addr, 2*(section.addr+len(section.words)))
            width = 2
        require(span is not None, 'unsupported pinned NAM/native address')
        expected.update((span[0]+width*i+j, word >> (16*j) & 0xffff)
                        for i, word in enumerate(section.words) for j in range(width))
    # These guarded native setup literals own both sides of the external gap.
    for tag, count, base, payload in records:
        if tag == 3:
            for pc in (0x17884b, 0x178855, 0x17885e, 0x1788b6, 0x1788c0, 0x1788c9):
                for address in range(max(pc, base), min(pc+3, base+count)):
                    i = address-base
                    expected[address] = payload[i//2] >> (16*(1-i % 2)) & 0xffff
    actual = replay_physical(records, expected)
    require(actual == expected, 'aliased boot writes change pinned NAM/native neighbor storage')


def require_last_writer_space(records, span, kind):
    """Reject late alias writes the ISA/DM replay would otherwise overlook.

    A full initialized record must establish each declared section. Earlier
    clear/alias records can legitimately precede it. Same-space later overlays
    are replayed by the corresponding loader; cross-space later writers are
    rejected because this gate does not pretend to emulate their parcel order.
    """
    own_tag = 4 if kind == 'external_isa48' else 5
    full = []
    spans = []
    for index, record in enumerate(records):
        tag, n, base, _ = record
        actual = record_physical_span(record)
        if actual and actual[0] < span[1] and span[0] < actual[1]:
            spans.append((index, tag))
            if tag == own_tag and actual[0] <= span[0] and span[1] <= actual[1]:
                full.append(index)
    require(full, 'executable section lacks a complete initialized boot record')
    allowed = (1, 4) if own_tag == 4 else (2, 5)
    require(all(index <= max(full) or tag in allowed for index, tag in spans),
            'late boot write overlaps executable storage through another address space')


def model_reports(report):
    """Bind both native models to their fixed declarations, never report policy."""
    rows = report.get('models')
    require(isinstance(rows, list) and len(rows) == len(MODELS),
            'report must contain both Atmosphere models')
    names = [row.get('effect', {}).get('model_name') for row in rows]
    require(len(set(names)) == len(MODELS) and set(names) == {m.name for m in MODELS},
            'report Atmosphere model identities differ')
    bound = []
    for effect in MODELS:
        row = rows[names.index(effect.name)]
        declared = dict(preset_id=effect.preset_id, primitive=effect.primitive,
                        registry_address=REGISTRY_ADDRESSES[effect.name],
                        private_dm_words=effect.instance.dm_words,
                        private_pm_words=effect.instance.pm_words,
                        private_sdram_words=effect.instance.sdram_words)
        require(all(type(row.get(key)) is int and row[key] == value
                    for key, value in declared.items()),
                'report model identity/private-allocation binding differs')
        require(type(row.get('effect', {}).get('width')) is int
                and json.loads(json.dumps(row.get('effect'))) == json.loads(json.dumps(effect.describe())),
                'report model declaration/width differs')
        bound.append((effect, row))
    stereo = bound[0][1]
    require(all(report.get(key) == stereo.get(key) for key in
                ('init_entry', 'control_entry', 'process_entry', 'declared_dsp_cost')),
            'top-level stereo callback/charge contradicts model report primitive registry')
    return bound


def verify_layout(e2, report):
    records = list(loader.ldr_blocks(e2))
    baseline = layout.require_baseline(records)
    require(report.get('nam_slots') == baseline.slots, 'report NAM profile differs from image')
    placement.require_native_reservation(records)
    require_pinned_neighbors(records, baseline)
    # Reserve both neighbors even in a build omitting their feature, so this
    # gate never invents new ownership from an apparent uninitialized gap.
    gap = layout.profile(baseline.slots, metronome=True, gr=baseline.slots == 2)
    sections = executable_sections(report)
    physical = []
    decoded = {}
    normal = {}
    for tag, count, base, payload in records:
        if tag in (1, 4):
            normal.update((base+i, payload[i] if tag == 4 else 0) for i in range(count))
    native_pm = layout.pm_words(records)
    for section in sections:
        pm, count = section['code_pm'], section['instructions']
        if section['kind'] == 'external_isa48':
            begin, end = section.get('data_begin'), section.get('data_end')
            require(type(begin) is int and type(end) is int and pm*3 == begin*2
                    and (end-begin)*2 == count*3, 'external ISA/data alias mismatch')
            require(baseline.ddr2_to <= begin < end <= layout.nam_multi.DDR2_END,
                    'external code is outside the proven reservation')
            require(all(not (lo < end and begin < hi) for lo, hi in baseline.claims()),
                    'external code overlaps NAM runtime storage')
            span = (2*begin, 2*end)
            raw = b''.join(normal[address].to_bytes(4, 'little') for address in range(begin, end))
            decoded.update((pm+i, int.from_bytes(raw[6*i:6*i+6], 'little')) for i in range(count))
        else:
            begin, end = layout.normal_word(pm), layout.normal_word(pm+count)
            require(gap.block3_begin <= begin < end <= layout.normal_word(gap.block3_end_pm),
                    'internal code is outside the proven NAM/GR/click gap')
            span = (2*begin, 2*end)
            require(all(address in native_pm for address in range(pm, pm+count)),
                    'internal ISA section is absent from the image')
            decoded.update((address, native_pm[address]) for address in range(pm, pm+count))
        require(all(not (lo < span[1] and span[0] < hi) for lo, hi in physical),
                'executable sections overlap through physical aliases')
        require_last_writer_space(records, span, section['kind'])
        physical.append(span)
    # The explicit sections must contain every published callback, and final
    # registry words rather than report values select the process/callbacks.
    for effect, row in model_reports(report):
        registry = [loader.ldr_word(e2, row['registry_address']+i) for i in range(8)]
        expected = [effect.primitive, row.get('init_entry'), 0, 0,
                    row.get('control_entry'), row.get('process_entry'),
                    effect.instance.dm_words, effect.instance.pm_words]
        require(registry == expected, 'Atmosphere primitive registry/callback allocation differs')
        require(all(registry[n] in decoded for n in (1, 4, 5)), 'callback is outside verified ISA sections')
    rows = [row for _, row in model_reports(report)]
    require(len({r['process_entry'] for r in rows}) == len({r['control_entry'] for r in rows}) == 1
            and len({r['init_entry'] for r in rows}) == len(MODELS),
            'Atmosphere family must share process/control and have distinct channel initializers')
    return baseline, sections, decoded


def verify_callbacks(e2, decoded, report, effect=EFFECT):
    sim, short = visa.load(e2, parcel_order='high-first', external_parcel_order='low-first')
    sim.pm.update(decoded)
    state, descriptor, value = 0xb3000, 0xb6000, 0xb7000
    for offset in range(effect.instance.dm_words):
        sim.wr(state+offset, 0x7fc00000)
    sim.wr(descriptor, state)
    sim.wr(0x400000, 0xdeadbeef)
    original_write = sim.wr
    def callback_write(address, word):
        require(state <= address < state+effect.instance.dm_words
                or 0xc6d18 <= address < 0xc6f18,
                f'native callback writes outside instance/C stack at {address:#x}')
        original_write(address, word)
    def invoke(entry, args):
        for register, word in ((0x16, 0xc6e98), (0x17, 0xc6d98), (0x27, 0xffffffff),
                               (0x2e, 1), (0x37, 0), *args):
            sim.set(register, word)
        sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x10000
        sim.wr = callback_write
        try:
            callbacks.invoke_from_stock_c_caller(sim, short, entry)
        finally:
            sim.wr = original_write
    invoke(report['init_entry'], [(4, descriptor)])
    require([sim.rd(state+i) for i in (10, 11, 20)] == [0, 0, 0], 'native init did not reset transport')
    require(sim.rd(state+14) == effect.width, 'native init channel count differs from model width')
    require(sim.rd(state+9) == 0x7fc00000 and sim.rd(0x400000) == 0xdeadbeef,
            'native init touched unrelated controls/history')
    for live in (False, True):
        sim.wr(state+20, int(live))
        sim.wr(value, 1)
        for pid in (10, 11):
            invoke(report['control_entry'], [(4, pid), (8, value), (12, descriptor)])
            require(sim.rd(state+pid) == int(live), 'native transport control initialization guard differs')
    carved = allocation.inspect_member_arenas(e2, dm_words=effect.instance.dm_words,
                pm_words=effect.instance.pm_words, sdram_words=effect.instance.sdram_words)
    require(carved['complete_prefix'] and carved['memory_guards_intact'],
            'native member allocation replay failed')


def oracle_binary(directory):
    compiler = shutil.which('clang++') or shutil.which('g++')
    require(compiler is not None, 'C++ compiler required for independent audio verification')
    exe = Path(directory) / 'atmosphere-vectors'
    result = subprocess.run([compiler, '-std=c++17', '-O1', '-ffp-contract=off',
                '-I', str(HERE), str(ROOT/'tests/microlooper_vectors.cpp'), '-o', str(exe)],
                capture_output=True, text=True, timeout=90)
    require(result.returncode == 0, 'C++ oracle failed to compile: '+result.stderr)
    return exe


def guard_audio_memory(runner, effect):
    """Reject every out-of-instance access, including reads past mono buffers."""
    sim = runner.sim
    owned = [(runner.state, runner.state+effect.instance.dm_words),
             (runner.ring, runner.ring+effect.instance.sdram_words),
             (0xb8000, 0xb8000+16*effect.width),
             (0xb8100, 0xb8100+16*effect.width)]
    readable = owned + [(runner.call_record, runner.call_record+3),
                        (runner.instance, runner.instance+8)]
    original_read, original_write = sim.rd, sim.wr
    def checked_read(address):
        require(any(low <= address < high for low, high in readable),
                f'candidate process reads outside its instance/buffers at {address:#x}')
        return original_read(address)
    def checked_write(address, word):
        require(any(low <= address < high for low, high in owned),
                f'candidate process writes outside its instance/buffers at {address:#x}')
        original_write(address, word)
    sim.rd, sim.wr = checked_read, checked_write


def verify_audio(e2, decoded, report):
    cases = [(0, 1., .1875), (1, 1., .1875), (1, 1., .8125),
             (2, 1., .1875), (2, 1., .8125), (0, 0., .8125), (2, .5, .8125)]
    results = []
    with tempfile.TemporaryDirectory(prefix='atmosphere-verify-') as directory:
        oracle = oracle_binary(directory)
        for effect, row in model_reports(report):
            worst_error, instruction_peak = 0., 0
            for mode, clock, modify in cases:
                capture, playback = 128, 320
                expected = np.frombuffer(subprocess.check_output([str(oracle), str(mode), str(clock),
                            str(modify), str(capture), str(playback), 'changes', str(effect.width)],
                            timeout=10), np.float32).reshape(-1, 2)
                if effect.width == 1:
                    expected = expected[:, 0]
                sim, _ = visa.load(e2, parcel_order='high-first', external_parcel_order='low-first')
                sim.pm.update(decoded)
                final_pm = dict(sim.pm)
                runner = bridge.Bridge(sim=sim, core_base=report['pm_base'],
                                       bridge_base=row['process_entry'], instance=0x31122f,
                                       channels=effect.width)
                sim.pm = final_pm  # discard every source-assembled instruction from the fixture
                runner.symbols[bridge.ENTRY] = row['process_entry']
                runner.params(mode=mode, clock=clock, modify=modify, length=.63, mix=.8)
                for address in range(runner.ring, runner.ring+effect.instance.sdram_words):
                    sim.wr(address, 0x7fc00000)
                guard_audio_memory(runner, effect)
                original_step = sim.step
                def checked_step():
                    require(sim.pc in decoded, f'candidate process left verified code at {sim.pc:#x}')
                    return original_step()
                sim.step = checked_step
                actual = []
                for first in range(0, capture+playback, 16):
                    if first == capture:
                        runner.params(play=True)
                    if first == capture+32:
                        runner.params(length=.05)
                    if first == capture+64:
                        runner.params(overdub=True)
                    if first == capture+80:
                        runner.params(mode=(mode+1) % 3)
                    if first == capture+128:
                        runner.params(overdub=False, clock=1-clock)
                    if first == capture+160:
                        runner.params(play=False)
                    if first == capture+192:
                        runner.params(play=True)
                    samples = [(((i*37) % 127-63)/256, ((i*19) % 113-56)/256)
                               for i in range(first, first+16)]
                    if effect.width == 1:
                        samples = [frame[0] for frame in samples]
                    before = sim.cycles
                    actual.extend(runner.block(samples, inplace=first % 32 == 0))
                    instruction_peak = max(instruction_peak, sim.cycles-before)
                actual = np.asarray(actual)
                require(np.isfinite(actual).all(), 'candidate produced non-finite audio/stale history')
                error = float(np.max(np.abs(actual-expected)))
                require(error <= 2e-6,
                        f'C++ audio mismatch width={effect.width} mode={mode} clock={clock}: {error}')
                worst_error = max(worst_error, error)
            results.append(dict(preset_id=effect.preset_id, width=effect.width, cases=len(cases),
                                frames=len(cases)*448, maximum_absolute_error=worst_error,
                                sampled_instruction_peak=instruction_peak))
    return dict(models=results, cases=len(cases)*len(MODELS),
                stereo_frames=sum(r['frames'] for r in results if r['width'] == 2),
                mono_frames=sum(r['frames'] for r in results if r['width'] == 1),
                maximum_absolute_error=max(r['maximum_absolute_error'] for r in results),
                sampled_instruction_peak=max(r['sampled_instruction_peak'] for r in results),
                instruction_counts_are_hardware_cycles=False)


def verify_archive(data, report, *, audio=True):
    sizes = verify_integrity(data)
    declared = dict(preset_id=EFFECT.preset_id, primitive=EFFECT.primitive,
                    private_dm_words=EFFECT.instance.dm_words,
                    private_pm_words=EFFECT.instance.pm_words,
                    private_sdram_words=EFFECT.instance.sdram_words,
                    entry2_bytes=sizes[2],
                    entry2_remaining_bytes=layout.ENTRY2_INJECTION_LIMIT-sizes[2])
    require(all(type(report.get(key)) is int and report[key] == value
                for key, value in declared.items()), 'report identity/private-allocation/partition binding differs')
    if 'candidate_archive_sha256' in report:
        require(report['candidate_archive_sha256'] == hashlib.sha256(data).hexdigest(),
                'report candidate archive fingerprint differs')
    models = model_reports(report)
    costs = []
    for effect, row in models:
        _, cost = effect_model.verify_model(data, effect)
        require(type(row.get('declared_dsp_cost')) is int and row['declared_dsp_cost'] == cost,
                'report DSP charge differs from model table')
        costs.append(dict(preset_id=effect.preset_id, width=effect.width, declared_dsp_cost=cost))
    cost = costs[0]['declared_dsp_cost']
    controls = microlooper_native.verify_installed(kit.get_entry_swapped(data, 0))
    e2 = kit.l6ia.swap32(kit.get_entry_swapped(data, 2))
    baseline, sections, decoded = verify_layout(e2, report)
    require(report.get('declared_dsp_cost') == cost, 'report DSP charge differs from model table')
    result = dict(archive_sha256=hashlib.sha256(data).hexdigest(), nam_slots=baseline.slots,
                  declared_dsp_cost=cost, entry2_bytes=sizes[2],
                  entry2_remaining_bytes=layout.ENTRY2_INJECTION_LIMIT-sizes[2],
                  executable_sections=sections, controls=controls, models=costs,
                  allocation_verified_offline=True, audio_verified_offline=False,
                  native_callbacks_executed=False, native_member_allocator_executed=False,
                  hardware_timing_verified=False, hardware_audio_qualified=False)
    if audio:
        for effect, row in models:
            verify_callbacks(e2, decoded, row, effect)
        result['audio'] = verify_audio(e2, decoded, report)
        result['audio_verified_offline'] = True
        result['native_callbacks_executed'] = True
        result['native_member_allocator_executed'] = True
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--allocation-only', action='store_true', help='skip callback/audio execution explicitly')
    parser.add_argument('--json', type=Path, help='write the verification result')
    args = parser.parse_args(argv)
    try:
        result = verify_archive(load_image(args.image), json.loads(args.report.read_text()),
                                audio=not args.allocation_only)
    except (ValueError, AssertionError, KeyError, struct.error, zlib.error) as exc:
        parser.exit(1, f'Atmosphere candidate rejected: {exc}\n')
    text = json.dumps(result, indent=2)+'\n'
    if args.json:
        args.json.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
