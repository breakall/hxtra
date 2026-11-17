"""Actual complete-image Atmosphere layout, callback and audio integration."""
import os
import struct

import pytest

import kit_patch_amp as kit
import m4cache
import patch_comp
import patch_click
import patch_microlooper_build as build
from microlooper_definition import MODELS
from sharc import microlooper as layout
from sharc import microlooper_adapter as loader
from sharc import microlooper_bridge as bridge
from sharc import microlooper_audio as audio
from sharc import microlooper_init as callbacks
from sharc import nam_multi


@pytest.fixture(scope='module', params=[3, 2], ids=['NAM3-click', 'NAM2-GR-click'])
def profile_image(tmp_path_factory, request):
    path = os.environ.get('HX_STOMP_HXF')
    if not path:
        pytest.skip('HX_STOMP_HXF is not set')
    base = m4cache.nam_base(path, str(tmp_path_factory.mktemp('microlooper-base')))
    image, _ = kit.load_l6ia_from_any(base)
    image, _ = build.prepare_metadata(image, dsp_cost=1000, log=lambda _: None)
    with nam_multi.flags(['--mid-sweep']):
        source, lay = nam_multi.build(request.param)
    image, _ = kit.patch_kernel(image, source, 'nam1.asm', relocate=False, log=lambda _: None)
    image, _ = patch_click.add_click(image, log=lambda _: None, lay=lay)
    if request.param == 2:
        image = patch_comp.patch_comp(image, log=lambda _: None)
        image = patch_comp.patch_dsp(image, log=lambda _: None, lay=lay)
    return image


@pytest.fixture(scope='module')
def linked(profile_image):
    return build.link_dsp(profile_image, log=lambda _: None, require_controls=False)


@pytest.mark.firmware
def test_full_profile_links_exact_private_callbacks_with_unchanged_other_entries(profile_image, linked):
    image, report = linked
    cold, hot, shim, init = report['section_instructions']
    assert cold+hot == audio.instructions()+(report['code_split']['region'] == 'sample-loop')
    assert (shim, init) == (bridge.instructions(), callbacks.instructions())
    assert report['entry2_bytes'] <= layout.ENTRY2_INJECTION_LIMIT
    assert report['code_ldr_records'] == 2
    assert [section['kind'] for section in report['executable_sections']] == ['external_isa48', 'internal_isa48']
    assert report['entry2_remaining_bytes'] == layout.ENTRY2_INJECTION_LIMIT-report['entry2_bytes']
    assert report['private_dm_words'] == 163 and report['private_pm_words'] == 0
    assert report['private_sdram_words'] == 48000 and report['nam_slots'] in (2, 3)
    assert not report['hardware_verified'] and not report['native_dsp_cost_measured']
    for index in range(len(kit.l6ia.parse(image))):
        if index != 2:
            assert kit.get_entry_swapped(image, index) == kit.get_entry_swapped(profile_image, index)
    raw = kit.l6ia.swap32(kit.get_entry_swapped(image, 2))
    actual = [loader.ldr_word(raw, build.model.PRIM[1]+i) for i in range(8)]
    assert actual == [0x012e, report['init_entry'], 0, 0, report['control_entry'], report['process_entry'], 163, 0]
    assert len(report['models']) == 2
    for effect, row in zip(MODELS, report['models']):
        assert row['effect'] == effect.describe()
        assert row['declared_dsp_cost'] == 1000
        assert row['private_sdram_words'] == 24000*effect.width
        actual = [loader.ldr_word(raw, row['registry_address']+i) for i in range(8)]
        assert actual == [effect.primitive, row['init_entry'], 0, 0,
                          row['control_entry'], row['process_entry'], 163, 0]
    with pytest.raises(ValueError, match='already installed'):
        build.link_dsp(image, log=lambda _: None, require_controls=False)


