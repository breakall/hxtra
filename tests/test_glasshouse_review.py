"""Independent integration regressions found while reviewing the emitted port."""
import numpy as np
import pytest

import glasshouse_audio as audio
from glasshouse import reference


def render(engine, frames):
    return [sample for first in range(0, len(frames), 16)
            for sample in engine.block(frames[first:first+16], inplace=True)]


def native_engine():
    """Actual stock C callsite drives the port's emitted parameter callback."""
    from firmware import stock
    import glasshouse_init as callbacks
    import kit_patch_amp as kit
    import microlooper_visa as visa
    import ssim

    archive = stock()
    entry = kit.l6ia.parse(archive)[2]
    e2 = archive[entry['payload_off']:entry['payload_off']+entry['payload_len']]
    sim, short = visa.load(e2, parcel_order='high-first', external_parcel_order='low-first')
    sections, symbols = callbacks.assemble(0xe5000)
    sim.load(sections)
    engine = audio.Audio(channels=1, sim=sim)
    descriptor, value = 0xb6000, 0xb7000
    sim.wr(descriptor, engine.state)

    def control(pid, word):
        for register, register_word in ((0x16, 0xc6e98), (0x17, 0xc6d98), (0x27, 0xffffffff),
                                        (0x2e, 1), (0x37, 0), (4, pid), (8, value), (12, descriptor)):
            sim.set(register, register_word)
        sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x10000
        sim.wr(value, word)
        callbacks.invoke_from_stock_c_caller(sim, short, symbols[callbacks.CONTROL_ENTRY], limit=160)
    return engine, control


def test_settled_drive_matches_source_for_small_changes_at_high_parallel_gain(tmp_path):
    oracle = reference.build_reference(tmp_path)
    knobs = [list(page) for page in reference.KNOBS]
    toggles = [list(page) for page in reference.TOGGLES]
    # Every parameter is valid, with both parallel levels at their documented
    # +12dB endpoints. Keep the input strictly below digital full scale.
    knobs[0] = [1., 0., 1., 0., .5, 1.]
    knobs[2][4] = 1.
    toggles[1][0], toggles[2][0] = 0, 1
    samples = np.concatenate((np.full(3072, .99, dtype=np.float32),
                              .99 + np.arange(256, dtype=np.float32)*4e-6))
    frames = np.column_stack((samples, samples))
    expected = reference.run(oracle, reference.settings(knobs, toggles, reset=True),
                             reference.switch('enable', True), reference.process(frames))
    engine = audio.Audio()
    engine.settings(knobs, toggles)
    actual = np.asarray(render(engine, frames))
    # The port's documented existing ADAA/source tolerance is1e-4.
    np.testing.assert_allclose(actual, expected, atol=1e-4, rtol=0)


@pytest.mark.firmware
def test_native_aux_pulse_between_audio_blocks_completes_the_source_manual_dip(tmp_path):
    engine, control = native_engine()
    knobs = [list(page) for page in reference.KNOBS]
    toggles = [list(page) for page in reference.TOGGLES]
    knobs[0][1], knobs[0][3] = 0., 0.
    knobs[1][2], knobs[1][3] = 0., 0.
    toggles[2][1] = 1  #manual dip: even a brief tap must complete the dip
    engine.settings(knobs, toggles)
    warm, tail = np.full(512, .2, dtype=np.float32), np.full(128, .2, dtype=np.float32)
    actual = render(engine, warm)
    control(52, 1)
    control(52, 0)
    actual.extend(render(engine, tail))
    oracle = reference.build_reference(tmp_path)
    expected = reference.run(oracle, reference.settings(knobs, toggles, reset=True),
                             reference.switch('enable', True), reference.process(warm),
                             reference.switch('aux', True), reference.switch('aux', False),
                             reference.process(tail))[:, 0]
    np.testing.assert_allclose(actual, expected, atol=1e-5, rtol=0)


@pytest.mark.firmware
def test_native_disable_enable_between_blocks_restarts_one_shot_automation(tmp_path):
    engine, control = native_engine()
    knobs = [list(page) for page in reference.KNOBS]
    toggles = [list(page) for page in reference.TOGGLES]
    knobs[0][1], knobs[0][3] = 0., 0.
    knobs[2][1], knobs[3][2] = 1., 1.  #8Hz, full Wet automation depth
    toggles[3] = [1, 0, 0]  #one shot/rise/linear
    engine.settings(knobs, toggles)
    warm, tail = np.full(512, .2, dtype=np.float32), np.full(128, .2, dtype=np.float32)
    actual = render(engine, warm)
    control(54, 0)
    control(54, 1)
    actual.extend(render(engine, tail))
    oracle = reference.build_reference(tmp_path)
    expected = reference.run(oracle, reference.settings(knobs, toggles, reset=True),
                             reference.switch('enable', True), reference.process(warm),
                             reference.switch('enable', False), reference.switch('enable', True),
                             reference.process(tail))[:, 0]
    np.testing.assert_allclose(actual, expected, atol=1e-5, rtol=0)


@pytest.mark.firmware
def test_aux_captures_swell_mode_when_control_is_delivered(tmp_path):
    engine, control = native_engine()
    knobs = [list(page) for page in reference.KNOBS]
    toggles = [list(page) for page in reference.TOGGLES]
    knobs[0][1], knobs[0][3] = 0., 0.
    knobs[1][2], knobs[1][3] = 0., 0.
    engine.settings(knobs, toggles)
    warm = np.full(512, .2, dtype=np.float32)
    held, tail = np.full(16, .2, dtype=np.float32), np.full(128, .2, dtype=np.float32)
    actual = render(engine, warm)
    control(52, 1)  #Aux in the nonmanual mode does not latch a manual dip.
    control(47, 1)  #Changing mode afterward must not reinterpret that event.
    actual.extend(render(engine, held))
    control(52, 0)
    actual.extend(render(engine, tail))
    changed = [list(page) for page in toggles]
    changed[2][1] = 1
    oracle = reference.build_reference(tmp_path)
    expected = reference.run(oracle, reference.settings(knobs, toggles, reset=True),
                             reference.switch('enable', True), reference.process(warm),
                             reference.switch('aux', True), reference.settings(knobs, changed),
                             reference.process(held), reference.switch('aux', False),
                             reference.process(tail))[:, 0]
    np.testing.assert_allclose(actual, expected, atol=1e-5, rtol=0)
