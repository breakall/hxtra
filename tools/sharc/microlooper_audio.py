#!/usr/bin/env python3
"""Assemble the looper audio kernel and exercise its provisional stereo contract.

I0=private DM state (153 words); I1/I2=32 interleaved float32 words, 16 frames.
DM12/13 are caller-allocated SDRAM begin/end. Raw Overdub is an idempotent
level: only a fresh low-to-high transition while playing enables it; transport
changes clear it. After an ignored high while listening, return low first.
A fresh instance ignores Play high until it has observed Play low at least once,
so restored preset controls cannot immediately capture an empty recording. This contract is NOT a verified
native stereo FX adapter. No model registration, global ring or instance limit.
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
RING_BEGIN, RING_END = 12, 13
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
    def __init__(self, state=0xb3000, ring=0x400000, sim=None):
        self.sim = sim or ssim.Sim()
        self.sim.strict_cbufen = True
        self.state, self.ring = state, ring
        sections, self.symbols = assemble()
        self.sim.load(sections)
        for k in range(STATE_WORDS):
            self.sim.wr(state + k, 0)
        self.sim.wr(state + RING_BEGIN, ring)
        self.sim.wr(state + RING_END, ring + RING_WORDS)
        self.params(mode=1, length=.5, modify=.75, clock=1, mix=.5, play=False, overdub=False)
        self.calls = 0

    def params(self, **values):
        for name, v in values.items():
            word = int(v) if name in ('mode', 'play', 'overdub') else ssim.f2b(v)
            self.sim.wr(self.state + PARAMS[name], word)

    def block(self, samples=None, inplace=False):
        samples = [(0., 0.)] * 16 if samples is None else samples
        if len(samples) != 16:
            raise ValueError('a DSP block is exactly 16 stereo frames')
        src, dst = 0xb8000, 0xb8000 if inplace else 0xb8100
        for k, pair in enumerate(samples):
            for channel, value in enumerate(pair):
                self.sim.wr(src + 2*k + channel, ssim.f2b(value))
        for code, value in ((0x10, self.state), (0x11, src), (0x12, dst)):
            self.sim.set(code, value)
        self.sim.call(self.symbols[ENTRY], limit=100_000)
        self.calls += 1
        return [(ssim.b2f(self.sim.rd(dst + 2*k)), ssim.b2f(self.sim.rd(dst + 2*k + 1))) for k in range(16)]
