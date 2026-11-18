"""Build and drive the unchanged C++ Glasshouse source, independently of SHARC."""
from pathlib import Path
import shutil
import struct
import subprocess

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
KNOBS = ((.42, .25, .5, .48, .5, 0),
         (.35, .5, .6, .5, .75, 0),
         (.6, .5, 0, 0, 0, 0),
         (0, 0, 0, 0, 0, 0))
TOGGLES = ((1, 1, 1), (1, 1, 0), (0, 0, 0), (0, 0, 0))


def build_reference(directory, *, sanitize=False):
    compiler = shutil.which('clang++') or shutil.which('c++')
    if compiler is None:
        raise RuntimeError('Glasshouse reference requires a C++14 compiler')
    executable = Path(directory) / 'glasshouse-reference'
    flags = ['-std=c++14', '-O2', '-Wall', '-Wextra', '-Werror', '-ffp-contract=off']
    if sanitize:
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    subprocess.run([compiler, *flags, '-I', str(ROOT / 'tools'),
                    str(ROOT / 'tests/glasshouse_reference.cpp'),
                    '-o', str(executable)], check=True, capture_output=True, timeout=90)
    return executable


def settings(knobs=KNOBS, toggles=TOGGLES, *, reset=False):
    """Encode source settings; reset also resets the engine at 48 kHz."""
    flat = [v for page in knobs for v in page]
    modes = [v for page in toggles for v in page]
    if len(flat) != 24 or len(modes) != 12:
        raise ValueError('Glasshouse settings require 24 knobs and 12 toggles')
    return (struct.pack('<If', 0, 48000.) if reset else struct.pack('<I', 1)) + struct.pack('<24f12I', *flat, *modes)


def switch(name, value):
    return struct.pack('<2I', {'enable': 2, 'aux': 3, 'sag': 4}[name], int(bool(value)))


def process(samples):
    frames = np.asarray(samples, dtype='<f4')
    if frames.ndim == 1:
        frames = np.column_stack((frames, frames))
    if frames.ndim != 2 or frames.shape[1] != 2:
        raise ValueError('source samples must be mono or stereo frame pairs')
    return struct.pack('<2I', 5, len(frames)) + frames.astype('<f4').tobytes()


def inspect():
    return struct.pack('<I', 6)


def run(executable, *commands):
    result = subprocess.run([str(executable)], input=b''.join(commands),
                            capture_output=True, check=True, timeout=90)
    return np.frombuffer(result.stdout, dtype='<f4').reshape(-1, 2).copy()