@pytest.mark.firmware
@pytest.mark.parametrize('mode', [0, 1, 2])
@pytest.mark.parametrize('channels', [1, 2])
def test_encoded_final_image_process_matches_the_actual_core(linked, mode, channels):
    image, report = linked
    # Execute bytes replayed from the final image, at the actual linked entry.
    runner = bridge.Bridge(core_base=report['pm_base'], bridge_base=report['process_entry'], channels=channels)
    raw = kit.l6ia.swap32(kit.get_entry_swapped(image, 2))
    runner.sim.pm.clear()
    runner.sim.pm.update(layout.pm_words(loader.ldr_blocks(raw)))
    storage = report['code_storage']
    data = next(payload for tag, count, address, payload in loader.ldr_blocks(raw)
                if tag == 4 and address == storage['data_begin'])
    packed = struct.pack(f'<{len(data)}I', *data)
    runner.sim.pm.update((report['pm_base']+i, int.from_bytes(packed[6*i:6*i+6], 'little'))
                         for i in range(storage['instructions']))
    reference = audio.Audio(channels=channels)
    settings = dict(mode=mode, length=.4, modify=.6, clock=1., mix=.75)
    runner.params(**settings)
    reference.params(**settings)
    for block in range(7):
        if block in (3, 5):
            runner.params(play=True, overdub=block == 5)
            reference.params(play=True, overdub=block == 5)
        samples = [(k/64., -(k+1)/128.) for k in range(block*16, (block+1)*16)]
        if channels == 1:
            samples = [frame[0] for frame in samples]
        assert runner.block(samples) == reference.block(samples)


@pytest.mark.firmware
def test_linker_rejects_code_collision_before_overwriting(profile_image, linked):
    _, report = linked
    raw = kit.l6ia.swap32(kit.get_entry_swapped(profile_image, 2))
    raw = kit.inject_sharc_ldr_blocks(raw, kit.pack_init_l48(report['pm_base'], [0, 0]))
    image, _, _ = kit.l6ia.rebuild_archive(profile_image, {2: kit.l6ia.swap32(raw)})
    with pytest.raises(ValueError, match='overlaps boot'):
        build.link_dsp(image, log=lambda _: None, require_controls=False)


@pytest.mark.firmware
@pytest.mark.parametrize('channels', [1, 2])
def test_final_external_callbacks_run_through_original_native_c_call(linked, channels):
    import microlooper_visa as visa
    import ssim
    image, report = linked
    row = next(row for row in report['models'] if row['effect']['width'] == channels)
    raw = kit.l6ia.swap32(kit.get_entry_swapped(image, 2))
    sim, short = visa.load(raw, parcel_order='high-first', external_parcel_order='low-first')
    data = next(payload for tag, count, address, payload in loader.ldr_blocks(raw)
                if tag == 4 and address == report['code_storage']['data_begin'])
    packed = struct.pack(f'<{len(data)}I', *data)
    sim.pm.update((report['pm_base']+i, int.from_bytes(packed[6*i:6*i+6], 'little'))
                  for i in range(report['code_storage']['instructions']))
    state, descriptor, value = 0xb3000, 0xb6000, 0xb7000
    frame, stack = 0xc6e98, 0xc6d98
    for offset in range(163):
        sim.wr(state+offset, 0x7fc00000)
    sim.wr(descriptor, state)
    sim.wr(0x400000, 0xdeadbeef)
    for register, word in ((0x16, frame), (0x17, stack), (0x27, 0xffffffff),
                           (0x2e, 1), (0x37, 0), (4, descriptor)):
        sim.set(register, word)
    sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x10000
    callbacks.invoke_from_stock_c_caller(sim, short, row['init_entry'])
    assert [sim.rd(state+i) for i in (10, 11, 20)] == [0, 0, 0]
    assert sim.rd(state+14) == channels
    assert sim.rd(state+9) == 0x7fc00000
    assert sim.rd(0x400000) == 0xdeadbeef
    for live in (False, True):
        sim.wr(state+20, int(live))
        sim.wr(value, 1)
        for register, word in ((0x16, frame), (0x17, stack), (4, 10), (8, value), (12, descriptor)):
            sim.set(register, word)
        callbacks.invoke_from_stock_c_caller(sim, short, report['control_entry'])
        assert sim.rd(state+10) == int(live)


