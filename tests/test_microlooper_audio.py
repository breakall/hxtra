"""Encoded mono/stereo audio against the independent C++ oracle."""
from pathlib import Path
import random
import shutil
import subprocess

import numpy as np
import pytest

import microlooper_audio as audio
import ssim

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def oracle(tmp_path_factory):
    compiler=shutil.which('clang++') or shutil.which('g++')
    if not compiler: pytest.skip('C++ compiler required for differential oracle')
    exe=tmp_path_factory.mktemp('looper-audio')/'vectors'
    subprocess.run([compiler,'-std=c++17','-O1','-ffp-contract=off','-I',str(ROOT/'tools'),
                    str(ROOT/'tests/microlooper_vectors.cpp'),'-o',str(exe)],check=True,capture_output=True)
    return exe


def input_at(i):
    return (((i*37)%127-63)/256, ((i*19)%113-56)/256)


@pytest.mark.parametrize('mode', [0,1,2])
@pytest.mark.parametrize('clock', [1.,.5,0.])
@pytest.mark.parametrize('modify', [.1875,.8125])
def test_encoded_kernel_matches_reference_modes_clocks_and_signed_rates(oracle, mode, clock, modify):
    capture,playback=64,256
    expected=np.frombuffer(subprocess.check_output([str(oracle),str(mode),str(clock),str(modify),str(capture),str(playback)]),np.float32).reshape(-1,2)
    a=audio.Audio();a.params(mode=mode,clock=clock,modify=modify,length=.63,mix=.8)
    actual=[]
    for first in range(0,capture+playback,16):
        if first==capture:a.params(play=True)
        if first==capture+64:a.params(overdub=True)
        if first==capture+128:a.params(overdub=False)
        actual.extend(a.block([input_at(i) for i in range(first,first+16)]))
    np.testing.assert_allclose(actual,expected,atol=2e-6,rtol=0)


@pytest.mark.parametrize("channels", [1, 2])
def test_private_storage_guards_and_registers_are_preserved(channels):
    a=audio.Audio(channels=channels);sim=a.sim
    sim.wr(a.ring-1,0xdeadbeef);sim.wr(a.ring+a.ring_words,0xfeedface)
    rng=random.Random(44)
    for r in range(16):sim.setR(r,rng.getrandbits(32));sim.alt[r]=rng.getrandbits(32)
    for c in range(0x10,0x50):sim.set(c, rng.randrange(1,16) if 0x30<=c<0x40 else rng.randrange(0x100000))
    # Driver resets only the declared argument registers.
    sim.set(0x10,a.state);sim.set(0x11,0xb8000);sim.set(0x12,0xb8100)
    sim.u[ssim.U_MODE1]=0x1608000
    before=([sim.R(r)for r in range(16)],list(sim.alt),[sim.get(c)for c in range(0x10,0x50)],sim.u[ssim.U_MODE1])
    a.block([.125]*16 if channels==1 else [(.125,-.25)]*16)
    after=([sim.R(r)for r in range(16)],list(sim.alt),[sim.get(c)for c in range(0x10,0x50)],sim.u[ssim.U_MODE1])
    assert before==after
    assert sim.rd(a.ring-1)==0xdeadbeef and sim.rd(a.ring+a.ring_words)==0xfeedface


@pytest.mark.parametrize('badbegin,badend', [(0,48000),(0x400000,0x400002),(0x400000,0x4000001)])
def test_invalid_allocation_passes_dry_without_ring_writes(badbegin,badend):
    a=audio.Audio();a.sim.wr(a.state+12,badbegin);a.sim.wr(a.state+13,badend)
    samples=[(.125,-.25)]*16
    assert a.block(samples)==samples
    assert a.sim.rd(a.state+48)==1


def test_two_instances_do_not_share_histories():
    first=audio.Audio();second=audio.Audio(state=0xb4000,ring=0x420000,sim=first.sim)
    for _ in range(4):first.block([(.25,0.)]*16);second.block([(0.,-.125)]*16)
    assert first.sim.rd(first.ring)==ssim.f2b(.25)
    assert first.sim.rd(second.ring+1)==ssim.f2b(-.125)
    assert first.sim.rd(first.ring+1)==first.sim.rd(second.ring)==0


