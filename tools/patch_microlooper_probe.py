"""Offline linker for an explicitly instrumented Acoustic Sim diagnostic.

Requires the known NAM1/mid-sweep kernel. Reserves GR and metronome space even
when absent, logs the last native invocation, and changes no effect graph,
allocation, controls or model identity. No build flag, hardware operation or
production looper is supplied here. --telemetry adds an explicit diagnostic
readback through an already-installed, exactly verified GR wrapper.
"""
import argparse
import hashlib
import json
from pathlib import Path

import kit_patch_amp as kit
from sharc import microlooper as layout
from sharc import microlooper_adapter as adapter
from sharc import nam_multi
from sharc import sasm

REGISTRY, PRIMITIVE, ORIGINAL = 0x200580, 0x9c51, 0x8e9e3
ORIGINAL_REGISTRY = [PRIMITIVE, 0x61525a, 0, 0, 0x61530f, ORIGINAL, 129, 0]


def _replace_pm(raw, original, replacement):
    """Replace an exactly known PM section without growing its boot record.

    Preserve every address/label and modify only each instruction's final boot
    writer. This keeps existing GR registry pointers and all data untouched.
    """
    if (original.kind != 'pm' or replacement.kind != 'pm' or original.addr != replacement.addr
            or len(original.words) != len(replacement.words)):
        raise ValueError('replacement must preserve the complete PM section extent')
    records = list(adapter.ldr_blocks(raw))
    memory = layout.pm_words(records)
    if any(memory.get(original.addr+i) != value for i, value in enumerate(original.words)):
        raise ValueError('diagnostic requires the exact existing GR code')
    offsets, cursor = {}, 384 * 4
    for tag, count, base, payload in records:
        if tag == 5:
            offsets.update((base+i, cursor+12+6*i) for i in range(count))
        elif tag == 2:
            for i in range(count):
                offsets.pop(base+i, None)
        cursor += 12 + len(payload)*4
    out = bytearray(raw)
    for i, (before, after) in enumerate(zip(original.words, replacement.words)):
        if before != after:
            offset = offsets.get(original.addr+i)
            if offset is None:
                raise ValueError('replacement instruction has no initialized PM writer')
            out[offset:offset+6] = after.to_bytes(6, 'little')
    return bytes(out)


