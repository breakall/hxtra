"""Run encoded Glasshouse callbacks through the supplied firmware's C caller."""
import os
import random

import pytest

import kit_patch_amp as kit
import glasshouse_init as native
import microlooper_visa as visa
import ssim
from glasshouse_definition import (EFFECT, MONO_EFFECT, PARAMETER_BY_PID,
                                   PARAMETER_BASE, FLOAT_BOOLS)

STATE, INSTANCE, VALUE = 0xb3000, 0xb6000, 0xb7000
STACK, FRAME = 0xc6d98, 0xc6e98


@pytest.fixture(scope='module')
def firmware():
    path = os.environ.get('HX_STOMP_HXF')
    if not path:
        pytest.skip('HX_STOMP_HXF is not set')
    image, _ = kit.load_l6ia_from_any(path)
    entry = kit.l6ia.parse(image)[2]
    return image[entry['payload_off']:entry['payload_off'] + entry['payload_len']]


def setup(firmware):
    sim, short = visa.load(firmware, parcel_order='high-first', external_parcel_order='low-first')
    sections, symbols = native.assemble(0xe5000)
    sim.load(sections)
    sim.strict_cbufen = True
    rng = random.Random(166)
    for code in range(0x60):
        sim.set(code, rng.getrandbits(32))
    for code, value in ((0x25, 0), (0x26, 1), (0x27, 0xffffffff),
                        (0x2d, 0), (0x2e, 1), (0x2f, 0xffffffff),
                        (0x37, 0), (0x16, FRAME), (0x17, STACK)):
        sim.set(code, value)
    sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x10000
    sim.wr(INSTANCE, STATE)
    return sim, short, symbols


def invoke(sim, short, symbols, *, channels=None, pid=16, value=0, instance=INSTANCE):
    sim.set(0x16, FRAME)
    sim.set(0x17, STACK)
    sim.set(4, instance if channels else pid)
    sim.set(8, VALUE)
    sim.set(12, instance)
    sim.wr(VALUE, value)
    preserved = [code for code in range(0x60) if code not in (0, 1, 2, 4, 8, 12, 0x14, 0x1c)]
    before = [sim.get(code) for code in preserved]
    mode1, pc_stack, loops = sim.get(ssim.U_MODE1), list(sim.pcstk), list(sim.loops)
    entry = (MONO_EFFECT.callbacks.init if channels == 1 else native.INIT_ENTRY) if channels else native.CONTROL_ENTRY
    native.invoke_from_stock_c_caller(sim, short, symbols[entry], limit=160)
    assert [sim.get(code) for code in preserved] == before
    assert sim.get(ssim.U_MODE1) == mode1
    assert sim.pcstk == pc_stack and sim.loops == loops
    assert sim.pc == native.RETURN_SITE
    assert sim.get(0) == 0


@pytest.mark.parametrize('effect', (EFFECT, MONO_EFFECT))
def test_registry_has_native_callbacks_and_declared_payload(effect):
    _, symbols = native.assemble(0xe5000)
    assert native.registry(effect.primitive, 0x220000, 0xe5000, effect=effect) == [
        effect.primitive, symbols[effect.callbacks.init], 0, 0,
        symbols[native.CONTROL_ENTRY], 0x220000, 512, 0]
    with pytest.raises(ValueError, match='primitive'):
        native.registry(0, 0x220000, 0xe5000, effect=effect)
    for bad in (-2, 1, True):
        with pytest.raises(ValueError):
            native.assemble(bad)


@pytest.mark.firmware
@pytest.mark.parametrize('channels', (1, 2))
def test_dirty_init_sets_complete_source_defaults_and_preserves_framework(firmware, channels):
    sim, short, symbols = setup(firmware)
    before = [0x5a000000 + i for i in range(native.STATE_WORDS)]
    for i, word in enumerate(before):
        sim.wr(STATE + i, word)
    sim.wr(STATE - 1, 0xdeadbeef)
    sim.wr(STATE + native.STATE_WORDS, 0xdeadbeef)
    invoke(sim, short, symbols, channels=channels)
    expected = list(before)
    expected[4], expected[5] = 0, channels
    expected[6], expected[7] = 0, 0
    expected[16:55] = native.default_words()
    assert [sim.rd(STATE + i) for i in range(native.STATE_WORDS)] == expected
    assert sim.rd(STATE - 1) == sim.rd(STATE + native.STATE_WORDS) == 0xdeadbeef


