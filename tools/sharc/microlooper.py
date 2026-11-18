"""Place Atmosphere beside the unchanged NAM, metronome and GR storage."""
from dataclasses import dataclass
import struct

import nam_multi
import patch_click
import patch_comp
import sasm

ENTRY2_INJECTION_LIMIT = 0x80000


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


def normal_word(pm):
    return nam_multi.NW3 + (pm - nam_multi.NW3) * 3 // 2


@dataclass(frozen=True)
class Profile:
    block3_begin: int
    block3_end_pm: int

    def place(self, instructions):
        """Place even-padded PM code without overlapping native sections."""
        if type(instructions) is not int or instructions < 1:
            raise ValueError('positive integer instruction count required')
        base = self.block3_end_pm - (instructions + instructions % 2)
        if normal_word(base) < self.block3_begin:
            raise ValueError('Atmosphere code does not fit this internal-memory profile')
        return base


def profile(nam_slots=3, metronome=False, gr=False):
    if nam_slots not in (2, 3):
        raise ValueError('Atmosphere supports the existing NAM2 or NAM3 layout')
    if gr and nam_slots == 3:
        raise ValueError('current GR layout requires two NAM slots')
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
    return Profile(lower, upper)
