#!/usr/bin/env python3
"""Verify the final Glasshouse archive, startup decoder and encoded audio.

The report identifies locations; declarations, canonical executable words,
native callbacks and the independent source oracle establish the contract.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'sharc'))
import effect_model
import glasshouse_audio as audio
import glasshouse_init as callbacks
import glasshouse_storage as storage
import kit_patch_amp as kit
import microlooper as layout
import microlooper_adapter as loader
import microlooper_allocation as allocation
import microlooper_placement as placement
import microlooper_visa as visa
import ssim
import verify_atmosphere_candidate as atmosphere
from glasshouse import reference
from glasshouse_definition import MODELS, FLOAT_BOOLS, PARAMETER_BASE
from patch_glasshouse import REGISTRY_ADDRESSES

require = atmosphere.require


def model_reports(report):
    rows = report.get('models')
    require(isinstance(rows, list) and len(rows) == len(MODELS), 'both Glasshouse models required')
    names = [row.get('effect', {}).get('model_name') for row in rows]
    require(set(names) == {effect.name for effect in MODELS}, 'Glasshouse model names differ')
    result = []
    for effect in MODELS:
        row = rows[names.index(effect.name)]
        require(json.loads(json.dumps(row.get('effect'))) == json.loads(json.dumps(effect.describe())),
                'Glasshouse declaration differs')
        expected = dict(preset_id=effect.preset_id, primitive=effect.primitive,
                        registry_address=REGISTRY_ADDRESSES[effect.name],
                        private_dm_words=effect.instance.dm_words,
                        private_pm_words=effect.instance.pm_words,
                        private_sdram_words=effect.instance.sdram_words)
        require(all(type(row.get(key)) is int and row[key] == value for key, value in expected.items()),
                'Glasshouse identity/allocation differs')
        require(type(row.get('declared_dsp_cost')) is int
                and 1 <= row['declared_dsp_cost'] <= 7500, 'Glasshouse report cost differs')
        result.append((effect, row))
    first_effect, first = result[0]
    require(json.loads(json.dumps(report.get('effect'))) == json.loads(json.dumps(first_effect.describe())),
            'Glasshouse root declaration differs')
    for key in ('preset_id', 'primitive', 'declared_dsp_cost', 'private_dm_words',
                'private_pm_words', 'private_sdram_words', 'process_entry', 'init_entry', 'control_entry'):
        require(type(report.get(key)) is int and report[key] == first.get(key),
                f'Glasshouse root {key} differs')
    return result


def verify_code(e2, report):
    records = list(loader.ldr_blocks(e2))
    baseline = layout.require_baseline(records)
    require(report.get('nam_slots') == baseline.slots, 'Glasshouse report NAM profile differs')
    placement.require_native_reservation(records)
    atmosphere.require_pinned_neighbors(records, baseline)
    normal = {}
    for tag, count, base, payload in records:
        if tag in (1, 4):
            normal.update((base+i, payload[i] if tag == 4 else 0) for i in range(count))
    sections = report.get('executable_sections')
    require(isinstance(sections, list) and len(sections) == 2, 'Glasshouse executable sections differ')
    physical, decoded = [], {}
    for section in sections:
        pm, count = section.get('code_pm'), section.get('instructions')
        begin, end = section.get('data_begin'), section.get('data_end')
        require(section.get('kind') == 'external_isa48'
                and all(type(x) is int for x in (pm, count, begin, end))
                and pm % 2 == count % 2 == 0 and count > 0
                and 3*pm == 2*begin and 3*count == 2*(end-begin), 'Glasshouse ISA aliases differ')
        require(baseline.ddr2_to <= begin < end <= layout.nam_multi.DDR2_END,
                'Glasshouse code is outside reserved DDR2')
        require(all(not (lo < end and begin < hi) for lo, hi in baseline.claims()),
                'Glasshouse code overlaps NAM state')
        span = (2*begin, 2*end)
        require(all(not (lo < span[1] and span[0] < hi) for lo, hi in physical),
                'Glasshouse executable aliases overlap')
        atmosphere.require_last_writer_space(records, span, 'external_isa48')
        raw = b''.join(normal[address].to_bytes(4, 'little') for address in range(begin, end))
        decoded.update((pm+i, int.from_bytes(raw[6*i:6*i+6], 'little')) for i in range(count))
        physical.append(span)
    core_pm = report.get('pm_base')
    core_sections, symbols = audio.assemble(core_pm)
    core_count = sum(len(section.words)+len(section.words) % 2 for section in core_sections)
    require(core_count == report.get('core_instructions'), 'Glasshouse core size differs')
    callback_sections, callback_symbols = callbacks.assemble(core_pm+core_count)
    callback_count = sum(len(section.words)+len(section.words) % 2 for section in callback_sections)
    require(type(report.get('callback_instructions')) is int
            and callback_count == report['callback_instructions'], 'Glasshouse callback size differs')
    table = storage._table_record(e2)[3]
    decoder_pm, decoder_count = table[4:6]
    decoder_sections, _ = storage.assemble_decoder(decoder_pm)
    expected_decoder = dict(kind='external_isa48', code_pm=decoder_pm,
                            instructions=decoder_count, data_begin=decoder_pm*3//2,
                            data_end=(decoder_pm+decoder_count)*3//2, role='startup_decoder')
    expected_audio = dict(kind='external_isa48', code_pm=core_pm,
                         instructions=core_count+callback_count, data_begin=core_pm*3//2,
                         data_end=(core_pm+core_count+callback_count)*3//2,
                         role='glasshouse_audio_and_callbacks')
    require(sections == [expected_decoder, expected_audio], 'Glasshouse executable roles/extent binding differs')
    require(core_pm == decoder_pm+decoder_count, 'Glasshouse executable sections are not contiguous')
    require(report.get('code_storage') == {key: value for key, value in expected_audio.items() if key != 'role'},
            'Glasshouse code_storage differs')
    require(report.get('permanent_reservation') == dict(code_pm=decoder_pm,
                instructions=decoder_count+core_count+callback_count, data_begin=decoder_pm*3//2,
                data_end=expected_audio['data_end']), 'Glasshouse permanent_reservation differs')
    symbols.update(callback_symbols)
    for section in decoder_sections+core_sections+callback_sections:
        canonical = list(section.words)+[0]*(len(section.words) % 2)
        require(all(decoded.get(section.addr+i) == word for i, word in enumerate(canonical)),
                'Glasshouse emitted executable differs from verified source')
    for effect, row in model_reports(report):
        actual = [loader.ldr_word(e2, row['registry_address']+i) for i in range(8)]
        require(actual == effect.registry(symbols), 'Glasshouse native registry differs')
        require(all(row.get(key) == symbols[symbol] for key, symbol in
                    (('process_entry', effect.callbacks.process), ('init_entry', effect.callbacks.init),
                     ('control_entry', effect.callbacks.control))), 'Glasshouse report callbacks differ')
    return decoded


def verify_callbacks(e2, decoded, effect, row):
    sim, short = visa.load(e2, parcel_order='high-first', external_parcel_order='low-first')
    sim.pm.update(decoded)
    state, descriptor, value = 0xb3000, 0xb6000, 0xb7000
    for i in range(effect.instance.dm_words):
        sim.wr(state+i, 0x7fc00000)
    sim.wr(descriptor, state)
    original_write = sim.wr
    def checked_write(address, word):
        require(state <= address < state+effect.instance.dm_words or 0xc6d18 <= address < 0xc6f18,
                'Glasshouse C callback writes outside owned state/stack')
        original_write(address, word)
    def invoke(entry, args):
        for register, word in ((0x16, 0xc6e98), (0x17, 0xc6d98), (0x27, 0xffffffff),
                               (0x2e, 1), (0x37, 0), *args):
            sim.set(register, word)
        sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x10000
        sim.wr = checked_write
        try:
            callbacks.invoke_from_stock_c_caller(sim, short, entry, limit=256)
        finally:
            sim.wr = original_write
    invoke(row['init_entry'], [(4, descriptor)])
    require(sim.rd(state+4) == 0 and sim.rd(state+5) == effect.width
            and sim.rd(state+6) == sim.rd(state+7) == 0, 'Glasshouse initialization differs')
    require([sim.rd(state+i) for i in range(16, 55)] == list(callbacks.default_words()),
            'Glasshouse source defaults differ')
    for p in effect.parameters:
        word = ssim.f2b(p.default) if p.type == 3 else int(p.default)
        sim.wr(value, word)
        invoke(row['control_entry'], [(4, p.pid), (8, value), (12, descriptor)])
        expected = ssim.f2b(p.default) if p.pid-PARAMETER_BASE in FLOAT_BOOLS else word
        require(sim.rd(state+p.pid) == expected, 'Glasshouse native parameter delivery differs')
    carved = allocation.inspect_member_arenas(e2, dm_words=effect.instance.dm_words,
                pm_words=effect.instance.pm_words, sdram_words=effect.instance.sdram_words)
    require(carved['complete_prefix'] and carved['memory_guards_intact'], 'Glasshouse allocation differs')


def configurations():
    for name in ('default', 'compression', 'sag', 'dark', 'bright', 'physics',
                 'drive', 'gate', 'swell', 'spread', 'key', 'automation'):
        knobs = [list(page) for page in reference.KNOBS]
        toggles = [list(page) for page in reference.TOGGLES]
        if name == 'compression': knobs[0][0], knobs[0][1], knobs[0][3] = .6, .75, .1
        if name == 'sag': knobs[0][1] = 1.
        if name == 'dark': knobs[0][4], toggles[0][1] = 0., 0
        if name == 'bright': knobs[0][4], toggles[0][1] = 1., 2
        if name == 'physics': toggles[0][2], toggles[1][0] = 2, 2
        if name == 'drive': knobs[2][4], knobs[0][0] = 1., .8
        if name == 'gate': knobs[2][2], knobs[1][0] = 1., 1.
        if name == 'swell': toggles[2][1], knobs[1][2], knobs[1][3] = 1, 0., 0.
        if name == 'spread': toggles[2][0], toggles[2][2], knobs[2][0] = 1, 2, 1.
        if name == 'key': toggles[2][0], knobs[0][1] = 2, .8
        if name == 'automation':
            toggles[3], knobs[3], knobs[2][1] = [2, 2, 1], [.5]*6, 1.
        yield name, knobs, toggles


def verify_control_pulses(e2, decoded, effect, row, report, oracle):
    """Run native C delivery and the actual process code across a short pulse."""
    knobs = [list(page) for page in reference.KNOBS]
    toggles = [list(page) for page in reference.TOGGLES]
    toggles[2][1], toggles[3][0] = 1, 1  # manual swell and one-shot automation
    knobs[1][2], knobs[1][3], knobs[2][1], knobs[3] = 0., 0., 1., [.5]*6
    frames = np.asarray([(((i*37) % 127-63)/128, ((i*19) % 113-56)/128)
                         for i in range(192)], dtype=np.float32)
    if effect.width == 1:
        frames[:, 1] = frames[:, 0]
    expected = reference.run(oracle, reference.settings(knobs, toggles, reset=True),
                reference.switch('enable', True), reference.process(frames[:128]),
                reference.switch('aux', True), reference.switch('aux', False),
                reference.switch('enable', False), reference.switch('enable', True),
                reference.process(frames[128:]))
    sim, short = visa.load(e2, parcel_order='high-first', external_parcel_order='low-first')
    sim.pm.update(decoded)
    final_pm = dict(sim.pm)
    engine = audio.Audio(channels=effect.width, base=report['pm_base'], sim=sim)
    sim.pm = final_pm
    engine.settings(knobs, toggles)
    descriptor, value = 0xb6000, 0xb7000
    sim.wr(descriptor, engine.state)
    def control(pid, word):
        sim.wr(value, word)
        for register, argument in ((0x16, 0xc6e98), (0x17, 0xc6d98),
                                   (0x27, 0xffffffff), (0x2e, 1), (0x37, 0),
                                   (4, pid), (8, value), (12, descriptor)):
            sim.set(register, argument)
        sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x10000
        callbacks.invoke_from_stock_c_caller(sim, short, row['control_entry'], limit=256)
    actual = []
    step = sim.step
    def checked_step():
        require(sim.pc in decoded, 'Glasshouse pulse process left verified code')
        return step()
    for first in range(0, len(frames), 16):
        if first == 128:
            for pid, word in ((52, 1), (52, 0), (54, 0), (54, 1)):
                control(pid, word)
            require(sim.rd(engine.state+6) == sim.rd(engine.state+7) == 1,
                    'Glasshouse native short-pulse latches differ')
        sim.step = checked_step
        try:
            block = frames[first:first+16]
            actual.extend(engine.block(block[:, 0] if effect.width == 1 else block))
        finally:
            sim.step = step
    require(sim.rd(engine.state+6) == sim.rd(engine.state+7) == 0,
            'Glasshouse short-pulse latches were not consumed')
    if effect.width == 1:
        expected = expected[:, 0]
    error = float(np.max(np.abs(np.asarray(actual)-expected)))
    require(np.isfinite(actual).all() and error <= 1e-5,
            f'Glasshouse native short-pulse source mismatch width={effect.width}: {error}')
    return dict(frames=len(frames), maximum_absolute_error=error,
                aux_and_enable_native_pulses_executed=True)


def verify_audio(e2, decoded, report):
    results = []
    with tempfile.TemporaryDirectory(prefix='glasshouse-verify-') as directory:
        oracle = reference.build_reference(directory)
        for effect, row in model_reports(report):
            peak, maximum = 0, 0.
            for name, knobs, toggles in configurations():
                frames = np.asarray([(((i*37) % 127-63)/128, ((i*19) % 113-56)/128)
                                     for i in range(64)], dtype=np.float32)
                if effect.width == 1:
                    frames[:, 1] = frames[:, 0]
                expected = reference.run(oracle, reference.settings(knobs, toggles, reset=True),
                                         reference.switch('enable', True), reference.process(frames))
                sim, _ = visa.load(e2, parcel_order='high-first', external_parcel_order='low-first')
                sim.pm.update(decoded)
                final_pm = dict(sim.pm)
                engine = audio.Audio(channels=effect.width, base=report['pm_base'], sim=sim)
                sim.pm = final_pm  # discard every instruction assembled by the harness
                engine.settings(knobs, toggles)
                step, read, write = sim.step, sim.rd, sim.wr
                allowed = ((engine.state, engine.state+effect.instance.dm_words),
                           (0xb8000, 0xb8020), (0xb8100, 0xb8120))
                def checked_step():
                    require(sim.pc in decoded, 'Glasshouse audio left verified code')
                    return step()
                def checked_read(address):
                    require(any(lo <= address < hi for lo, hi in allowed), 'Glasshouse reads outside instance/buffers')
                    return read(address)
                def checked_write(address, word):
                    require(any(lo <= address < hi for lo, hi in allowed), 'Glasshouse writes outside instance/buffers')
                    write(address, word)
                sim.step, sim.rd, sim.wr = checked_step, checked_read, checked_write
                actual = []
                for first in range(0, len(frames), 16):
                    samples = frames[first:first+16]
                    before = sim.cycles
                    actual.extend(engine.block(samples[:, 0] if effect.width == 1 else samples,
                                               inplace=first % 32 == 0))
                    peak = max(peak, sim.cycles-before)
                if effect.width == 1:
                    expected = expected[:, 0]
                error = float(np.max(np.abs(np.asarray(actual)-expected)))
                require(np.isfinite(actual).all() and error <= (1e-4 if name == 'drive' else 1e-5),
                        f'Glasshouse source mismatch width={effect.width} case={name}: {error}')
                maximum = max(maximum, error)
            pulses = verify_control_pulses(e2, decoded, effect, row, report, oracle)
            results.append(dict(preset_id=effect.preset_id, width=effect.width, cases=12,
                                frames=768, maximum_absolute_error=maximum,
                                sampled_instruction_peak=peak, transient_actions=pulses))
    return dict(models=results, instruction_counts_are_hardware_cycles=False)


def verify_archive(data, report, *, audio_check=True):
    sizes = atmosphere.verify_integrity(data)
    require(report.get('candidate_archive_sha256') == hashlib.sha256(data).hexdigest(),
            'Glasshouse report fingerprint differs from final archive')
    require(report.get('entry2_bytes') == sizes[2]
            and report.get('entry2_remaining_bytes') == layout.ENTRY2_INJECTION_LIMIT-sizes[2],
            'Glasshouse report partition binding differs')
    for effect, row in model_reports(report):
        _, cost = effect_model.verify_model(data, effect)
        require(cost == row.get('declared_dsp_cost'), 'Glasshouse report cost differs')
    raw = kit.l6ia.swap32(kit.get_entry_swapped(data, 2))
    startup = storage.verify_transport(raw)
    e2 = storage.expand(raw)
    decoded = verify_code(e2, report)
    result = dict(archive_sha256=hashlib.sha256(data).hexdigest(), entry2_bytes=sizes[2],
                  entry2_remaining_bytes=layout.ENTRY2_INJECTION_LIMIT-sizes[2],
                  boot_transport=startup, allocation_verified_offline=True,
                  audio_verified_offline=False, native_callbacks_executed=False,
                  native_member_allocator_executed=False, hardware_boot_verified=False, hardware_dsp_cost_verified=False)
    if audio_check:
        for effect, row in model_reports(report):
            verify_callbacks(e2, decoded, effect, row)
        result['audio'] = verify_audio(e2, decoded, report)
        result.update(audio_verified_offline=True, native_callbacks_executed=True,
                      native_member_allocator_executed=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--allocation-only', action='store_true')
    parser.add_argument('--json', type=Path)
    args = parser.parse_args(argv)
    try:
        result = verify_archive(atmosphere.load_image(args.image), json.loads(args.report.read_text()),
                                audio_check=not args.allocation_only)
    except (ValueError, AssertionError, KeyError, struct.error) as exc:
        parser.exit(1, f'Glasshouse candidate rejected: {exc}\n')
    output = json.dumps(result, indent=2)+'\n'
    if args.json:
        args.json.write_text(output)
    print(output, end='')


if __name__ == '__main__':
    main()
