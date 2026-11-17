"""Place Atmosphere's repeated processing in the proven internal code gap.

NAM2 keeps the sample loop and its helpers internally. NAM3 has room for the
wrap/read/interpolation helpers. Cold setup and native callbacks stay in the
existing external reservation. The source assembler used by unit fixtures is
unchanged; this module owns the production split and its ownership checks.
"""
from dataclasses import dataclass, field
import re

from sharc import microlooper as layout
from sharc import microlooper_audio as audio
from sharc import sasm


@dataclass(frozen=True)
class Split:
    region: str
    internal_pm: int
    internal_instructions: int
    external_instructions: int
    _source: str = field(repr=False)

    def assemble(self, external_pm):
        """Return the cold section, hot section, and their common symbol map."""
        if type(external_pm) is not int or external_pm < 0 or external_pm % 2:
            raise ValueError('external PM base must be nonnegative and even')
        sections, symbols = sasm.assemble(
            self._source.replace('KIT_PM_BASE', hex(external_pm)), 'microlooper_split.asm')
        if (len(sections) != 2 or any(s.kind != 'pm' for s in sections)
                or sections[0].addr != external_pm
                or sections[1].addr != self.internal_pm
                or [len(s.words) for s in sections]
                != [self.external_instructions, self.internal_instructions]):
            raise ValueError('assembled Atmosphere split differs from its plan')
        return sections[0], sections[1], symbols

    def describe(self):
        return dict(region=self.region, internal_pm=self.internal_pm,
                    internal_instructions=self.internal_instructions,
                    external_instructions=self.external_instructions)


def _label(source, name):
    matches = list(re.finditer(rf'(?m)^{name}:\s*$', source))
    if len(matches) != 1:
        raise ValueError(f'Atmosphere split requires one {name} label')
    return matches[0].start()


def plan(baseline, records):
    """Choose the largest supported region fitting independently owned storage.

    Reserving the ordinary click/GR neighbors even when omitted keeps ownership
    independent of environment flags. No optional-feature hole or native heap
    slack is borrowed. Existing boot records and NAM runtime claims may not
    overlap the selected internal span, including through normal/ISA aliases.
    """
    records = list(records)
    if baseline.slots not in (2, 3):
        raise ValueError('Atmosphere split requires an unchanged NAM2 or NAM3 profile')
    gap = layout.profile(baseline.slots, metronome=True, gr=baseline.slots == 2)
    source = audio.ASM.read_text()
    sections, symbols = sasm.assemble(source.replace('KIT_PM_BASE', '0x200000'), 'microlooper_kernel.asm')
    if len(sections) != 1 or sections[0].kind != 'pm':
        raise ValueError('Atmosphere source must contain one core PM section')
    end = _label(source, 'ml_return')
    total = len(sections[0].words)
    # The large region is tried first; both choices preserve the original
    # arithmetic. Only the sample-loop cut needs an explicit fallthrough jump.
    for name, label, jump in (('sample-loop', 'ml_sample', True),
                              ('read-helpers', 'ml_wrap', False)):
        start = _label(source, label)
        count = symbols['ML_RETURN'] - symbols[label.upper()]
        if not 0 < count < total or start >= end:
            raise ValueError('Atmosphere split labels are out of order')
        try:
            internal = gap.place(count)
        except ValueError:
            continue
        prefix = source[:start]
        if jump:
            prefix += f'JUMP {label};\n'
        else:
            code = re.sub(r'//[^\n]*', '', prefix).strip()
            if not code.endswith('JUMP ml_return;'):
                raise ValueError('Atmosphere helper cut would discard a fallthrough edge')
        text = prefix + source[end:] + f'\n.section pm {internal:#x}\n' + source[start:end]
        split = Split(name, internal, count, total-count+int(jump), text)
        split.assemble(0x200000)
        low = layout.normal_word(internal)
        high = layout.normal_word(internal+count+count % 2)
        if not gap.block3_begin <= low < high <= layout.normal_word(gap.block3_end_pm):
            raise ValueError('Atmosphere internal code exceeds the proven profile gap')
        for claim_low, claim_high in baseline.claims():
            if claim_low < high and low < claim_high:
                raise ValueError('Atmosphere internal code overlaps NAM runtime storage')
        for tag, n, address, _ in records:
            lo, hi = layout.internal_span(tag, n, address)
            if lo < high and low < hi:
                raise ValueError(f'Atmosphere internal code overlaps boot record at {address:#x}')
        return split
    raise ValueError('Atmosphere hot code does not fit the proven internal profile gap')
