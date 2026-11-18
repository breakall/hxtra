"""Encoded native C callbacks: allocation is separate from callback linkage."""
import math
import os
import random

import pytest

import kit_patch_amp as kit
import microlooper_bridge as bridge
import microlooper_init as native
import microlooper_visa as visa
import ssim
from microlooper_definition import EFFECT, MONO_EFFECT

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


def setup(firmware, state=STATE, instance=INSTANCE):
    sim, short = visa.load(firmware, parcel_order='high-first', external_parcel_order='low-first')
    sections, symbols = native.assemble(0xe5000)
    sim.load(sections)
    sim.strict_cbufen = True
    rng = random.Random(721)
    for code in range(0x60):
        sim.set(code, rng.getrandbits(32))
    for code, value in ((0x25, 0), (0x26, 1), (0x27, 0xffffffff),
                        (0x2d, 0), (0x2e, 1), (0x2f, 0xffffffff),
                        (0x37, 0),
                        (0x16, FRAME), (0x17, STACK)):
        sim.set(code, value)
    sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x10000  # native scalar C environment
    for j, value in enumerate((state, state + native.STATE_WORDS, state, 0, 0, 0,
                               0x400000, 0x400000 + native.SDRAM_WORDS, 0x400000)):
        sim.wr(instance + j, value)
    return sim, short, symbols


def invoke(sim, short, symbols, *, init=False, pid=5, value=0, instance=INSTANCE, channels=2):
    sim.set(0x16, FRAME)
    sim.set(0x17, STACK)
    sim.set(4, instance if init else pid)
    sim.set(8, VALUE)
    sim.set(12, instance)
    sim.wr(VALUE, value)
    # Verify all nonvolatile registers and every modifier/base/length, plus
    # exact caller frame restoration. Arithmetic flags are C-call volatile.
    preserved = [code for code in range(0x60) if code not in (0, 1, 2, 4, 8, 12, 0x14, 0x1c)]
    before = [sim.get(code) for code in preserved]
    mode1, pc_stack, loops = sim.get(ssim.U_MODE1), list(sim.pcstk), list(sim.loops)
    native.invoke_from_stock_c_caller(sim, short, symbols[('MICROLOOPER_INIT_MONO' if channels == 1 else native.INIT_ENTRY) if init else native.CONTROL_ENTRY])
    assert [sim.get(code) for code in preserved] == before
    assert sim.get(ssim.U_MODE1) == mode1
    assert sim.pcstk == pc_stack and sim.loops == loops
    assert sim.pc == native.RETURN_SITE
    assert sim.get(0) == 0  # deterministic status for both callbacks


@pytest.mark.parametrize('effect', [EFFECT, MONO_EFFECT])
def test_registry_uses_only_custom_callbacks_and_no_private_pm(effect):
    _, symbols = native.assemble(0xe5000)
    record = native.registry(effect.primitive, 0xe4000, 0xe5000, effect=effect)
    assert record == [effect.primitive, symbols[effect.callbacks.init], 0, 0,
                      symbols[native.CONTROL_ENTRY], 0xe4000, 163, 0]
    assert native.instructions() == 41
    for base in (-2, 1):
        with pytest.raises(ValueError):
            native.assemble(base)


@pytest.mark.firmware
@pytest.mark.parametrize("channels", [1, 2])
def test_init_resets_exactly_transport_and_marker_without_sdram_or_ir_globals(firmware, channels):
    sim, short, symbols = setup(firmware)
    before = [0x5a000000 + j for j in range(native.STATE_WORDS)]
    for j, value in enumerate(before):
        sim.wr(STATE + j, value)
    sim.wr(STATE - 1, 0xdeadbeef)
    sim.wr(STATE + native.STATE_WORDS, 0xdeadbeef)
    writes = []
    write = sim.wr
    def log(address, value):
        writes.append(address)
        write(address, value)
    sim.wr = log
    invoke(sim, short, symbols, init=True, channels=channels)
    expected = list(before)
    expected[14] = channels
    for offset in (10, 11, 15, 20):
        expected[offset] = 0
    assert [sim.rd(STATE + j) for j in range(native.STATE_WORDS)] == expected
    assert sim.rd(STATE - 1) == sim.rd(STATE + native.STATE_WORDS) == 0xdeadbeef
    assert set(writes) == {VALUE, STACK, STACK - 1, STATE + 10, STATE + 11, STATE + 14, STATE + 15, STATE + 20}


