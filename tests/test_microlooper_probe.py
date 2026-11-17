"""Encoded SHARC probe under its explicit caller ABI; no native stereo ABI claim."""
import functools
import random

import pytest

import microlooper as ml
import patch_amp
import ssim

STATE, INPUT, OUTPUT, RING = 0xb3000, 0xb8000, 0xb8100, 0x400000


@functools.lru_cache(None)
def code():
    p = ml.profile(3, metronome=True)
    return ml.assemble(p.place(ml.probe_instructions()))


class Probe:
    def __init__(self, frames=24):
        self.sim = ssim.Sim()
        self.sim.strict_cbufen = True
        sections, self.symbols = code()
        self.sim.load(sections)
        self.frames = frames
        self.setup(STATE, RING, frames)

    def setup(self, state, ring, frames):
        for offset in range(ml.STATE_WORDS):
            self.sim.wr(state + offset, 0)
        self.sim.wr(state, ring)
        self.sim.wr(state + 1, ring + frames * 2)
        self.sim.wr(state + 8, 1)
        for offset in range(-1, frames * 2 + 1):
            self.sim.wr(ring + offset, 0xdeadbeef)

    def call(self, samples=None, state=STATE, inplace=False):
        sim = self.sim
        samples = samples or [(k + .25, -k - .5) for k in range(16)]
        words = [ssim.f2b(x) for pair in samples for x in pair]
        for offset, word in enumerate(words):
            sim.wr(INPUT + offset, word)
        rng = random.Random(83)
        for r in range(16):
            sim.setR(r, rng.getrandbits(32))
            sim.alt[r] = rng.getrandbits(32)
        # Native ABI may use other pointers. This caller ABI deliberately supplies
        # interleaved stereo and must not be mistaken for host-dispatch evidence.
        for c in range(0x10, 0x50):
            sim.set(c, rng.randrange(1, 16) if 0x30 <= c < 0x40 else rng.randrange(0x100000))
        for c, value in ((0x10, state), (0x11, INPUT), (0x12, INPUT if inplace else OUTPUT)):
            sim.set(c, value)
        sim.u[ssim.U_MODE1] = 0x1600000  # RND32 plus SIMD/broadcast flags: kernel must clear/restore.
        before = ([sim.R(r) for r in range(16)], list(sim.alt[:16]),
                  [sim.get(c) for c in range(0x10, 0x50)], sim.u[ssim.U_MODE1])
        sim.call(self.symbols['MICROLOOPER_PROBE_ENTRY'], limit=5000)
        after = ([sim.R(r) for r in range(16)], list(sim.alt[:16]),
                 [sim.get(c) for c in range(0x10, 0x50)], sim.u[ssim.U_MODE1])
        assert after == before, 'probe clobbered caller registers'
        assert not sim.pcstk and not sim.loops
        out = INPUT if inplace else OUTPUT
        assert [sim.rd(out + k) for k in range(32)] == words, 'dry stereo passthrough changed samples'
        return words


@pytest.mark.parametrize('inplace', [False, True])
def test_records_stereo_without_changing_dry_audio_or_caller_state(inplace):
    p = Probe()
    words = p.call(inplace=inplace)
    assert [p.sim.rd(RING + k) for k in range(32)] == words
    assert p.sim.rd(STATE + 2) == 32
    assert p.sim.rd(STATE + 3) == 16
    assert p.sim.rd(STATE + 4) == 1
    assert p.sim.rd(STATE + 5) == 0
    for channel in (0, 1):
        digest = 0
        for k in range(channel, 32, 2):
            digest ^= words[k]
        assert p.sim.rd(STATE + 6 + channel) == digest


