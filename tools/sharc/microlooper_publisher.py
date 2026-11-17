"""Diagnostic-only coherent context export using existing GR frame transport.

The regular frame_probe.asm is unchanged. dsp_source replaces exactly the
62 instructions exporting old state words219..249, preserving every subsequent
GR process/control label and its entire DM allocation. The caller places the
standalone publisher separately and rewrites the known original GR PM bytes.
No image patch, registry change, source reservation or hardware action occurs
here. Publication coherence on actual SPI/DMA still needs hardware validation.
"""
from pathlib import Path

import microlooper_adapter as adapter
import patch_comp
import sasm

ASM = Path(__file__).resolve().parents[2] / 'src/sharc/microlooper_publisher.asm'
TAG = 0x4d4c0001
WORDS = 16
FRAME_TAG, FRAME_BEGIN, FRAME_COUNT, FRAME_PAYLOAD, FRAME_END = 219, 220, 221, 222, 238
PUBLISH_SAVE_OFFSET = 181
REPLACED_INSTRUCTIONS = 62


def assemble(base, sidecar):
    """Standalone publisher, caller supplies frame in I4. All registers restored."""
    if base < 0 or base % 2:
        raise ValueError('PM base must be nonnegative and even')
    if sidecar % 2 or not any(low <= sidecar and sidecar + adapter.STATE_WORDS <= high
                              for low, high in adapter.INTERNAL_DM_RANGES):
        raise ValueError('sidecar must be even and fit internal normal-word memory')
    source = ASM.read_text().replace('KIT_PM_BASE', hex(base)).replace('MICROLOOPER_SIDECAR', hex(sidecar))
    return sasm.assemble(source, ASM.name)


def dsp_source(dm_base, pm_base, publisher_entry):
    """Same-size GR variant; no appended code, registry relocation or DM growth.

    The native wrapper has already validated I4 as a frame. Replace only old
    diagnostic state-copy stores: marker200, peaks216/217, controls218 and
    window/coefficient250..252 remain byte-for-byte unchanged.
    """
    if publisher_entry < 0 or publisher_entry % 2:
        raise ValueError('publisher PM entry must be nonnegative and even')
    source = patch_comp.dsp_asm(dm_base, pm_base)
    old = ''.join(f'      R2 = DM(FP_LOG + {n + 19});\n      DM({n + 219}, I4) = R2;\n'
                  for n in range(31))
    if source.count(old) != 1:
        raise ValueError('GR frame export source differs from the guarded diagnostic replacement')
    replacement = f'      CALL {publisher_entry:#x};\n' + '      NOP;\n' * (REPLACED_INSTRUCTIONS - 1)
    return source.replace(old, replacement)


def assemble_gr(dm_base, pm_base, publisher_entry):
    return sasm.assemble(dsp_source(dm_base, pm_base, publisher_entry), 'frame_probe_microlooper.asm')
