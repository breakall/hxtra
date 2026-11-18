#!/usr/bin/env python3
"""Assemble and exercise the native planar mono/stereo audio kernel.

I0 is private DM state; I1/I2 are16 mono words or planar L[16],R[16].
DM12/13 own a24000-frame SDRAM ring and DM14 fixes its channel count.
A fresh instance ignores Play high until it observes Play low; transport
changes clear effective Overdub. Native initialization owns that contract.
"""
from functools import lru_cache
from pathlib import Path
import sasm
import ssim
from microlooper_definition import EFFECT

ASM = Path(__file__).resolve().parents[2] / 'src/sharc/microlooper_kernel.asm'
STATE_WORDS = 153
RING_FRAMES = 24000
RING_WORDS = EFFECT.instance.sdram_words
PARAMS = {p.name.lower(): p.pid for p in EFFECT.parameters}
RING_BEGIN, RING_END, CHANNELS = 12, 13, 14
INITIALIZED, RECORDED, PLAYING, DIVIDER = 20, 22, 26, 29
ENTRY = 'CUSTOM_AMP_ENTRY'
# See the named state map at the head of microlooper_kernel.asm.
WRITE, FULL, START, DUB_WRITE = 21, 24, 23, 25
ERRORS = 48
EFFECTIVE_OVERDUB, PREVIOUS_OVERDUB, PLAY_ARMED = 111, 112, 113


@lru_cache(None)
def assemble(base=0xe3000):
    """Explicit address, with no claim that this placement fits a NAM profile."""
    if base < 0 or base % 2:
        raise ValueError('PM base must be a nonnegative even address')
    return sasm.assemble(ASM.read_text().replace('KIT_PM_BASE', hex(base)), ASM.name)


def instructions():
    return sum(len(s.words) for s in assemble()[0] if s.kind == 'pm')


class Audio:
    """Actual encoded kernel in ssim; caller buffers, not firmware dispatch."""
    def __init__(self, state=0xb3000, ring=0x400000, sim=None, channels=2):
        if channels not in (1, 2):
            raise ValueError("channel count must be1 or2")
        self.channels = channels
        self.ring_words = RING_FRAMES * channels
        self.sim = sim or ssim.Sim()
        self.sim.strict_cbufen = True
        self.state, self.ring = state, ring
        sections, self.symbols = assemble()
        self.sim.load(sections)
        for k in range(STATE_WORDS):
            self.sim.wr(state + k, 0)
        self.sim.wr(state + RING_BEGIN, ring)
        self.sim.wr(state + RING_END, ring + self.ring_words)
        self.sim.wr(state + CHANNELS, channels)
        self.params(mode=1, length=.5, modify=.75, clock=1, mix=.5, play=False, overdub=False)
        self.calls = 0

    def params(self, **values):
        for name, v in values.items():
            word = int(v) if name in ('mode', 'loop', 'play', 'overdub') else ssim.f2b(v)
            self.sim.wr(self.state + PARAMS[name], word)

    def block(self, samples=None, inplace=False):
        samples = ([0.] * 16 if self.channels == 1 else [(0., 0.)] * 16) if samples is None else samples
        if len(samples) != 16:
            raise ValueError('a DSP block is exactly16 frames')
        src, dst = 0xb8000, 0xb8000 if inplace else 0xb8100
        for frame, sample in enumerate(samples):
            values = (sample,) if self.channels == 1 else sample
            for channel, value in enumerate(values):
                self.sim.wr(src + 16*channel + frame, ssim.f2b(value))
        for code, value in ((0x10, self.state), (0x11, src), (0x12, dst)):
            self.sim.set(code, value)
        self.sim.call(self.symbols[ENTRY], limit=100_000)
        self.calls += 1
        if self.channels == 1:
            return [ssim.b2f(self.sim.rd(dst + frame)) for frame in range(16)]
        return [(ssim.b2f(self.sim.rd(dst + frame)), ssim.b2f(self.sim.rd(dst + 16 + frame))) for frame in range(16)]