@pytest.mark.parametrize('frames', [1, 2, 16, 17, 24, ml.RING_FRAMES])
def test_ring_wraps_and_valid_count_saturates_without_crossing_guards(frames):
    p = Probe(frames)
    writes = []
    for block in range(4):
        writes += p.call([(block + k / 32, -block - k / 64) for k in range(16)])
    expected = [0xdeadbeef] * (frames * 2)
    for k, word in enumerate(writes):
        expected[k % len(expected)] = word
    assert [p.sim.rd(RING + k) for k in range(frames * 2)] == expected
    assert p.sim.rd(STATE + 2) == len(writes) % (frames * 2)
    assert p.sim.rd(STATE + 3) == min(64, frames)
    assert p.sim.rd(RING - 1) == p.sim.rd(RING + frames * 2) == 0xdeadbeef


def test_paused_probe_counts_calls_and_input_without_touching_ring():
    p = Probe()
    p.sim.wr(STATE + 8, 0)
    p.call([(1., 0.)] * 15 + [(2., 3.)])
    assert p.sim.rd(STATE + 4) == 1
    assert p.sim.rd(STATE + 6) != p.sim.rd(STATE + 7)
    assert p.sim.rd(STATE + 2) == p.sim.rd(STATE + 3) == 0
    assert all(p.sim.rd(RING + k) == 0xdeadbeef for k in range(48))


@pytest.mark.parametrize('offset,value', [(0, 0), (1, RING), (1, RING - 2),
                                         (1, RING + 47), (1, 0x4000001),
                                         (2, 48), (2, 0xffffffff), (2, 1)])
def test_bad_descriptor_is_dry_and_never_writes_ring(offset, value):
    p = Probe()
    p.sim.wr(STATE + offset, value)
    p.call()
    assert p.sim.rd(STATE + 5) == 1
    assert p.sim.rd(STATE + 3) == 0
    assert all(p.sim.rd(RING + k) == 0xdeadbeef for k in range(-1, 49))


def test_two_instances_own_separate_rings_and_counters():
    p = Probe()
    second_state, second_ring = STATE + 0x100, RING + 0x10000
    p.setup(second_state, second_ring, 24)
    first = p.call([(1., 2.)] * 16)
    second = p.call([(3., 4.)] * 16, state=second_state)
    assert [p.sim.rd(RING + k) for k in range(32)] == first
    assert [p.sim.rd(second_ring + k) for k in range(32)] == second
    assert p.sim.rd(STATE + 4) == p.sim.rd(second_state + 4) == 1


@pytest.mark.parametrize('slots,click,gr,free', [(3, False, False, 512), (3, True, False, 299),
                                               (2, False, False, 2528), (2, True, False, 2315),
                                               (2, True, True, 1077)])
def test_current_profiles_place_real_encoded_probe_without_overlap(slots, click, gr, free):
    p = ml.profile(slots, click, gr)
    assert p.block2_free_words == 4
    assert p.block3_free_words == free
    n = ml.probe_instructions()
    base = p.place(n)
    sections, _ = ml.assemble(base)
    assert [(s.kind, s.addr, len(s.words)) for s in sections] == [('pm', base, n)]
    assert ml.normal_word(base) >= p.block3_begin
    assert base + n + n % 2 <= p.block3_end_pm
    with pytest.raises(ValueError, match='does not fit'):
        p.place(free)
    with pytest.raises(ValueError, match='does not fit'):
        p.place(n, shared_dm_words=free)


def test_profile_rejects_unsupported_existing_combinations():
    with pytest.raises(ValueError, match='two NAM'):
        ml.profile(3, gr=True)
    with pytest.raises(ValueError, match='1, 2 or 3'):
        ml.profile(0)


def test_image_growth_matches_actual_ldr_encoding_and_reports_limit_separately():
    n = ml.probe_instructions()
    for instructions in (n, n + 1):
        encoded = patch_amp.pack_init_l48(0xe5000, [0] * instructions)
        report = ml.image_budget(521440, instructions)
        assert report['code_ldr_growth_bytes'] == len(encoded) * 4
        assert report['remaining_bytes'] == 0x80000 - 521440 - len(encoded) * 4
        assert report['fits_injection_guard']
    assert not ml.image_budget(0x80000, n)['fits_injection_guard']