def patch_diagnostic(data, log=print, *, telemetry=False):
    """Return (L6IA, placement report); this is a diagnostic, not the looper.

    Verify known code before trusting its free-memory profile. Reject any boot
    record already occupying the sidecar or code and retain all native registry
    words except the process pointer. telemetry requires the original GR code
    at its known NAM1 location; it keeps every GR entry/control address and
    native/GR telemetry field. No hardware operation is performed.
    """
    e0 = kit.get_entry_swapped(data, 0)
    if kit.e0_device(kit._parse_e0_segments(e0)).NAME != 'HX Stomp':
        raise ValueError('diagnostic targets HX Stomp 3.80.0')
    raw = kit.l6ia.swap32(kit.get_entry_swapped(data, 2))
    records = list(adapter.ldr_blocks(raw))
    registry = [adapter.ldr_word(raw, REGISTRY+i) for i in range(8)]
    if registry != ORIGINAL_REGISTRY:
        raise ValueError('Acoustic Sim registry is changed or already instrumented')
    layout.require_nam1(records)
    profile = layout.profile(1, metronome=True, gr=True)
    sidecar = (profile.block3_begin + 1) & ~1
    trial, _ = adapter.assemble_diagnostic(0xe0000, sidecar)
    adapter_count = sum(len(s.words) for s in trial if s.kind == 'pm')
    counts = [adapter_count]
    if telemetry:
        from sharc import microlooper_publisher as publisher
        pub_trial, _ = publisher.assemble(0xe0000, sidecar)
        counts.append(sum(len(s.words) for s in pub_trial if s.kind == 'pm'))
    encoded = sum(n + n % 2 for n in counts)
    base = profile.place(encoded, shared_dm_words=adapter.STATE_WORDS)
    sections, symbols = adapter.assemble_diagnostic(base, sidecar)
    telemetry_report = {}
    if telemetry:
        import patch_comp
        publisher_base = base + adapter_count + adapter_count % 2
        publisher_sections, publisher_symbols = publisher.assemble(publisher_base, sidecar)
        publisher_entry = publisher_symbols['MICROLOOPER_PUBLISH_CONTEXT']
        sections += publisher_sections
        lay = nam_multi.layout(['--mid-sweep', '--slots', '1'])
        gr_dm, gr_pm = patch_comp.dsp_place(lay)
        original, original_symbols = sasm.assemble(patch_comp.dsp_asm(gr_dm, gr_pm), 'frame_probe.asm')
        variant, variant_symbols = publisher.assemble_gr(gr_dm, gr_pm, publisher_entry)
        if original_symbols != variant_symbols or len(original) != len(variant):
            raise ValueError('diagnostic GR variant changed native entry/control addresses')
        registry_words = {}
        for tag, count, address, payload in records:
            if tag in (1, 4):
                low, high = max(address, 0x200000), min(address+count, 0x2008d0)
                registry_words.update((at, payload[at-address] if tag == 4 else 0)
                                      for at in range(low, high))
        for prim, _ in patch_comp.WRAPS:
            rows = [at for at in range(0x200000, 0x2008d0, 8) if registry_words.get(at) == prim]
            if (len(rows) != 1
                    or registry_words.get(rows[0]+4) != original_symbols[f'CTRL_{prim:X}']
                    or registry_words.get(rows[0]+5) != original_symbols[f'ENTRY_{prim:X}']):
                raise ValueError('diagnostic requires installed GR process/control callbacks')
        for before, after in zip(original, variant):
            if before.kind == 'pm':
                raw = _replace_pm(raw, before, after)
            elif before.addr != after.addr or before.words != after.words:
                raise ValueError('diagnostic GR variant changed its data allocation')
        telemetry_report = dict(publisher_pm=publisher_entry, publisher_instructions=counts[1],
                                gr_dm=gr_dm, gr_pm=gr_pm,
                                source_sequence_dm=sidecar + adapter.SOURCE_SEQUENCE_OFFSET)
    reserved = [(sidecar, sidecar + adapter.STATE_WORDS),
                (layout.normal_word(base), layout.normal_word(base + encoded))]
    for tag, count, address, _ in records:
        low, high = layout.internal_span(tag, count, address)
        if any(low < end and start < high for start, end in reserved):
            raise ValueError(f'diagnostic placement overlaps existing boot record at {address:#x}')
    # Existing stock loader uses ZERO_LDATA records; initialize only our sidecar.
    blocks = [1, adapter.STATE_WORDS, sidecar]
    for section in sections:
        if section.kind != 'pm':
            raise ValueError('diagnostic assembler unexpectedly requires extra data')
        blocks += kit.pack_init_l48(section.addr, section.words)
    entry = symbols['MICROLOOPER_ADAPTER_GLOBAL_ACOUSTIC_DIAGNOSTIC']
    blocks += kit.pack_init_l32(REGISTRY + 5, [entry])
    patched = kit.inject_sharc_ldr_blocks(raw, blocks)
    if len(patched) > layout.ENTRY2_INJECTION_LIMIT:
        raise ValueError('diagnostic exceeds the Entry 2 injection guard')
    updates = {2: kit.l6ia.swap32(patched)}
    if telemetry:
        import microlooper_readback
        import patch_menu
        patch = patch_menu.Patch(e0, [], {})
        telemetry_report.update(microlooper_readback.install(patch))
        patch.finish_chains()
        updates.update(patch.output())
    out, _, _ = kit.l6ia.rebuild_archive(data, updates)
    report = dict(diagnostic_only=True, native_stereo_abi_verified=False,
                  native_process=ORIGINAL, process_entry=entry, pm_base=base,
                  instructions=sum(counts), encoded_instructions=encoded,
                  adapter_instructions=adapter_count, sidecar_dm=sidecar,
                  sidecar_words=adapter.STATE_WORDS,
                  snapshot_dm=sidecar + adapter.SNAPSHOT_OFFSET,
                  entry2_bytes=len(patched), entry2_remaining_bytes=0x80000-len(patched),
                  changes_native_allocation=False, changes_model_graphs=False,
                  telemetry_readback_implemented=telemetry, hardware_telemetry_verified=False,
                  **telemetry_report)
    log(f'[+] Instrumented Acoustic Sim diagnostic: {report}')
    return out, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='NAM1 mid-sweep HXF or L6IA')
    parser.add_argument('-o', '--output', type=Path, required=True, help='diagnostic .l6ia archive')
    parser.add_argument('--telemetry', action='store_true', help='add GR-frame and USB context readback')
    parser.add_argument('--report', type=Path, help='write placement and checksum JSON')
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != '.l6ia':
        parser.error('--output must be a diagnostic .l6ia archive')
    destinations = [args.output] + ([args.report] if args.report else [])
    paths = [args.input.resolve(), *(path.resolve() for path in destinations)]
    if len(set(paths)) != len(paths):
        parser.error('input, output and report must have distinct paths')
    image, _ = kit.load_l6ia_from_any(str(args.input))
    out, report = patch_diagnostic(image, telemetry=args.telemetry)
    report.update(input_sha256=hashlib.sha256(args.input.read_bytes()).hexdigest(),
                  output_md5=hashlib.md5(out).hexdigest())
    args.output.write_bytes(out)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(f'[+] Wrote {args.output}: MD5 {report["output_md5"]}')


if __name__ == '__main__':
    main()