def test_full_ring_wrap_has_no_unbounded_initialization():
    a=audio.Audio();a.block()
    a.sim.wr(a.state+21,23992);a.sim.wr(a.state+22,23992)
    a.sim.wr(a.ring-1,0x1234);a.sim.wr(a.ring+audio.RING_WORDS,0x5678)
    a.block([(.5,-.5)]*16,inplace=True)
    assert a.sim.rd(a.state+21)==8
    assert a.sim.rd(a.state+22)==24000
    assert a.sim.rd(a.ring-1)==0x1234 and a.sim.rd(a.ring+audio.RING_WORDS)==0x5678


@pytest.mark.parametrize('mode,clock', [(0,1.), (1,.5), (2,0.)])
def test_parameter_changes_and_partial_recapture_match_reference(oracle,mode,clock):
    capture,playback,modify=128,320,.8125
    expected=np.frombuffer(subprocess.check_output([str(oracle),str(mode),str(clock),str(modify),str(capture),str(playback),'changes']),np.float32).reshape(-1,2)
    a=audio.Audio();a.params(mode=mode,clock=clock,modify=modify,length=.63,mix=.8)
    actual=[]
    for first in range(0,capture+playback,16):
        if first==capture:a.params(play=True)
        if first==capture+32:a.params(length=.05)
        if first==capture+64:a.params(overdub=True)
        if first==capture+80:a.params(mode=(mode+1)%3)
        if first==capture+128:a.params(overdub=False,clock=1-clock)
        if first==capture+160:a.params(play=False)
        if first==capture+192:a.params(play=True)
        actual.extend(a.block([input_at(i) for i in range(first,first+16)]))
    np.testing.assert_allclose(actual,expected,atol=2e-6,rtol=0)


@pytest.mark.parametrize('mode', [0,1,2])
def test_hardware_reciprocal_seed_refines_to_reference_accuracy(oracle,monkeypatch,mode):
    monkeypatch.setattr(ssim,'RECIPS_HW',True)
    capture,playback,modify=96,256,.1875
    expected=np.frombuffer(subprocess.check_output([str(oracle),str(mode),'1',str(modify),str(capture),str(playback)]),np.float32).reshape(-1,2)
    a=audio.Audio();a.params(mode=mode,clock=1,modify=modify,length=.63,mix=.8)
    actual=[]
    for first in range(0,capture+playback,16):
        if first==capture:a.params(play=True)
        if first==capture+64:a.params(overdub=True)
        if first==capture+128:a.params(overdub=False)
        actual.extend(a.block([input_at(i) for i in range(first,first+16)]))
    np.testing.assert_allclose(actual,expected,atol=2e-6,rtol=0)


def test_empty_capture_after_reset_never_reads_stale_recording():
    a=audio.Audio();a.block([(.5,.25)]*16);a.params(play=True)
    a.block();a.sim.wr(a.state+audio.INITIALIZED,0)
    # Graph initializer owns restoring transport. A saved Play state also must
    # never expose the old audio when valid history is empty.
    a.params(play=True,mix=1)
    for _ in range(16):
        assert a.block()==[(0.,0.)]*16


@pytest.mark.parametrize('mode', [0,1,2])
def test_wrapped_full_capture_matches_reference(oracle,mode):
    # Nonzero physical start, full24k history and seam reads in both channels.
    capture,playback,modify=24032,512,.1875
    expected=np.frombuffer(subprocess.check_output([str(oracle),str(mode),'1',str(modify),str(capture),str(playback)]),np.float32).reshape(-1,2)
    a=audio.Audio();a.params(mode=mode,clock=1,modify=modify,length=.63,mix=.8)
    actual=[]
    for first in range(0,capture+playback,16):
        if first==capture:a.params(play=True)
        if first==capture+64:a.params(overdub=True)
        if first==capture+128:a.params(overdub=False)
        actual.extend(a.block([input_at(i) for i in range(first,first+16)]))
    np.testing.assert_allclose(actual,expected,atol=2e-6,rtol=0)


