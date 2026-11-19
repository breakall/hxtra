"""Cache ADAA history without changing its binary32 transfer or small-delta path."""
from pathlib import Path

import numpy as np
import pytest

import sasm
import ssim
from glasshouse import reference
from sharc import glasshouse_audio as audio


# Independent uncached instruction sequence implementing the original softclip
# expression, using the unchanged log1p and reciprocal approximations. This
# lets the cache optimization require bit-identical output, not a wider oracle
# tolerance that could hide stale integral history.
UNCACHED = '''
gh_adaa_uncached:
    DM(20,I6) = F0;
    F1 = DM(4,I6);
    F2 = F0 - F1;
    DM(21,I6) = F2;
    F2 = ABS F2;
    F3 = 0.001;
    COMP(F2,F3);
    IF LT JUMP gh_uncached_midpoint;
    F0 = ABS F0;
    DM(22,I6) = F0;
    CALL gh_log1p;
    F1 = DM(22,I6);
    F0 = F1 - F0;
    DM(22,I6) = F0;
    F0 = DM(4,I6);
    F0 = ABS F0;
    DM(23,I6) = F0;
    CALL gh_log1p;
    F1 = DM(23,I6);
    F0 = F1 - F0;
    F1 = DM(22,I6);
    F1 = F1 - F0;
    DM(23,I6) = F1;
    F0 = DM(21,I6);
    CALL gh_recip;
    F1 = DM(23,I6);
    F0 = F1 * F0;
    JUMP gh_uncached_done;
gh_uncached_midpoint:
    F0 = F0 + F1;
    F1 = 0.5;
    F0 = F0 * F1;
    DM(22,I6) = F0;
    F0 = ABS F0;
    F1 = 1.0;
    F0 = F1 + F0;
    CALL gh_recip;
    F1 = DM(22,I6);
    F0 = F1 * F0;
gh_uncached_done:
    R1 = DM(20,I6);
    DM(4,I6) = R1;
    RTS;
'''


class Clip:
    def __init__(self, *, cached=True):
        math_source = (Path(__file__).parents[1] / 'src/sharc/glasshouse_math.asm').read_text()
        sections, self.symbols = sasm.assemble('.section pm 0xe3000\n'+math_source+'\n'+UNCACHED,
                                               'glasshouse_clip_comparison.asm')
        self.sim = ssim.Sim()
        self.sim.load(sections)
        self.state, self.channel = 0xb3000, 0xb3080
        self.entry = self.symbols['GH_ADAA' if cached else 'GH_ADAA_UNCACHED']
        self.sim.set(0x10, self.state)
        self.sim.set(0x16, self.channel)
        self.sim.set(ssim.U_MODE1, 0x10000 | ssim.CBUFEN)
        self.log_calls = 0
        step = self.sim.step
        def tracked_step():
            if self.sim.pc == self.symbols['GH_LOG1P']:
                self.log_calls += 1
            return step()
        self.sim.step = tracked_step
        write = self.sim.wr
        def bounded_write(address, word):
            assert (address == self.channel+4
                    or self.channel+18 <= address < self.channel+24
                    or self.state+384 <= address <= self.state+390)
            write(address, word)
        self.sim.wr = bounded_write

    def process(self, value):
        self.sim.set(0, ssim.f2b(value))
        before, calls = self.sim.cycles, self.log_calls
        self.sim.call(self.entry, limit=1000)
        return self.sim.get(0), self.log_calls-calls, self.sim.cycles-before


def compare_sequence(values):
    cached, uncached = Clip(), Clip(cached=False)
    details = []
    for value in values:
        a, count, instructions = cached.process(value)
        b, original_count, original_instructions = uncached.process(value)
        assert a == b
        assert cached.sim.rd(cached.channel+4) == ssim.f2b(value)
        details.append((count, instructions, original_count, original_instructions))
    return cached, details


def test_large_delta_cache_halves_log_calls_with_bit_identical_audio(monkeypatch):
    monkeypatch.setattr(ssim, 'RECIPS_HW', True)
    values = [.2, -.4, 1.2, -.8, 4., -3., 10., -20.]*8
    _, rows = compare_sequence(values)
    assert sum(row[0] for row in rows) == len(values)+1
    assert sum(row[2] for row in rows) == 2*len(values)
    assert sum(row[1] for row in rows) < sum(row[3] for row in rows)*.8


