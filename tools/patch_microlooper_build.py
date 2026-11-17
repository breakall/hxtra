#!/usr/bin/env python3
"""Build phases for the development Atmosphere; no hardware operation.

Metadata precedes the normal M4 feature pass. DSP linking follows NAM, click
and GR so the final boot-memory and partition checks see the complete image.
Experimental native cost is explicit; current profile measurements are recorded
in docs/research/features/microlooper-hardware-log.md.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import kit_patch_amp as kit
import patch_microlooper as model
from microlooper_definition import EFFECT, MONO_EFFECT, MODELS
from effect_model import verify_model
from sharc import microlooper as layout
from sharc import microlooper_adapter as loader
from sharc import microlooper_audio as audio
from sharc import microlooper_bridge as bridge
from sharc import microlooper_init as callbacks
from sharc import ldr_compact
from sharc import microlooper_placement as placement
from sharc import microlooper_split as split
from dataclasses import asdict

UNUSED_REGISTRIES = {
    EFFECT.name: [0x012e, 0x60aceb, 0, 0x60ad36, 0x60ac8c, 0x8ce74, 9, 4],
    MONO_EFFECT.name: [0x0100, 0x60bb54, 0, 0, 0x60ba02, 0x8cfdc, 7, 4],
}


def prepare_metadata(data, *, dsp_cost, mono_dsp_cost=None, log=print):
    return model.register_models(data, dsp_costs={
        EFFECT.name: dsp_cost,
        MONO_EFFECT.name: dsp_cost if mono_dsp_cost is None else mono_dsp_cost,
    }, log=log)


def verify_metadata(data):
    return {effect.name: verify_model(data, effect) for effect in MODELS}


def link_dsp(data, *, log=print, require_controls=True):
    """Link cold external and hot internal ISA beside the unchanged NAM baseline."""
    metadata = verify_metadata(data)
    _, dsp_cost = metadata[EFFECT.name]
    controls = {}
    if require_controls:
        import microlooper_native
        e0 = kit.get_entry_swapped(data, 0)
        controls.update(microlooper_native.verify_installed(e0))
    raw = kit.l6ia.swap32(kit.get_entry_swapped(data, 2))
    records = list(loader.ldr_blocks(raw))
    baseline = layout.require_baseline(records)
    for effect in MODELS:
        address = model.REGISTRY_ADDRESSES[effect.name]
        if [loader.ldr_word(raw, address+i) for i in range(8)] != UNUSED_REGISTRIES[effect.name]:
            raise ValueError(f'{effect.display} primitive is already installed or changed')
    core = split.plan(baseline, records)
    counts = [core.external_instructions, core.internal_instructions, bridge.instructions(),
              sum(len(s.words) for s in callbacks.assemble(0xe0000)[0])]
    external_encoded = sum(n+n % 2 for n in (counts[0], counts[2], counts[3]))
    encoded = external_encoded + counts[1] + counts[1] % 2
    heap6_end, heap4_begin = placement.require_native_reservation(records)
    if not heap6_end <= baseline.ddr2_to < layout.nam_multi.DDR2_END <= heap4_begin:
        raise ValueError('Atmosphere executable reservation overlaps the native heaps')
    placed = placement.plan(external_encoded, records, data_begin=baseline.ddr2_to,
                            data_end=layout.nam_multi.DDR2_END, claims=baseline.claims())
    base = placed.code_pm
    cold_section, hot_section, core_symbols = core.assemble(base)
    bridge_base = base+counts[0]+counts[0] % 2
    bridge_sections, bridge_symbols = bridge.assemble(bridge_base, core_symbols[audio.ENTRY])
    callback_base = bridge_base+counts[2]+counts[2] % 2
    callback_sections, callback_symbols = callbacks.assemble(callback_base)
    # Cold code uses the existing DDR2 reservation. Repeated processing uses
    # only the split planner's disjoint internal gap; no NAM storage moves.
    blocks = placement.pack(placed, [cold_section]+bridge_sections+callback_sections)
    blocks += kit.pack_init_l48(hot_section.addr, hot_section.words)
    raw, saved = ldr_compact.compact(raw)
    process = bridge_symbols[bridge.ENTRY]
    models = []
    for effect in MODELS:
        registry = callbacks.registry(effect.primitive, process, callback_base, effect=effect)
        address = model.REGISTRY_ADDRESSES[effect.name]
        blocks += kit.pack_init_l32(address, registry)
        models.append(dict(
            effect=effect.describe(), preset_id=effect.preset_id, primitive=effect.primitive,
            registry_address=address, process_entry=process, init_entry=registry[1],
            control_entry=registry[4], private_dm_words=effect.instance.dm_words,
            private_pm_words=effect.instance.pm_words,
            private_sdram_words=effect.instance.sdram_words,
            declared_dsp_cost=metadata[effect.name][1]))
    registry = models[0]
    projected = len(raw)+len(blocks)*4
    if projected > layout.ENTRY2_INJECTION_LIMIT:
        raise ValueError(f'Atmosphere Entry 2 exceeds its partition by {projected-layout.ENTRY2_INJECTION_LIMIT} bytes')
    raw = kit.inject_sharc_ldr_blocks(raw, blocks)
    if len(raw) > layout.ENTRY2_INJECTION_LIMIT:
        raise ValueError(f'Atmosphere Entry 2 exceeds its partition by {len(raw)-layout.ENTRY2_INJECTION_LIMIT} bytes')
    out, _, _ = kit.l6ia.rebuild_archive(data, {2: kit.l6ia.swap32(raw)})
    report = dict(experimental=True, hardware_verified=False, native_stereo_abi_verified=False,
                  native_dsp_cost_measured=False,
                  nam_slots=baseline.slots, preset_id=model.PRESET_ID, primitive=model.PRIM[0], declared_dsp_cost=dsp_cost,
                  pm_base=base, process_entry=process, init_entry=registry['init_entry'], control_entry=registry['control_entry'],
                  section_instructions=counts, encoded_instructions=encoded, code_ldr_records=2,
                  private_dm_words=bridge.STATE_WORDS, private_pm_words=callbacks.PM_WORDS,
                  private_sdram_words=callbacks.SDRAM_WORDS, zero_data_saved_bytes=saved,
                  entry2_bytes=len(raw), entry2_remaining_bytes=layout.ENTRY2_INJECTION_LIMIT-len(raw),
                  controls_verified=require_controls, controls=controls)
    report['effect'] = EFFECT.describe()
    report['models'] = models
    report['code_storage'] = dict(kind='external_isa48', **asdict(placed),
                                  data_words=placed.words32, hardware_fetch_timing_verified=False)
    report['code_split'] = core.describe()
    report['executable_sections'] = [
        dict(kind='external_isa48', code_pm=base, instructions=external_encoded,
             data_begin=placed.data_begin, data_end=placed.data_end),
        dict(kind='internal_isa48', code_pm=hot_section.addr,
             instructions=len(hot_section.words)+len(hot_section.words) % 2),
    ]
    log(f'[+] Atmosphere DSP: {report}')
    return out, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('metadata', 'dsp'))
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--dsp-cost', type=int)
    parser.add_argument('--mono-dsp-cost', type=int)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    if args.input.resolve() == args.output.resolve():
        parser.error('input and output must have distinct paths')
    if args.report and args.report.resolve() in (args.input.resolve(), args.output.resolve()):
        parser.error('report must have a distinct path')
    data, _ = kit.load_l6ia_from_any(str(args.input))
    if args.phase == 'metadata':
        out, report = prepare_metadata(data, dsp_cost=args.dsp_cost, mono_dsp_cost=args.mono_dsp_cost)
    else:
        out, report = link_dsp(data)
    # build.py packs the HXF only after complete archive integrity verification.
    if args.output.suffix.lower() != '.l6ia':
        parser.error('phase output must be .l6ia')
    args.output.write_bytes(out)
    if args.report:
        if isinstance(report, list):
            report = {'models': report}
        report['output_md5'] = hashlib.md5(out).hexdigest()
        args.report.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
