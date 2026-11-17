#!/usr/bin/env python3
"""Development-only stereo ring diagnostic and current HXtra resource accounting.

The probe ABI is caller-defined interleaved stereo, NOT verified against the
stock stereo effect dispatcher. Nothing here registers a production effect,
chooses a DSP percentage, or changes firmware. CLI: microlooper.py [--image file].
"""
import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import nam_multi
import patch_click
import patch_comp
import patch_amp
import sasm

ASM = HERE.parents[1] / 'src/sharc/microlooper_probe.asm'
STATE_WORDS = 49
RING_FRAMES = 24000
RING_WORDS = RING_FRAMES * 2
ENTRY2_INJECTION_LIMIT = 0x80000  # hxf_ram payload sectors0x8803..0x8c03, excluding the header


def pm_words(records):
    """Replay normal instruction records; later writers replace earlier ones."""
    memory = {}
    for tag, count, base, payload in records:
        if tag == 5:
            raw = struct.pack(f'<{len(payload)}I', *payload)
            memory.update((base+i, int.from_bytes(raw[6*i:6*i+6], 'little')) for i in range(count))
        elif tag == 2:
            memory.update((base+i, 0) for i in range(count))
    return memory


def require_baseline(records):
    """Identify an unchanged NAM2/3 baseline, including resident data.

    Read the existing generator without changing its sources or placement.
    Physical gap ownership requires the exact profile, not just a slot count.
    """
    records = list(records)
    memory = pm_words(records)
    for slots in (3, 2):
        with nam_multi.flags(['--mid-sweep']):
            source, lay = nam_multi.build(slots)
        sections, _ = sasm.assemble(source, f'nam{slots}.asm')
        if any(s.kind == 'pm' and any(memory.get(s.addr+i) != word
                                      for i, word in enumerate(s.words)) for s in sections):
            continue
        data = {}
        for tag, count, base, payload in records:
            if tag not in (1, 4):
                continue
            for section in sections:
                if section.kind != 'dm':
                    continue
                low, high = max(base, section.addr), min(base+count, section.addr+len(section.words))
                for address in range(low, high):
                    data[address] = payload[address-base] if tag == 4 else 0
        if all(s.kind != 'dm' or all(data.get(s.addr+i) == word
                                    for i, word in enumerate(s.words)) for s in sections):
            return lay
    raise ValueError('Atmosphere requires an unchanged NAM2 or NAM3 mid-sweep baseline')


def require_nam1(records):
    """Retained diagnostic probes use their explicitly selected NAM1 layout."""
    with nam_multi.flags(['--mid-sweep']):
        source, _ = nam_multi.build(1)
    sections, _ = sasm.assemble(source, 'nam1.asm')
    memory = pm_words(records)
    if any(s.kind == 'pm' and any(memory.get(s.addr+i) != word
                                  for i, word in enumerate(s.words)) for s in sections):
        raise ValueError('micro-looper diagnostic requires the exact NAM1 mid-sweep code profile')


def internal_span(tag, count, base):
    """Conservative internal normal-word extent of a loader record."""
    if tag in (1, 4):
        return base, base+count
    if tag in (2, 5):
        low, high = max(base, 0xe0000), min(base+count, 0xe5556)
        if low < high:
            return normal_word(low), normal_word(high+high % 2)
    if tag == 3:
        return base//2, (base+count+1)//2
    return 0, 0


def assemble(base):
    """Assemble diagnostic with explicit PM address; no firmware ABI adapter."""
    if base < 0 or base % 2:
        raise ValueError('PM base must be nonnegative and even')
    return sasm.assemble(ASM.read_text().replace('KIT_PM_BASE', hex(base)), ASM.name)


def probe_instructions():
    sections, _ = assemble(nam_multi.NW3)
    return sum(len(s.words) for s in sections if s.kind == 'pm')


def normal_word(pm):
    return nam_multi.NW3 + (pm - nam_multi.NW3) * 3 // 2


@dataclass(frozen=True)
class Profile:
    nam_slots: int
    metronome: bool
    gr: bool
    block2_free_words: int
    block3_begin: int
    block3_end_pm: int
    metronome_reserved: bool

    @property
    def block3_free_words(self):
        return normal_word(self.block3_end_pm) - self.block3_begin

    def place(self, instructions, shared_dm_words=0):
        """Place an even-padded PM section after any explicitly reserved shared DM.

        Instance state belongs in the effect allocation, so normally shared DM=0.
        Raises instead of overlapping existing NAM/GR/metronome sections.
        """
        if instructions < 1 or shared_dm_words < 0:
            raise ValueError('positive instruction count and nonnegative shared DM required')
        base = self.block3_end_pm - (instructions + instructions % 2)
        if normal_word(base) < self.block3_begin + shared_dm_words:
            raise ValueError('micro-looper diagnostic does not fit this internal-memory profile')
        return base


