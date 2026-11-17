#!/usr/bin/env python3
"""Sample encoded looper instruction paths; these are not hardware DSP costs.

Run from any directory. Synthetic complete zero histories and old-head/seam
positions exercise 720 control combinations, not an exhaustive worst-case bound.
ssim has no external-memory stall or hardware pipeline model for this report.
"""
import hashlib
from itertools import product
import json

import microlooper_audio as audio
import ssim


def profile():
    names = ('Envelope', 'Tape', 'Stretch')
    peaks = {name: {'instructions': 0} for name in names}
    listen = {'instructions': 0}
    configurations = 0

    def measure(engine):
        before = engine.sim.cycles
        engine.block([(.2, .3)] * 16)
        return engine.sim.cycles - before

    for mode, clock, zone, length, overdub in product(
            range(3), (1., .75, .5, .25, 0.), range(8), (.0000374, .5, 1.), (False, True)):
        configurations += 1
        context = dict(mode=names[mode], clock=clock, modify=(zone + .5) / 8, length=length)
        engine = audio.Audio()
        engine.params(mode=mode, clock=clock, modify=context['modify'], length=length, mix=.8)
        count = measure(engine)
        if count > listen['instructions']:
            listen = dict(context, instructions=count, path='initial-listen')
        # The simulator's unwritten ring is zero. Set history validity and a
        # physical write cursor without spending 24k recording frames per case.
        engine.sim.wr(engine.state + audio.RECORDED, audio.RING_FRAMES)
        engine.sim.wr(engine.state + audio.WRITE, 23500)
        engine.params(play=True)
        count = measure(engine)
        if count > peaks[names[mode]]['instructions']:
            peaks[names[mode]] = dict(context, instructions=count, overdub=False, path='capture')
        engine.params(overdub=overdub)
        # Private core fields: play, old head, fade, two grain heads and phase.
        for offset, value in ((31, 23000.123046875), (32, 23000.123046875),
                              (33, .99), (34, 23759.125), (35, 12000.5), (36, .3)):
            engine.sim.wr(engine.state + offset, ssim.f2b(value))
        engine.sim.wr(engine.state + 37, 1)
        engine.sim.wr(engine.state + 30, engine.sim.rd(engine.state + audio.DIVIDER) - 1)
        count = measure(engine)
        if count > peaks[names[mode]]['instructions']:
            peaks[names[mode]] = dict(context, instructions=count, overdub=overdub, path='old-head/seam')
    return dict(kernel_sha256=hashlib.sha256(audio.ASM.read_bytes()).hexdigest(),
                kernel_instructions=audio.instructions(), configuration_count=configurations,
                measurement='sampled executed instructions per 16 stereo frames; not hardware cycles, '
                            'DSP percentages or exhaustive bounds; no external-memory stall/pipeline model',
                initial_listen_peak=listen, mode_peaks=peaks)


if __name__ == '__main__':
    print(json.dumps(profile(), indent=2))