@pytest.mark.firmware
@pytest.mark.parametrize('pid', [*range(5, 12), 15])
@pytest.mark.parametrize('value', [0, 1, 0x3f000000, 0xbf800000, 0x7fc01234, 0xffffffff])
def test_control_stores_raw_word_only_in_requested_instance_parameter(firmware, pid, value):
    sim, short, symbols = setup(firmware)
    for j in range(native.STATE_WORDS):
        sim.wr(STATE + j, 0x5a000000 + j)
    before = [sim.rd(STATE + j) for j in range(native.STATE_WORDS)]
    writes = []
    write = sim.wr
    def log(address, word):
        writes.append(address)
        write(address, word)
    sim.wr = log
    invoke(sim, short, symbols, pid=pid, value=value)
    before[pid] = value
    assert [sim.rd(STATE + j) for j in range(native.STATE_WORDS)] == before
    assert set(writes) == {VALUE, STACK, STACK - 1, STATE + pid}


@pytest.mark.firmware
@pytest.mark.parametrize('pid', [0, 1, 4, 12, 13, 14, 16, 144, 199, 0xffffffff])
def test_invalid_control_id_returns_without_value_or_descriptor_dereference(firmware, pid):
    sim, short, symbols = setup(firmware)
    reads = []
    read = sim.rd
    def log(address):
        reads.append(address)
        return read(address)
    sim.rd = log
    invoke(sim, short, symbols, pid=pid, value=0x12345678, instance=0)
    assert set(reads) == {STACK, STACK - 1}


@pytest.mark.firmware
def test_two_instances_and_reinitialization_do_not_share_state(firmware):
    sim, short, symbols = setup(firmware)
    other, descriptor = STATE + 0x200, INSTANCE + 0x100
    sim.wr(descriptor, other)
    for base in (STATE, other):
        for j in range(native.STATE_WORDS):
            sim.wr(base + j, 0x5a000000 + j)
    invoke(sim, short, symbols, pid=6, value=0x3f123456)
    invoke(sim, short, symbols, init=True, instance=descriptor)
    assert sim.rd(STATE + 6) == 0x3f123456
    assert sim.rd(STATE + 20) == 0x5a000014
    assert sim.rd(other + 20) == sim.rd(other + 10) == sim.rd(other + 11) == 0
    assert sim.rd(other + 6) == 0x5a000006


def run_actual_dispatch(sim, short, start, stop):
    """No call target substitution: object/registry data select our callbacks."""
    sim.pc = start
    for _ in range(100):
        if sim.pc == stop:
            return
        pc = sim.pc
        if pc in short:
            visa.step(sim, visa.decode([short[pc + j] for j in range(3)]))
        else:
            sim.step()
    pytest.fail('actual native dispatcher exceeded instruction bound')


@pytest.mark.firmware
def test_actual_primitive_init_dispatcher_passes_descriptor_and_ignores_status(firmware):
    sim, short, symbols = setup(firmware)
    registry = 0xb8000
    for j, word in enumerate(native.registry(0x12e, 0xe4000, 0xe5000)):
        sim.wr(registry + j, word)
    sim.set(15, INSTANCE)  # retained original R4 at actual0x177a00
    sim.set(0x15, INSTANCE)
    sim.set(0x14, registry)
    for offset in (10, 11, 15, 20):
        sim.wr(STATE + offset, 0xffffffff)
    run_actual_dispatch(sim, short, 0x177a55, 0x177a8a)
    assert sim.get(4) == INSTANCE
    assert [sim.rd(STATE + offset) for offset in (10, 11, 15, 20)] == [0, 0, 0, 0]
    assert sim.rd(INSTANCE + 31) == symbols[native.INIT_ENTRY]
    assert sim.rd(INSTANCE + 32) == sim.rd(INSTANCE + 33) == 0x1779e7
    assert sim.rd(INSTANCE + 34) == symbols[native.CONTROL_ENTRY]
    assert sim.rd(INSTANCE + 35) == 0xe4000
    # The very next original instruction explicitly clears R0; the init
    # callback's returned value does not select a failure path here.
    next_instruction = visa.decode([short[sim.pc + j] for j in range(3)])
    sim.set(0, 0xdeadbeef)
    visa.step(sim, next_instruction)
    assert sim.get(0) == 0