def profile(nam_slots=3, metronome=False, gr=False):
    if nam_slots not in (1, 2, 3):
        raise ValueError('current NAM layout supports 1, 2 or 3 slots')
    if gr and nam_slots == 3:
        raise ValueError('current GR layout requires one or two NAM slots')
    lay = nam_multi.layout(['--mid-sweep', '--slots', str(nam_slots)])
    lower = lay.b3_to
    # GR layout reserves the click's location even when HX_CLICK is not enabled.
    reserve_click = metronome or gr
    upper = patch_click.pm_base(patch_click.kernel_size(), lay) if reserve_click else lay.cold_pm
    if gr:
        dm, pm = patch_comp.dsp_place(lay)
        sections, _ = sasm.assemble(patch_comp.dsp_asm(dm, pm), 'frame_probe.asm')
        end = max(s.addr + len(s.words) + len(s.words) % 2 for s in sections if s.kind == 'pm')
        lower = normal_word(end)
    if normal_word(upper) < lower:
        raise ValueError('existing DSP sections overlap')
    return Profile(nam_slots, metronome, gr, nam_multi.B2_END - lay.b2_to,
                   lower, upper, reserve_click)


def image_budget(payload_bytes, instructions, *, section_instructions=None):
    """Code LDR blocks' exact encoded growth under the current injection guard.

    Registry/other blocks are NOT included. The existing hxf_ram partition map
    gives1024 payload sectors after the separate sub-header (512KiB total).
    """
    if payload_bytes < 0 or payload_bytes % 4 or instructions < 1:
        raise ValueError('aligned payload bytes and positive instructions required')
    counts = tuple(section_instructions) if section_instructions is not None else (instructions,)
    if not counts or any(type(n) is not int or n < 1 for n in counts) or sum(counts) != instructions:
        raise ValueError('positive section instruction counts must sum to the total')
    encoded = sum(n + n % 2 for n in counts)
    growth = 12 * len(counts) + 6 * encoded
    result = payload_bytes + growth
    return {'payload_bytes': payload_bytes, 'code_ldr_growth_bytes': growth,
            'code_sections': len(counts), 'encoded_instructions': encoded,
            'result_bytes': result, 'injection_guard_bytes': ENTRY2_INJECTION_LIMIT,
            'remaining_bytes': ENTRY2_INJECTION_LIMIT - result,
            'fits_injection_guard': result <= ENTRY2_INJECTION_LIMIT}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', help='inspect Entry 2 payload length of a supplied .hxf/L6IA')
    parser.add_argument('--audio', action='store_true', help='measure the complete audio kernel instead of the ring probe')
    parser.add_argument('--bridge', action='store_true', help='include the disabled planar bridge with the complete audio kernel')
    parser.add_argument('--compact-data', action='store_true', help='include opt-in zero-data encoding savings in image accounting')
    args = parser.parse_args()
    state_words = STATE_WORDS
    if args.audio or args.bridge:
        import microlooper_audio
        n = microlooper_audio.instructions()
        state_words = microlooper_audio.STATE_WORDS
    else:
        n = probe_instructions()
    counts = [n]
    if args.bridge:
        import microlooper_bridge
        counts.append(microlooper_bridge.instructions())
        state_words = microlooper_bridge.STATE_WORDS
        n = sum(counts)
    encoded_n = sum(count + count % 2 for count in counts)
    profiles = []
    for slots, click, gr in ((3, False, False), (3, True, False), (2, False, False),
                             (2, True, False), (2, True, True), (1, True, True)):
        p = profile(slots, click, gr)
        row = dict(asdict(p), block3_free_words=p.block3_free_words)
        try:
            row.update(kernel_pm_base=p.place(encoded_n), fits_internal_memory=True)
            if args.bridge:
                row['bridge_pm_base'] = row['kernel_pm_base'] + counts[0] + counts[0] % 2
        except ValueError as e:
            row.update(fits_internal_memory=False, reason=str(e))
        profiles.append(row)
    kernel = 'audio_with_planar_bridge' if args.bridge else 'audio' if args.audio else 'ring_probe'
    report = {'kernel': kernel, 'native_stereo_abi_verified': False,
              'instructions': n, 'instance_state_words': state_words,
              'encoded_instructions': encoded_n, 'section_instructions': counts,
              'audio_ring_words': RING_WORDS, 'profiles': profiles}
    if args.image:
        image, _ = patch_amp.load_l6ia_from_any(args.image)
        raw = patch_amp.l6ia.swap32(patch_amp.get_entry_swapped(image, 2))
        saved = 0
        if args.compact_data:
            import ldr_compact
            raw, saved = ldr_compact.compact(raw)
        budget = image_budget(len(raw), n, section_instructions=counts)
        registry_bytes = len(patch_amp.pack_init_l32(0x200058, [0] * 8)) * 4
        budget.update(zero_data_saved_bytes=saved, registry_growth_bytes=registry_bytes,
                      with_registry_bytes=budget['result_bytes'] + registry_bytes,
                      with_registry_remaining_bytes=budget['remaining_bytes'] - registry_bytes,
                      with_registry_fits_injection_guard=budget['result_bytes'] + registry_bytes <= ENTRY2_INJECTION_LIMIT,
                      native_adapter_not_included=not args.bridge,
                      native_initialization_and_lifecycle_not_included=True)
        report['code_block_budget'] = budget
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
