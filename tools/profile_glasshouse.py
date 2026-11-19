#!/usr/bin/env python3
"""Count executed Glasshouse instructions without opening a device.

Counts exclude physical DDR2/cache stalls and are not measured hardware DSP
percentages. An optional source snapshot gives a reproducible before/after.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'sharc'))
import glasshouse_audio as audio
import ssim
from glasshouse import reference


def configuration(name):
    knobs = [list(page) for page in reference.KNOBS]
    toggles = [list(page) for page in reference.TOGGLES]
    if name == 'compression':
        knobs[0][0], knobs[0][1], knobs[0][3] = .6, .75, .1
    if name in ('drive', 'complex'):
        knobs[2][4] = 1.
        knobs[0][2], knobs[0][5] = .9, .2
    if name == 'complex':
        knobs[2][3], knobs[0][1], knobs[3] = 1., .85, [.4]*6
        toggles[0][2], toggles[1][0] = 2, 2
        toggles[2][0], toggles[2][2], toggles[3] = 1, 2, [2, 2, 1]
    return knobs, toggles


def samples(width, block):
    # Integer-derived input is identical across hosts, source snapshots and runs.
    pairs = [(((i*37) % 127-63)/128., ((i*19) % 113-56)/128.)
             for i in range(block*16, (block+1)*16)]
    return [left for left, _ in pairs] if width == 1 else pairs


def profile(module=audio, *, blocks=8):
    if blocks < 1:
        raise ValueError('at least one warm block is required')
    old_reciprocal = ssim.RECIPS_HW
    ssim.RECIPS_HW = True
    cases = []
    try:
        for width in (1, 2):
            for name in ('default', 'compression', 'drive', 'complex'):
                engine = module.Audio(channels=width)
                knobs, toggles = configuration(name)
                engine.settings(knobs, toggles)
                active, memory = [False], [0, 0]
                original_call, original_read, original_write = engine.sim.call, engine.sim.rd, engine.sim.wr
                def call(*args, **kwargs):
                    active[0] = True
                    try:
                        return original_call(*args, **kwargs)
                    finally:
                        active[0] = False
                def read(address):
                    memory[0] += int(active[0])
                    return original_read(address)
                def write(address, word):
                    memory[1] += int(active[0])
                    return original_write(address, word)
                engine.sim.call, engine.sim.rd, engine.sim.wr = call, read, write
                def run(block):
                    before = engine.sim.cycles
                    previous = tuple(memory)
                    engine.block(samples(width, block), inplace=bool(block % 2))
                    return (engine.sim.cycles-before, memory[0]-previous[0], memory[1]-previous[1])
                cold = run(0)
                warm = [run(block) for block in range(1, blocks+1)]
                knobs[0][3], knobs[0][4], knobs[1][5] = .9, .1, .7
                engine.settings(knobs, toggles)
                changed = run(blocks+1)
                instructions = [row[0] for row in warm]
                cases.append(dict(width=width, configuration=name,
                                  cold_instructions=cold[0], steady_min=min(instructions),
                                  steady_max=max(instructions), steady_mean=sum(instructions)/len(instructions),
                                  steady_dm_reads_mean=sum(row[1] for row in warm)/len(warm),
                                  steady_dm_writes_mean=sum(row[2] for row in warm)/len(warm),
                                  changed_settings_instructions=changed[0]))
    finally:
        ssim.RECIPS_HW = old_reciprocal
    return dict(core_isa48_instructions=module.instructions(), cases=cases,
                warm_blocks_per_case=blocks, hardware_reciprocal_seed=True,
                counts_are_hardware_cycles=False, device_access=False)


def _module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def baseline_module(root):
    """Load the frozen emitter, state and math without changing production imports."""
    root = Path(root)
    original = sys.modules.get('glasshouse_state')
    try:
        sys.modules['glasshouse_state'] = _module(root / 'tools/sharc/glasshouse_state.py',
                                                '_glasshouse_profile_state')
        return _module(root / 'tools/sharc/glasshouse_audio.py', '_glasshouse_profile_audio')
    finally:
        if original is None:
            sys.modules.pop('glasshouse_state', None)
        else:
            sys.modules['glasshouse_state'] = original


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blocks', type=int, default=8)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--json', type=Path)
    args = parser.parse_args(argv)
    result = dict(current=profile(blocks=args.blocks))
    if args.baseline:
        result['baseline'] = profile(baseline_module(args.baseline), blocks=args.blocks)
        result['baseline_source_sha256'] = {
            name: hashlib.sha256((args.baseline/name).read_bytes()).hexdigest()
            for name in ('tools/sharc/glasshouse_audio.py', 'tools/sharc/glasshouse_state.py',
                         'src/sharc/glasshouse_math.asm')}
        result['comparison'] = [dict(width=after['width'], configuration=after['configuration'],
                                    before=before['steady_max'], after=after['steady_max'],
                                    reduction_percent=100*(1-after['steady_max']/before['steady_max']))
                                for before, after in zip(result['baseline']['cases'], result['current']['cases'])]
    root = HERE.parent
    result['source_sha256'] = {name: hashlib.sha256((root/name).read_bytes()).hexdigest()
                               for name in ('tools/sharc/glasshouse_audio.py',
                                            'tools/sharc/glasshouse_state.py',
                                            'src/sharc/glasshouse_math.asm')}
    text = json.dumps(result, indent=2)+'\n'
    if args.json:
        args.json.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