@pytest.mark.firmware
def test_every_declared_control_reaches_its_instance_word_with_native_types(firmware):
    sim, short, symbols = setup(firmware)
    invoke(sim, short, symbols, channels=2)
    for pid, parameter in PARAMETER_BY_PID.items():
        raw = ssim.f2b(.875) if parameter.type == 3 else int(parameter.maximum)
        expected = ssim.f2b(raw) if pid - PARAMETER_BASE in FLOAT_BOOLS else raw
        before = [sim.rd(STATE + i) for i in range(native.STATE_WORDS)]
        invoke(sim, short, symbols, pid=pid, value=raw)
        before[pid] = expected
        assert [sim.rd(STATE + i) for i in range(native.STATE_WORDS)] == before


@pytest.mark.firmware
def test_invalid_pid_never_dereferences_value_or_descriptor(firmware):
    sim, short, symbols = setup(firmware)
    for pid in (0, 15, 33, 55, 0xffffffff):
        reads, read = [], sim.rd
        def logged(address):
            reads.append(address)
            return read(address)
        sim.rd = logged
        invoke(sim, short, symbols, pid=pid, instance=0, value=0xffffffff)
        sim.rd = read
        assert set(reads) == {STACK, STACK - 1}


@pytest.mark.firmware
def test_invalid_values_cannot_poison_audio_or_read_the_instance_descriptor(firmware):
    sim, short, symbols = setup(firmware)
    for pid, raw in ((16, 0x7fc00000), (16, 0x7f800000), (16, 0xbf800000),
                     (16, ssim.f2b(1.01)), (30, 2), (40, 3), (52, 2), (54, 0xffffffff)):
        reads, read = [], sim.rd
        def logged(address):
            reads.append(address)
            return read(address)
        sim.rd = logged
        invoke(sim, short, symbols, pid=pid, value=raw, instance=0)
        sim.rd = read
        assert set(reads) == {VALUE, STACK, STACK - 1}


@pytest.mark.firmware
def test_negative_zero_is_a_valid_normalized_native_float(firmware):
    sim, short, symbols = setup(firmware)
    invoke(sim, short, symbols, channels=2)
    invoke(sim, short, symbols, pid=16, value=0x80000000)
    assert sim.rd(STATE + 16) == 0x80000000


@pytest.mark.firmware
def test_control_and_reinitialization_are_per_instance(firmware):
    sim, short, symbols = setup(firmware)
    other, descriptor = STATE + 0x400, INSTANCE + 0x100
    sim.wr(descriptor, other)
    invoke(sim, short, symbols, channels=1)
    invoke(sim, short, symbols, channels=2, instance=descriptor)
    invoke(sim, short, symbols, pid=17, value=ssim.f2b(.9))
    invoke(sim, short, symbols, pid=53, value=1, instance=descriptor)
    assert sim.rd(STATE + 17) == ssim.f2b(.9)
    assert sim.rd(other + 17) == native.default_words()[1]
    assert sim.rd(STATE + 53) == 0 and sim.rd(other + 53) == 1
    invoke(sim, short, symbols, channels=2, instance=descriptor)
    assert sim.rd(STATE + 17) == ssim.f2b(.9)
    assert sim.rd(other + 53) == 0


@pytest.mark.firmware
def test_live_aux_and_enable_edges_latch_across_multiple_control_deliveries(firmware):
    sim, short, symbols = setup(firmware)
    invoke(sim, short, symbols, channels=2)
    sim.wr(STATE + 4, 1)
    sim.wr(STATE + 47, 1)  # manual swell at the time of the Aux press
    invoke(sim, short, symbols, pid=52, value=1)
    invoke(sim, short, symbols, pid=52, value=0)
    assert sim.rd(STATE + 6) == 1 and sim.rd(STATE + 52) == 0
    invoke(sim, short, symbols, pid=54, value=0)
    invoke(sim, short, symbols, pid=54, value=1)
    assert sim.rd(STATE + 7) == 1 and sim.rd(STATE + 54) == 1
    # Further same-high deliveries do not create a new edge after consumption.
    sim.wr(STATE + 7, 0)
    invoke(sim, short, symbols, pid=54, value=1)
    assert sim.rd(STATE + 7) == 0


@pytest.mark.firmware
def test_constructor_and_nonmanual_aux_delivery_cannot_latch_a_manual_dip(firmware):
    sim, short, symbols = setup(firmware)
    invoke(sim, short, symbols, channels=2)
    sim.wr(STATE + 47, 1)
    invoke(sim, short, symbols, pid=52, value=1)
    assert sim.rd(STATE + 6) == 0
    sim.wr(STATE + 4, 1)
    sim.wr(STATE + 47, 0)
    invoke(sim, short, symbols, pid=52, value=0)
    invoke(sim, short, symbols, pid=52, value=1)
    assert sim.rd(STATE + 6) == 0
