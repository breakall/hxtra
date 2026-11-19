"""Native-control and history regressions for Glasshouse DSP optimization."""
import numpy as np
import pytest

import glasshouse_audio as audio
import glasshouse_init as callbacks
import ssim
from glasshouse import reference
from glasshouse_definition import PARAMETER_BY_PID
from test_glasshouse_review import native_engine, render


def setup_native(width):
    engine, control = native_engine()
    if width == 2:
        engine = audio.Audio(channels=2, sim=engine.sim)
    return engine, control


def update(control, knobs, toggles, index, value):
    if index < 24:
        knobs[index // 6][index % 6] = value
    else:
        toggles[(index-24) // 3][(index-24) % 3] = value
    parameter = PARAMETER_BY_PID[16+index]
    control(parameter.pid, ssim.f2b(value) if parameter.type == 3 else int(value))


def signal(count, start=0, amplitude=.25):
    i = np.arange(start, start+count, dtype=np.float32)
    return np.column_stack((amplitude*np.sin(i*.19), amplitude*.73*np.cos(i*.31))).astype(np.float32)


def native_frames(engine, frames):
    return frames[:, 0] if engine.channels == 1 else frames


def expected_frames(expected, width):
    return expected[:, 0] if width == 1 else expected


@pytest.mark.firmware
@pytest.mark.parametrize('width', (1, 2))
def test_native_coefficient_updates_invalidate_caches_before_the_next_audio_block(tmp_path, width):
    engine, control = setup_native(width)
    knobs = [list(page) for page in reference.KNOBS]
    toggles = [list(page) for page in reference.TOGGLES]
    knobs[0][0], knobs[0][1], knobs[0][3] = .6, .7, .03
    toggles[2][0] = 1
    engine.settings(knobs, toggles)
    frames = signal(1024)
    source_frames = frames if width == 2 else np.column_stack((frames[:, 0], frames[:, 0]))
    commands = [reference.settings(knobs, toggles, reset=True), reference.switch('enable', True)]
    actual = []
    stages = ((), ((3, .97), (10, 0.), (11, .91), (7, 0.), (29, 2), (27, 2)),
              ((3, .08), (10, 1.), (11, 0.), (29, 0), (27, 0), (24, 2)),
              ((21, 1.), (13, 1.), (33, 2), (34, 2), (35, 1)))
    for stage, changes in enumerate(stages):
        for index, value in changes:
            update(control, knobs, toggles, index, value)
        if changes:
            commands.append(reference.settings(knobs, toggles))
        chunk = frames[256*stage:256*(stage+1)]
        actual.extend(render(engine, native_frames(engine, chunk)))
        commands.append(reference.process(source_frames[256*stage:256*(stage+1)]))
    expected = reference.run(reference.build_reference(tmp_path), *commands)
    np.testing.assert_allclose(actual, expected_frames(expected, width), atol=1e-5, rtol=0)


@pytest.mark.firmware
@pytest.mark.parametrize('width', (1, 2))
def test_disabled_gate_and_emphasis_keep_the_source_filter_history(tmp_path, width):
    engine, control = setup_native(width)
    knobs = [list(page) for page in reference.KNOBS]
    toggles = [list(page) for page in reference.TOGGLES]
    knobs[0][1], knobs[0][3], knobs[1][0], knobs[1][1] = 0., 0., 1., 0.
    toggles[1][0], toggles[2][0] = 0, 1
    engine.settings(knobs, toggles)
    frames = signal(1024, amplitude=.01)
    source_frames = frames if width == 2 else np.column_stack((frames[:, 0], frames[:, 0]))
    commands = [reference.settings(knobs, toggles, reset=True), reference.switch('enable', True)]
    actual = render(engine, native_frames(engine, frames[:512]))
    commands.append(reference.process(source_frames[:512]))
    for first, changes in ((512, ((14, 1), (29, 2))), (768, ((14, 0), (29, 0)))):
        for index, value in changes:
            update(control, knobs, toggles, index, value)
        commands.append(reference.settings(knobs, toggles))
        actual.extend(render(engine, native_frames(engine, frames[first:first+256])))
        commands.append(reference.process(source_frames[first:first+256]))
    expected = reference.run(reference.build_reference(tmp_path), *commands)
    np.testing.assert_allclose(actual, expected_frames(expected, width), atol=1e-6, rtol=0)


@pytest.mark.firmware
@pytest.mark.parametrize('width', (1, 2))
def test_drive_reenable_uses_the_last_active_adaa_history(tmp_path, width):
    engine, control = setup_native(width)
    knobs = [list(page) for page in reference.KNOBS]
    toggles = [list(page) for page in reference.TOGGLES]
    knobs[0], knobs[2][4], toggles[2][0] = [.8, 0., 1., 0., .5, .25], 1., 1
    engine.settings(knobs, toggles)
    frames = signal(1024, amplitude=.8)
    source_frames = frames if width == 2 else np.column_stack((frames[:, 0], frames[:, 0]))
    commands = [reference.settings(knobs, toggles, reset=True), reference.switch('enable', True)]
    actual = render(engine, native_frames(engine, frames[:256]))
    commands.append(reference.process(source_frames[:256]))
    update(control, knobs, toggles, 16, 0)
    commands.append(reference.settings(knobs, toggles))
    actual.extend(render(engine, native_frames(engine, frames[256:768])))
    commands.append(reference.process(source_frames[256:768]))
    update(control, knobs, toggles, 16, 1)
    commands.append(reference.settings(knobs, toggles))
    actual.extend(render(engine, native_frames(engine, frames[768:])))
    commands.append(reference.process(source_frames[768:]))
    expected = reference.run(reference.build_reference(tmp_path), *commands)
    np.testing.assert_allclose(actual, expected_frames(expected, width), atol=1e-4, rtol=0)


@pytest.mark.firmware
@pytest.mark.parametrize('width', (1, 2))
def test_native_graph_reinitialization_invalidates_channel_adaa_caches(tmp_path, width):
    engine, control = setup_native(width)
    knobs = [list(page) for page in reference.KNOBS]
    toggles = [list(page) for page in reference.TOGGLES]
    knobs[2][4], toggles[2][0] = 1., 1
    engine.settings(knobs, toggles)
    render(engine, native_frames(engine, signal(128)))
    # New optimization storage is private channel18..31. Poisoning it makes
    # any stale-cache read visible; actual native init must invalidate runtime.
    for channel in range(2):
        for offset in range(18, 32):
            engine.sim.wr(engine.state+128+32*channel+offset, 0x7fc0dead)
    sim = engine.sim
    _, symbols = callbacks.assemble(0xe5000)
    descriptor = 0xb6000
    sim.wr(descriptor, engine.state)
    for register, word in ((0x16, 0xc6e98), (0x17, 0xc6d98), (0x27, 0xffffffff),
                           (0x2e, 1), (0x37, 0), (4, descriptor)):
        sim.set(register, word)
    sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x10000
    entry = 'GLASSHOUSE_INIT_MONO' if width == 1 else callbacks.INIT_ENTRY
    from firmware import stock
    import kit_patch_amp as kit
    import microlooper_visa as visa
    archive = stock()
    section = kit.l6ia.parse(archive)[2]
    _, short = visa.load(archive[section['payload_off']:section['payload_off']+section['payload_len']],
                         parcel_order='high-first', external_parcel_order='low-first')
    callbacks.invoke_from_stock_c_caller(sim, short, symbols[entry], limit=160)
    for index in range(36):
        if index == 17:
            continue
        value = knobs[index // 6][index % 6] if index < 24 else toggles[(index-24)//3][(index-24)%3]
        update(control, knobs, toggles, index, value)
    frames = signal(256, start=128)
    source_frames = frames if width == 2 else np.column_stack((frames[:, 0], frames[:, 0]))
    actual = render(engine, native_frames(engine, frames))
    expected = reference.run(reference.build_reference(tmp_path), reference.settings(knobs, toggles, reset=True),
                             reference.switch('enable', True), reference.process(source_frames))
    assert np.isfinite(actual).all()
    np.testing.assert_allclose(actual, expected_frames(expected, width), atol=1e-4, rtol=0)
