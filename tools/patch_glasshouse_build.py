#!/usr/bin/env python3
"""Register native Glasshouse models and link their complete SHARC program.

Metadata runs before the ordinary M4/GR passes. DSP linking runs last, after
Atmosphere when selected, and reserves a disjoint permanent ISA48 code span.
The existing external stock payloads use the checked one-shot LZ32 boot
transport so the physical Entry2 partition remains bounded.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import kit_patch_amp as kit
import patch_glasshouse as model
from glasshouse_definition import EFFECT, MODELS
from sharc import glasshouse_audio as audio
from sharc import glasshouse_init as callbacks
from sharc import glasshouse_storage as storage
from sharc import microlooper as layout
from sharc import microlooper_adapter as loader
from sharc import microlooper_placement as placement


def prepare_metadata(data, *, dsp_cost, mono_dsp_cost=None, log=print):
    return model.register_models(data, dsp_costs={
        MODELS[0].name: dsp_cost,
        MODELS[1].name: dsp_cost if mono_dsp_cost is None else mono_dsp_cost,
    }, log=log)


def verify_metadata(data):
    return model.verify_metadata(data)


def _instructions(sections):
    if not sections or any(s.kind != 'pm' for s in sections):
        raise ValueError('Glasshouse executable must contain only PM sections')
    return sum(len(s.words)+len(s.words) % 2 for s in sections)


def plan_code(records, baseline, instructions):
    """Reserve after every existing owner in NAM's explicitly reserved tail."""
    heap6, heap4 = placement.require_native_reservation(records)
    if not heap6 <= baseline.ddr2_to < layout.nam_multi.DDR2_END <= heap4:
        raise ValueError('Glasshouse executable reservation overlaps native heaps')
    begin, end = baseline.ddr2_to, layout.nam_multi.DDR2_END
    for record in records:
        span = placement.physical_span(record)
        if span and span[0] < 2*end and 2*begin < span[1]:
            begin = max(begin, (span[1]+1)//2)
    if begin >= end:
        raise ValueError('Glasshouse executable does not fit the reserved DDR2 tail')
    return placement.plan(instructions, records, data_begin=begin, data_end=end,
                          claims=baseline.claims())


def link_dsp(data, *, log=print):
    metadata = verify_metadata(data)
    raw = kit.l6ia.swap32(kit.get_entry_swapped(data, 2))
    if storage.has_transport(raw):
        raise ValueError('Glasshouse DSP is already installed')
    records = list(loader.ldr_blocks(raw))
    baseline = layout.require_baseline(records)
    for effect in MODELS:
        address = model.REGISTRY_ADDRESSES[effect.name]
        actual = [loader.ldr_word(raw, address+i) for i in range(8)]
        if actual != model.UNUSED_REGISTRIES[effect.name]:
            raise ValueError(f'{effect.display} primitive is already installed or changed')
    core_sections, _ = audio.assemble(0x219000)
    core_count = _instructions(core_sections)
    callback_sections, _ = callbacks.assemble(0x219000)
    callback_count = _instructions(callback_sections)
    decoder_count = storage.decoder_instructions()
    decoder_count += decoder_count % 2
    placed = plan_code(records, baseline, decoder_count+core_count+callback_count)
    decoder_pm = placed.code_pm
    core_pm = decoder_pm+decoder_count
    core_sections, core_symbols = audio.assemble(core_pm)
    callback_pm = core_pm+core_count
    callback_sections, callback_symbols = callbacks.assemble(callback_pm)
    if _instructions(core_sections) != core_count or _instructions(callback_sections) != callback_count:
        raise ValueError('relocation changed Glasshouse executable size')
    process = core_symbols[audio.ENTRY]
    raw, transport = storage.install(raw, decoder_pm)
    code_begin = core_pm*3//2
    code = placement.Placement(core_pm, core_count+callback_count, code_begin, placed.data_end)
    blocks = placement.pack(code, [*core_sections, *callback_sections])
    models = []
    for effect in MODELS:
        registry = callbacks.registry(effect.primitive, process, callback_pm, effect=effect)
        address = model.REGISTRY_ADDRESSES[effect.name]
        blocks += kit.pack_init_l32(address, registry)
        models.append(dict(effect=effect.describe(), preset_id=effect.preset_id,
                           primitive=effect.primitive, registry_address=address,
                           process_entry=process, init_entry=registry[1],
                           control_entry=registry[4], private_dm_words=effect.instance.dm_words,
                           private_pm_words=effect.instance.pm_words,
                           private_sdram_words=effect.instance.sdram_words,
                           declared_dsp_cost=metadata[effect.name][1]))
    projected = len(raw)+4*len(blocks)
    if projected > layout.ENTRY2_INJECTION_LIMIT:
        raise ValueError(f'Glasshouse Entry 2 exceeds its partition by {projected-layout.ENTRY2_INJECTION_LIMIT} bytes')
    raw = kit.inject_sharc_ldr_blocks(raw, blocks)
    startup = storage.verify_transport(raw)
    out, _, _ = kit.l6ia.rebuild_archive(data, {2: kit.l6ia.swap32(raw)})
    report = dict(nam_slots=baseline.slots, models=models, effect=EFFECT.describe(),
                  preset_id=EFFECT.preset_id, primitive=EFFECT.primitive,
                  declared_dsp_cost=metadata[EFFECT.name][1],
                  pm_base=core_pm, process_entry=process,
                  init_entry=models[0]['init_entry'], control_entry=models[0]['control_entry'],
                  private_dm_words=EFFECT.instance.dm_words,
                  private_pm_words=EFFECT.instance.pm_words,
                  private_sdram_words=EFFECT.instance.sdram_words,
                  core_instructions=core_count, callback_instructions=callback_count,
                  entry2_bytes=len(raw), entry2_remaining_bytes=layout.ENTRY2_INJECTION_LIMIT-len(raw),
                  boot_transport=transport, startup_verification=startup,
                  code_storage=dict(kind='external_isa48', **asdict(code)),
                  permanent_reservation=asdict(placed),
                  executable_sections=[
                      dict(kind='external_isa48', code_pm=decoder_pm,
                           instructions=decoder_count, data_begin=placed.data_begin,
                           data_end=code_begin, role='startup_decoder'),
                      dict(kind='external_isa48', **asdict(code), role='glasshouse_audio_and_callbacks')],
                  candidate_archive_sha256=hashlib.sha256(out).hexdigest(),
                  hardware_boot_verified=False, hardware_dsp_cost_verified=False)
    log(f'[+] Glasshouse DSP: {report}')
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
    if args.output.suffix.lower() != '.l6ia':
        parser.error('phase output must be .l6ia')
    if args.report and args.report.resolve() in (args.input.resolve(), args.output.resolve()):
        parser.error('report must have a distinct path')
    data, _ = kit.load_l6ia_from_any(str(args.input))
    if args.phase == 'metadata':
        out, report = prepare_metadata(data, dsp_cost=args.dsp_cost, mono_dsp_cost=args.mono_dsp_cost)
    else:
        out, report = link_dsp(data)
    args.output.write_bytes(out)
    if args.report:
        if isinstance(report, list):
            report = {'models': report}
        report['output_md5'] = hashlib.md5(out).hexdigest()
        args.report.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
