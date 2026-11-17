#!/usr/bin/env python3
"""Build phases for the development Atmosphere; no hardware operation.

Metadata precedes the normal M4 feature pass. DSP linking follows NAM, click
and GR so the final boot-memory and partition checks see the complete image.
Native cost is caller-supplied until measured on the device.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

import kit_patch_amp as kit
import patch_microlooper as model
from microlooper_definition import EFFECT
from effect_model import verify_model
from sharc import microlooper as layout
from sharc import microlooper_adapter as loader
from sharc import microlooper_audio as audio
from sharc import microlooper_bridge as bridge
from sharc import microlooper_init as callbacks
from sharc import ldr_compact
from sharc import microlooper_placement as placement
from dataclasses import asdict

UNUSED_REGISTRY = [0x012e, 0x60aceb, 0, 0x60ad36, 0x60ac8c, 0x8ce74, 9, 4]


def prepare_metadata(data, *, dsp_cost, log=print):
    return model.register_model(data, dsp_cost=dsp_cost, log=log)


def verify_metadata(data):
    return verify_model(data, EFFECT)


def link_dsp(data, *, log=print, require_controls=True):
    """Link Atmosphere ISA into reserved DDR2 alongside the unchanged NAM baseline."""
    _, dsp_cost = verify_metadata(data)
    controls = {}
    if require_controls:
        import microlooper_native
        e0 = kit.get_entry_swapped(data, 0)
        controls.update(microlooper_native.verify_installed(e0))
    raw = kit.l6ia.swap32(kit.get_entry_swapped(data, 2))
    records = list(loader.ldr_blocks(raw))
    baseline = layout.require_baseline(records)
    if [loader.ldr_word(raw, model.PRIM[1]+i) for i in range(8)] != UNUSED_REGISTRY:
        raise ValueError('Atmosphere primitive is already installed or changed')
    counts = [audio.instructions(), bridge.instructions(),
              sum(len(s.words) for s in callbacks.assemble(0xe0000)[0])]
    encoded = sum(n+n % 2 for n in counts)
    heap6_end, heap4_begin = placement.require_native_reservation(records)
    if not heap6_end <= baseline.ddr2_to < layout.nam_multi.DDR2_END <= heap4_begin:
        raise ValueError('Atmosphere executable reservation overlaps the native heaps')
    placed = placement.plan(encoded, records, data_begin=baseline.ddr2_to,
                            data_end=layout.nam_multi.DDR2_END, claims=baseline.claims())
    base = placed.code_pm
    core_sections, core_symbols = audio.assemble(base)
    bridge_base = base+counts[0]+counts[0] % 2
    bridge_sections, bridge_symbols = bridge.assemble(bridge_base, core_symbols[audio.ENTRY])
    callback_base = bridge_base+counts[1]+counts[1] % 2
    callback_sections, callback_symbols = callbacks.assemble(callback_base)
    sections = core_sections+bridge_sections+callback_sections
    # Encode the same ISA48 instructions through their physical32-bit DDR2
    # alias. The native bootloader already supports INIT_LDATA. No internal
    # code/data placement, NAM workspace, or runtime capture storage moves.
    blocks = placement.pack(placed, sections)
    raw, saved = ldr_compact.compact(raw)
    process = bridge_symbols[bridge.ENTRY]
    registry = callbacks.registry(model.PRIM[0], process, callback_base)
    blocks += kit.pack_init_l32(model.PRIM[1], registry)
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
                  pm_base=base, process_entry=process, init_entry=registry[1], control_entry=registry[4],
                  section_instructions=counts, encoded_instructions=encoded, code_ldr_records=1,
                  private_dm_words=bridge.STATE_WORDS, private_pm_words=callbacks.PM_WORDS,
                  private_sdram_words=callbacks.SDRAM_WORDS, zero_data_saved_bytes=saved,
                  entry2_bytes=len(raw), entry2_remaining_bytes=layout.ENTRY2_INJECTION_LIMIT-len(raw),
                  controls_verified=require_controls, controls=controls)
    report['effect'] = EFFECT.describe()
    report['code_storage'] = dict(kind='external_isa48', **asdict(placed),
                                  data_words=placed.words32, hardware_fetch_timing_verified=False)
    log(f'[+] Atmosphere DSP: {report}')
    return out, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('metadata', 'dsp'))
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--dsp-cost', type=int)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args(argv)
    if args.input.resolve() == args.output.resolve():
        parser.error('input and output must have distinct paths')
    if args.report and args.report.resolve() in (args.input.resolve(), args.output.resolve()):
        parser.error('report must have a distinct path')
    data, _ = kit.load_l6ia_from_any(str(args.input))
    if args.phase == 'metadata':
        out, report = prepare_metadata(data, dsp_cost=args.dsp_cost)
    else:
        out, report = link_dsp(data)
    # build.py packs the HXF only after complete archive integrity verification.
    if args.output.suffix.lower() != '.l6ia':
        parser.error('phase output must be .l6ia')
    args.output.write_bytes(out)
    if args.report:
        report['output_md5'] = hashlib.md5(out).hexdigest()
        args.report.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