@pytest.mark.firmware
@pytest.mark.parametrize('pid', [*range(5, 12), 15])
def test_actual_control_dispatcher_passes_pid_value_pointer_and_descriptor(firmware, pid):
    sim, short, symbols = setup(firmware)
    sim.wr(STATE + 20, 1)  # live instance: its first audio block has run
    record, raw = 0xb8000, 0x7fc01234
    sim.wr(record, pid)
    sim.wr(record + 1, raw)
    sim.wr(INSTANCE + 34, symbols[native.CONTROL_ENTRY])
    sim.set(1, record)
    sim.set(13, INSTANCE)
    sim.set(0x13, INSTANCE)
    sim.set(0x15, 0xb9000)  # unrelated preserved caller loop pointer
    run_actual_dispatch(sim, short, 0x178108, 0x17811d)
    assert sim.get(4) == pid
    assert sim.get(8) == record + 1
    assert sim.get(12) == INSTANCE
    assert sim.rd(STATE + pid) == raw
    assert sim.get(0) == 0


@pytest.mark.firmware
@pytest.mark.parametrize('pid', [10, 11, 15])
@pytest.mark.parametrize('value', [0, 1, 0xffffffff])
def test_unprocessed_instance_discards_transport_without_reading_value(firmware, pid, value):
    sim, short, symbols = setup(firmware)
    invoke(sim, short, symbols, init=True)
    reads = []
    read = sim.rd
    def record(address):
        reads.append(address)
        return read(address)
    sim.rd = record
    invoke(sim, short, symbols, pid=pid, value=value)
    assert VALUE not in reads
    assert sim.rd(STATE + 10) == sim.rd(STATE + 11) == sim.rd(STATE + 15) == 0


@pytest.mark.firmware
@pytest.mark.parametrize('dirty', [None, 0x7fc00000, 0xffffffff],
                         ids=['finite', 'quiet-nan', 'all-bits-set'])
@pytest.mark.parametrize('mode', [0, 1, 2])
@pytest.mark.parametrize('channels', [1, 2])
def test_native_callbacks_feed_real_bridge_and_stale_saved_transport_cannot_capture(firmware, dirty, mode, channels):
    sim, short, symbols = setup(firmware)
    audio = bridge.Bridge(sim=sim, state=STATE, instance=INSTANCE, channels=channels)
    sim.wr(INSTANCE, STATE)
    # Dirty an already used instance; native init must invalidate it without
    # touching the old SDRAM audio. Normal parameters arrive via real callbacks.
    for offset in range(native.STATE_WORDS):
        sim.wr(STATE + offset, 0x5a000000 + offset if dirty is None else dirty)
    sim.wr(0x400000, ssim.f2b(.875))
    invoke(sim, short, symbols, init=True, channels=channels)
    assert sim.rd(0x400000) == ssim.f2b(.875)
    for pid, value in ((5, mode), (6, ssim.f2b(.5)), (7, ssim.f2b(.75)),
                       (8, ssim.f2b(1.)), (9, ssim.f2b(.5)), (10, 1), (11, 1), (15, 1)):
        invoke(sim, short, symbols, pid=pid, value=value)
    assert sim.rd(STATE + 10) == sim.rd(STATE + 11) == sim.rd(STATE + 15) == 0
    assert [sim.rd(STATE + pid) for pid in range(5, 10)] == [
        mode, ssim.f2b(.5), ssim.f2b(.75), ssim.f2b(1.), ssim.f2b(.5)]
    dry = [(.125 + frame/256., -.25 - frame/128.) for frame in range(16)]
    if channels == 1:
        dry = [pair[0] for pair in dry]
    output = audio.block(dry)
    assert all(math.isfinite(sample) for sample in (output if channels==1 else [sample for frame in output for sample in frame]))
    assert output == dry
    assert sim.rd(STATE + 22) == 16
    assert sim.rd(STATE + 26) == 0
    assert sim.rd(STATE + 111) == 0
    assert sim.rd(STATE + 113) == 1
    # Raw Loop is a request for the M4 gesture owner; it cannot operate the DSP
    # transport directly, even once native controller writes are accepted.
    invoke(sim, short, symbols, pid=15, value=1)
    assert sim.rd(STATE + 15) == 1
    assert audio.block(dry) == dry
    assert sim.rd(STATE + 26) == 0
    invoke(sim, short, symbols, pid=15, value=0)
    # The first owned capture after publication succeeds immediately. No
    # second Listen delivery or second tap is needed to undo saved controls.
    invoke(sim, short, symbols, pid=10, value=1)
    output = audio.block([.375] * 16 if channels==1 else [(.375, -.5)] * 16)
    assert all(math.isfinite(sample) for sample in (output if channels==1 else [sample for frame in output for sample in frame]))
    assert sim.rd(STATE + 26) == 1
