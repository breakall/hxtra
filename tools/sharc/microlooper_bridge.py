#!/usr/bin/env python3
"""Assemble the native planar audio bridge and execute encoded test blocks."""
from functools import lru_cache
from pathlib import Path

import microlooper_audio as audio
import microlooper_placement as placement
import sasm
import ssim
from microlooper_definition import EFFECT

ASM = Path(__file__).resolve().parents[2] / 'src/sharc/microlooper_bridge.asm'
SPILL_BEGIN = audio.STATE_WORDS
STATE_WORDS = EFFECT.instance.dm_words
ENTRY = EFFECT.callbacks.process


@lru_cache(None)
def assemble(bridge_base=0xe3500, core_entry=0xe3000):
    """Explicit addresses only; caller must separately check whole-image fit."""
    if bridge_base < 0 or bridge_base % 2 or core_entry < 0:
        raise ValueError('bridge PM base must be nonnegative/even; core entry nonnegative')
    source = ASM.read_text().replace('BRIDGE_PM_BASE', hex(bridge_base))
    source = source.replace('MICROLOOPER_CORE_ENTRY', hex(core_entry))
    source = source.replace('MICROLOOPER_DESCRIPTOR_HEAP_BEGIN', hex(placement.NATIVE_HEAP6_BEGIN))
    source = source.replace('MICROLOOPER_DESCRIPTOR_HEAP_LAST', hex(placement.NATIVE_HEAP6_END-8-placement.NATIVE_HEAP6_BEGIN))
    return sasm.assemble(source, ASM.name)


def instructions():
    return sum(len(s.words) for s in assemble()[0] if s.kind == 'pm')


class Bridge:
    """Encoded bridge plus actual audio core; test caller supplies planar data."""
    def __init__(self, state=0xb3000, ring=0x400000, call_record=0xb6000,
                 instance=0x99f80, sim=None, core_base=0xe3000,
                 bridge_base=0xe3500, channels=2):
        if channels not in (1, 2):
            raise ValueError("channel count must be1 or2")
        self.channels = channels
        self.ring_words = audio.RING_FRAMES * channels
        self.state, self.ring = state, ring
        self.call_record, self.instance = call_record, instance
        self.sim = sim or ssim.Sim()
        self.sim.strict_cbufen = True
        core_sections, core_symbols = audio.assemble(base=core_base)
        self.sim.load(core_sections)
        sections, self.symbols = assemble(bridge_base, core_symbols[audio.ENTRY])
        self.sim.load(sections)
        for offset in range(STATE_WORDS):
            self.sim.wr(state + offset, 0)
        # Match the native block width; per-model initialization sets DM14.
        self.sim.wr(state, 16)
        self.sim.wr(state + 2, channels)
        self.sim.wr(state + audio.CHANNELS, channels)
        self.sim.wr(call_record + 2, instance)
        self.sim.wr(instance + 6, ring)
        self.sim.wr(instance + 7, ring + self.ring_words)
        self.params(mode=1, length=.5, modify=.75, clock=1, mix=.5,
                    play=False, overdub=False)

    def params(self, **values):
        for name, value in values.items():
            word = int(value) if name in ('mode', 'loop', 'play', 'overdub') else ssim.f2b(value)
            self.sim.wr(self.state + audio.PARAMS[name], word)

    def block(self, samples=None, inplace=False):
        samples = ([0.] * 16 if self.channels == 1 else [(0., 0.)] * 16) if samples is None else samples
        if len(samples) != 16:
            raise ValueError('a DSP block is exactly16 frames')
        src, dst = 0xb8000, 0xb8000 if inplace else 0xb8100
        for frame, sample in enumerate(samples):
            values = (sample,) if self.channels == 1 else sample
            for channel, value in enumerate(values):
                self.sim.wr(src + 16*channel + frame, ssim.f2b(value))
        for code, value in ((0x10, self.state), (0x11, src), (0x12, dst),
                            (0x13, self.call_record)):
            self.sim.set(code, value)
        self.sim.call(self.symbols[ENTRY], limit=100_000)
        if self.channels == 1:
            return [ssim.b2f(self.sim.rd(dst + frame)) for frame in range(16)]
        return [(ssim.b2f(self.sim.rd(dst + frame)),
                 ssim.b2f(self.sim.rd(dst + 16 + frame))) for frame in range(16)]