def test_wrap_helper_is_float32_fmod_not_rounded_quotient_subtraction():
    import math
    rng = random.Random(37)
    pairs = [(23000.123046875, 48.000030517578125),
             (20000.125, 107.99749755859375),
             (-23000.123046875, 48.000030517578125),
             (-4., .875), (-0., 1.), (24000., 24000.)]
    pairs += [(rng.uniform(-48000,48000), rng.uniform(.875,24000)) for _ in range(200)]
    a = audio.Audio()
    for position, extent in pairs:
        position,extent = map(lambda x:ssim.b2f(ssim.f2b(x)),(position,extent))
        expected = ssim.b2f(ssim.f2b(math.fmod(position,extent)))
        if expected < 0: expected = ssim.b2f(ssim.f2b(expected+extent))
        a.sim.wr(a.state+76,ssim.f2b(position)); a.sim.wr(a.state+77,ssim.f2b(extent))
        a.sim.set(0x10,a.state)
        a.sim.call(a.symbols['ML_WRAP'],limit=1000)
        assert a.sim.rd(a.state+78)==ssim.f2b(expected), (position,extent)


def test_full_capture_long_envelope_play_then_noninteger_slice_shrink(oracle):
    capture,playback,modify = 24032,23136,.8125
    expected=np.frombuffer(subprocess.check_output([str(oracle),'0','1',str(modify),str(capture),str(playback),'shrink']),np.float32).reshape(-1,2)
    a=audio.Audio();a.params(mode=0,clock=1,modify=modify,length=1,mix=.8)
    actual=[]
    for first in range(0,capture+playback,16):
        if first==capture:a.params(play=True)
        if first==capture+23008:a.params(length=.0000374)
        actual.extend(a.block([input_at(i) for i in range(first,first+16)]))
    np.testing.assert_allclose(actual,expected,atol=2e-6,rtol=0)


def test_stale_overdub_high_cannot_activate_after_capture_or_resume(oracle):
    capture,playback = 64,320
    expected=np.frombuffer(subprocess.check_output([str(oracle),'1','1','.75',str(capture),str(playback),'stale']),np.float32).reshape(-1,2)
    a=audio.Audio();a.params(mode=1,clock=1,modify=.75,length=.63,mix=.8)
    actual=[]
    for first in range(0,capture+playback,16):
        if first==capture:a.params(play=True)
        if first in (32,capture+32,capture+96,capture+112,capture+208):a.params(overdub=True)
        if first in (capture+64,capture+192):a.params(overdub=False)
        if first==capture+128:a.params(play=False)
        if first==capture+160:a.params(play=True)
        actual.extend(a.block([(0.,0.) if i<capture else (.25,.125) for i in range(first,first+16)]))
        if first in (capture,capture+32,capture+64,capture+128,capture+160,capture+192):
            assert a.sim.rd(a.state+audio.EFFECTIVE_OVERDUB)==0
        if first in (capture+96,capture+112,capture+208):
            assert a.sim.rd(a.state+audio.EFFECTIVE_OVERDUB)==1
    np.testing.assert_allclose(actual,expected,atol=2e-6,rtol=0)


@pytest.mark.parametrize('modify,expected', [(0.,-4.),(.1875,-2.),(.3125,-1.),
                                           (.4375,-.5),(.5625,.5),(.6875,1.),
                                           (.8125,2.),(.9375,4.),(1.,4.)])
def test_all_tape_rate_zones_use_exact_signed_powers_of_two(modify,expected):
    a=audio.Audio();a.params(mode=1,modify=modify);a.block()
    assert a.sim.rd(a.state+61)==ssim.f2b(expected)


def test_restored_initial_play_high_stays_listening_until_low_arms_capture():
    a=audio.Audio();a.params(play=True,overdub=True,mix=1)
    samples=[(.25,-.125)]*16
    for _ in range(3):
        assert a.block(samples)==samples
        assert a.sim.rd(a.state+audio.PLAYING)==0
        assert a.sim.rd(a.state+audio.PLAY_ARMED)==0
        assert a.sim.rd(a.state+audio.EFFECTIVE_OVERDUB)==0
    assert a.sim.rd(a.state+audio.RECORDED)==48
    a.params(play=False);a.block(samples)
    assert a.sim.rd(a.state+audio.PLAY_ARMED)==1
    a.params(play=True);a.block()
    assert a.sim.rd(a.state+audio.PLAYING)==1
    assert a.sim.rd(a.state+audio.EFFECTIVE_OVERDUB)==0
    # Reusing the instance DM allocation must reset the private arming epoch.
    a.sim.wr(a.state+audio.INITIALIZED,0)
    a.block(samples)
    assert a.sim.rd(a.state+audio.PLAYING)==0
    assert a.sim.rd(a.state+audio.PLAY_ARMED)==0