@pytest.mark.firmware
def test_boot_partition_overflow_is_rejected(profile_image, linked):
    raw = kit.l6ia.swap32(kit.get_entry_swapped(profile_image, 2))
    # Valid external initialized data cannot be compacted or confused with PM.
    extra_words = linked[1]['entry2_remaining_bytes']//4 + 1
    raw = kit.inject_sharc_ldr_blocks(raw, kit.pack_init_l32(0x3000000, [0xabc] * extra_words))
    image, _, _ = kit.l6ia.rebuild_archive(profile_image, {2: kit.l6ia.swap32(raw)})
    with pytest.raises(ValueError, match='exceeds its partition'):
        build.link_dsp(image, log=lambda _: None, require_controls=False)


@pytest.mark.firmware
@pytest.mark.parametrize('change', ['transport_pid', 'transport_default', 'input_type'])
def test_final_graph_routing_and_initial_transport_defaults_are_verified(profile_image, change):
    info = kit.parse_entry3_full(kit.get_entry_swapped(profile_image, 3))
    item = kit.find_model(info, build.model.NAME)
    e4 = kit.get_entry_swapped(profile_image, 4)
    words = struct.unpack(f'<{len(e4)//4}I', e4)
    blob = list(kit.entry4_blob.blob(words, item['blob_index']))
    pmap, count, play = blob[6], len(build.EFFECT.parameters), 5
    if change == 'transport_pid':
        writer = pmap+blob[pmap]+10*(count+play)
        blob[pmap+blob[writer]+1] = 11  # Play's slot must target PID10, never Overdub.
    elif change == 'transport_default':
        value = blob[blob[10]+4*(count+play)+2]
        blob[value+1] = 1
    else:
        blob[pmap+blob[pmap]+10*play+3] = 0xb  # int input in place of bool
    changed = patch_comp.e4_replace_blob(e4, item['blob_index'], blob)
    image, _, _ = kit.l6ia.rebuild_archive(profile_image, {4: changed})
    with pytest.raises(ValueError, match='parameter map'):
        build.verify_metadata(image)


@pytest.mark.firmware
def test_complete_link_refuses_audio_without_control_hooks(profile_image):
    with pytest.raises(ValueError, match='runtime manifest'):
        build.link_dsp(profile_image, log=lambda _: None)


@pytest.mark.firmware
@pytest.mark.parametrize('long_press', [False, True])
def test_full_feature_and_dsp_phases_verify_controls_and_nam_profile(profile_image, long_press):
    import patch_menu
    flags = m4cache.web_flags()
    env = {flag: '1' for flag in flags if long_press or flag != 'HX_LONG_PRESS'}
    env['HX_MICRO_LOOPER'] = '1'
    updates, _ = patch_menu.menu_entries(lambda n: kit.get_entry_swapped(profile_image, n), env=env)
    image, _, _ = kit.l6ia.rebuild_archive(profile_image, updates)
    _, report = build.link_dsp(image, log=lambda _: None)
    assert report['controls_verified']
    assert report['controls']['shared_long_press'] == long_press
    assert 'nam_capacity' not in report['controls']
    # Enabling Micro must not install the retired NAM-capacity wrapper.
    before = kit.get_entry_swapped(profile_image, 0)
    after = kit.get_entry_swapped(image, 0)
    for address in (0x28dfffc4, 0x28e0060a):
        spans = [kit._e0_vaddr_to_foff(kit._parse_e0_segments(e0), address, 4)
                 for e0 in (before, after)]
        assert before[spans[0]:spans[0]+4] == after[spans[1]:spans[1]+4]
    assert report['controls']['lifecycle_hooks'] >= 9
    assert report['declared_dsp_cost'] == 1000  # structural fixture, not a measured cost