def test_small_delta_never_adds_logs_and_invalidates_only_changed_history():
    values = [0., .0001, .0002, .2, .2, .2005, .5, .5, .5]
    engine, rows = compare_sequence(values)
    assert [row[0] for row in rows] == [0, 0, 0, 2, 0, 0, 2, 0, 0]
    assert engine.sim.rd(engine.channel+19) == 1


@pytest.mark.parametrize('threshold', [np.nextafter(np.float32(.001), np.float32(0)),
                                     np.float32(.001),
                                     np.nextafter(np.float32(.001), np.float32(1))])
def test_zero_crossings_and_delta_boundary_preserve_original_branch(threshold):
    _, rows = compare_sequence([0., threshold, -threshold, 0., -0., 1., -1., 1000., -1000.])
    assert rows[1][0] == (0 if threshold < np.float32(.001) else 2)


def test_cached_adaa_preserves_hot_registers_and_address_generators():
    engine = Clip()
    untouched = [*range(6, 16), *range(0x10, 0x60), ssim.U_MODE1]
    for code in untouched:
        if code not in (0x10, 0x16, ssim.U_MODE1):
            engine.sim.set(code, 0x123000+code)
    # B-register setup also writes I; reestablish the two intended pointers.
    engine.sim.set(0x10, engine.state)
    engine.sim.set(0x16, engine.channel)
    engine.sim.set(0x30, 0)
    engine.sim.set(0x36, 0)
    expected = {code: engine.sim.get(code) for code in untouched}
    for value in (.3, -.6, -.5998, -.5998, 1.):
        engine.process(value)
        assert {code: engine.sim.get(code) for code in untouched} == expected


def test_cached_and_invalidated_sustained_drive_remain_bit_identical(monkeypatch):
    monkeypatch.setattr(ssim, 'RECIPS_HW', True)
    values = [np.float32(3.2*np.sin(i*.073)) for i in range(256)]
    # The plateau retains the integral; the tiny ramp invalidates it without
    # computing log1p, then a large jump must calculate a fresh previous value.
    values += [values[-1]]*10+[np.float32(values[-1]+i*.0001) for i in range(8)]+[-2., 2.]
    _, rows = compare_sequence(values)
    assert sum(row[0] for row in rows) < sum(row[2] for row in rows)*.6


@pytest.fixture(scope='module')
def oracle(tmp_path_factory):
    return reference.build_reference(tmp_path_factory.mktemp('glasshouse-drive-reference'))


def test_drive_off_on_pulse_retains_history_and_matches_original_source(oracle, monkeypatch):
    monkeypatch.setattr(ssim, 'RECIPS_HW', True)
    knobs = [list(page) for page in reference.KNOBS]
    toggles = [list(page) for page in reference.TOGGLES]
    knobs[0] = [.8, .55, .85, .2, .5, .2]
    knobs[2][4] = 1.
    toggles[2][0] = 1  # stereo program, separate left/right clip histories
    frames = np.asarray([(((i*37) % 127-63)/90, ((i*19) % 113-56)/80)
                         for i in range(192)], dtype=np.float32)
    engine = audio.Audio(channels=2)
    engine.settings(knobs, toggles)
    commands = [reference.settings(knobs, toggles, reset=True), reference.switch('enable', True)]
    actual = []
    def render(part):
        for first in range(0, len(part), 16):
            actual.extend(engine.block(part[first:first+16], inplace=first % 32 == 0))
        commands.append(reference.process(part))
    render(frames[:64])
    locations = [engine.state+128+32*channel+offset for channel in range(2) for offset in (4, 18, 19)]
    history = [engine.sim.rd(address) for address in locations]
    knobs[2][4] = 0.
    engine.settings(knobs, toggles)
    commands.append(reference.settings(knobs, toggles))
    render(frames[64:128])
    assert [engine.sim.rd(address) for address in locations] == history
    knobs[2][4] = 1.
    engine.settings(knobs, toggles)
    commands.append(reference.settings(knobs, toggles))
    render(frames[128:])
    expected = reference.run(oracle, *commands)
    error = float(np.max(np.abs(np.asarray(actual)-expected)))
    assert np.isfinite(actual).all()
    assert error <= 1.e-4