@pytest.mark.parametrize('mode', [0, 1, 2])
@pytest.mark.parametrize('clock', [1., .5, 0.])
@pytest.mark.parametrize('modify', [.1875, .8125])
def test_mono_kernel_matches_single_channel_reference(oracle, mode, clock, modify):
    capture, playback = 64, 256
    expected = np.frombuffer(subprocess.check_output([
        str(oracle), str(mode), str(clock), str(modify), str(capture),
        str(playback), 'steady', '1']), np.float32).reshape(-1, 2)[:, 0]
    a = audio.Audio(channels=1)
    a.params(mode=mode, clock=clock, modify=modify, length=.63, mix=.8)
    actual = []
    for first in range(0, capture + playback, 16):
        if first == capture: a.params(play=True)
        if first == capture + 64: a.params(overdub=True)
        if first == capture + 128: a.params(overdub=False)
        actual.extend(a.block([input_at(i)[0] for i in range(first, first + 16)]))
    np.testing.assert_allclose(actual, expected, atol=2e-6, rtol=0)
    assert a.sim.rd(a.state + audio.CHANNELS) == 1


@pytest.mark.parametrize('mode', [0, 1, 2])
@pytest.mark.parametrize('inplace', [False, True])
def test_mono_never_accesses_right_plane_or_exceeds_its_ring(monkeypatch, mode, inplace):
    a = audio.Audio(channels=1)
    a.params(mode=mode, mix=1, modify=.1875)
    sim, ring_end = a.sim, a.ring + a.ring_words
    # A forbidden virtual right plane catches reads as well as writes, including
    # in-place output. Ring guards are equally strict on either side.
    forbidden = {a.ring-1, ring_end}
    forbidden.update(range(0xb8000+16, 0xb8000+32))
    forbidden.update(range(0xb8100+16, 0xb8100+32))
    read, write = sim.rd, sim.wr
    def rd(address):
        assert address not in forbidden
        assert not 0x200000 <= address < 0x4000000 or a.ring <= address < ring_end
        return read(address)
    def wr(address, value):
        assert address not in forbidden
        assert not 0x200000 <= address < 0x4000000 or a.ring <= address < ring_end
        write(address, value)
    monkeypatch.setattr(sim, 'rd', rd)
    monkeypatch.setattr(sim, 'wr', wr)
    a.block([.25]*16, inplace=inplace)
    sim.wr(a.state + audio.WRITE, 23992)
    sim.wr(a.state + audio.RECORDED, 23992)
    a.block([-.25]*16, inplace=inplace)
    assert sim.rd(a.state + audio.WRITE) == 8
    assert sim.rd(a.state + audio.RECORDED) == 24000
    a.params(play=True)
    for block in range(24):
        if block == 2: a.params(overdub=True)
        if block == 10: a.params(overdub=False, mode=(mode+1)%3, clock=.5)
        if block == 14: a.params(play=False)
        if block == 18: a.params(play=True)
        assert len(a.block([.125]*16, inplace=inplace)) == 16
    assert sim.rd(a.state + audio.ERRORS) == 0


@pytest.mark.parametrize('inplace', [False, True])
def test_mono_invalid_ring_is_exactly16_dry_words(monkeypatch, inplace):
    a = audio.Audio(channels=1)
    a.sim.wr(a.state + audio.RING_END, a.ring + a.ring_words - 1)
    source = [frame/32 for frame in range(16)]
    forbidden = set(range(0xb8000+16, 0xb8000+32)) | set(range(0xb8100+16, 0xb8100+32))
    read, write = a.sim.rd, a.sim.wr
    def rd(address):
        assert address not in forbidden and not a.ring <= address < a.ring+a.ring_words
        return read(address)
    def wr(address, value):
        assert address not in forbidden and not a.ring <= address < a.ring+a.ring_words
        write(address, value)
    monkeypatch.setattr(a.sim, 'rd', rd)
    monkeypatch.setattr(a.sim, 'wr', wr)
    assert a.block(source, inplace=inplace) == source
    assert a.sim.rd(a.state + audio.ERRORS) == 1
