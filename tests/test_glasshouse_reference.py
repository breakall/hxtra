"""Pinned original Glasshouse behavior and the independent vector transport."""
import hashlib
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from glasshouse import reference

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def oracle(tmp_path_factory):
    return reference.build_reference(tmp_path_factory.mktemp('glasshouse-reference'), sanitize=True)


def test_reference_is_the_original_source():
    expected = {
        'reference.h': 'dae96bbe2a5fe30f668ba0e6304795bcb720a75fb3e81103d6351b650e089c47',
        'settings.h': 'f9b94f83a5c08c3e43e78eee66b9bc92ceec3d6c2130f3bc27bace87229ef891',
    }
    for name, digest in expected.items():
        assert hashlib.sha256((ROOT / 'tools/glasshouse' / name).read_bytes()).hexdigest() == digest


def test_original_audio_regressions(tmp_path):
    compiler = shutil.which('clang++') or shutil.which('c++')
    executable = tmp_path / 'glasshouse-source-tests'
    subprocess.run([compiler, '-std=c++14', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-ffp-contract=off', '-I', str(ROOT / 'tools'),
                    str(ROOT / 'tests/glasshouse_source_tests.cpp'), '-o', str(executable)],
                   capture_output=True, check=True, timeout=90)
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS (' in result.stdout
    assert 'gain wobble' not in result.stdout


def test_vector_transport_retains_stereo_bypass_and_enable_fade(oracle):
    knobs = [list(page) for page in reference.KNOBS]
    knobs[0] = [.125, 0, .5, 0, .5, 0]
    toggles = [list(page) for page in reference.TOGGLES]
    toggles[2][0] = 1
    frames = np.tile(np.array([.25, -.4], np.float32), (8192, 1))
    out = reference.run(oracle, reference.settings(knobs, toggles, reset=True),
                        reference.process(frames), reference.switch('enable', True),
                        reference.process(frames))
    np.testing.assert_allclose(out, np.tile(frames, (2, 1)), atol=1e-6)


def test_settings_and_momentary_sag_commands_preserve_both_smoothed_edges(oracle):
    knobs = [list(page) for page in reference.KNOBS]
    knobs[0] = [.5, 0, .5, 0, .5, 0]
    frames = np.full(192000, .2, np.float32)
    out = reference.run(oracle, reference.settings(knobs, reset=True),
                        reference.switch('enable', True), reference.process(frames),
                        reference.switch('sag', True), reference.process(frames),
                        reference.switch('sag', False), reference.process(frames),
                        reference.inspect())
    assert out[383999, 0] < .01
    assert out[575999, 0] > .19
    assert np.max(np.abs(np.diff(out[191999:576000, 0]))) < .001
    assert np.isfinite(out).all()


def test_malformed_reference_commands_are_rejected(oracle):
    result = subprocess.run([str(oracle)], input=b'\xff\x00\x00\x00', capture_output=True)
    assert result.returncode == 2
