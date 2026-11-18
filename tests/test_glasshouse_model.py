"""Native Glasshouse declarations roundtrip the real model/graph tables."""
from dataclasses import replace
import struct

import pytest

import effect_model
import kit_patch_amp as kit
import patch_glasshouse as native
import patch_microlooper
from firmware import stock
from glasshouse_definition import (MODELS, PARAMETERS, PARAMETER_BASE, FLOAT_BOOLS,
                                   source_default, AUX_PID, SAG_PID, ENABLE_PID)


@pytest.fixture(scope='module')
def registered():
    original = stock()
    atmosphere, _ = patch_microlooper.register_models(
        original, dsp_costs={effect.name: 1000 for effect in patch_microlooper.MODELS}, log=lambda _: None)
    final, result = native.register_models(
        atmosphere, dsp_costs={MODELS[0].name: 1600, MODELS[1].name: 1100}, log=lambda _: None)
    return original, atmosphere, final, result


def test_native_controls_cover_source_sound_settings_and_separate_actions():
    assert [parameter.name for parameter in PARAMETERS[:6]] == [
        'Sensitivity', 'Dynamics', 'Wet', 'Attack', 'EQ', 'Dry']
    assert {parameter.pid for parameter in PARAMETERS} == set(range(16, 55)) - {33}
    for parameter in PARAMETERS:
        index = parameter.pid - PARAMETER_BASE
        default = source_default(index)
        assert parameter.default == default
        if index in FLOAT_BOOLS:
            assert parameter.type == 1
        elif index < 24:
            assert parameter.type == 3
        elif index < 36:
            assert parameter.type == 2 and len(parameter.labels) == 3
    aux, sag, enable = (next(p for p in PARAMETERS if p.pid == pid)
                        for pid in (AUX_PID, SAG_PID, ENABLE_PID))
    assert aux.ui_index is not None and aux.restore == 'value'
    assert sag.ui_index is not None and sag.restore == 'value'
    assert enable.ui_index is None and enable.follow_enable
    assert not any(parameter.follow_enable for parameter in PARAMETERS[:-1])


def test_enable_policy_rejects_visible_or_nonboolean_follower():
    enable = PARAMETERS[-1]
    with pytest.raises(ValueError, match='hidden boolean'):
        replace(enable, ui_index=37)
    with pytest.raises(ValueError, match='hidden boolean'):
        replace(enable, type=2)
    with pytest.raises(ValueError, match='native enable follower'):
        replace(MODELS[0], parameters=tuple(replace(p, follow_enable=False) for p in PARAMETERS))


@pytest.mark.firmware
def test_family_preserves_atmosphere_and_original_dynamics_sources(registered):
    original, atmosphere, final, results = registered
    before = kit.parse_entry3_full(kit.get_entry_swapped(original, 3))
    after = kit.parse_entry3_full(kit.get_entry_swapped(final, 3))
    assert [row['preset_id'] for row in results] == [382, 383]
    assert [row['dsp_cost'] for row in results] == [1600, 1100]
    assert set(native.REGISTRY_ADDRESSES.values()).isdisjoint(patch_microlooper.REGISTRY_ADDRESSES.values())
    for effect, price in zip(MODELS, (1600, 1100)):
        item, cost = effect_model.verify_model(final, effect)
        assert cost == price
        assert item['meta']['category'] == 'dynamics'
        assert item['meta']['subcategory'] == ('stereo' if effect.width == 2 else 'mono')
        assert item['meta']['followEnable'] == 'true'
        assert item['meta']['displayParamCount'] == '37'
        assert item['params'][-1]['meta']['followEnable'] == 'true'
        source_before = kit.find_model(before, effect.source_model)
        source_after = kit.find_model(after, effect.source_model)
        assert source_before['meta'] == source_after['meta']
        assert source_before['params'] == source_after['params']
    for effect in patch_microlooper.MODELS:
        a, cost_a = effect_model.verify_model(atmosphere, effect)
        b, cost_b = effect_model.verify_model(final, effect)
        assert cost_a == cost_b == 1000
        assert a['meta'] == b['meta']
        assert [{k: v for k, v in p.items() if k != 'off'} for p in a['params']] == [
            {k: v for k, v in p.items() if k != 'off'} for p in b['params']]
    # Metadata alone must not install process callbacks or modify registry rows.
    assert kit.get_entry_swapped(atmosphere, 2) == kit.get_entry_swapped(final, 2)


@pytest.mark.firmware
def test_checked_registration_refuses_repeated_models_and_occupied_primitive(registered):
    _, _, final, _ = registered
    with pytest.raises(SystemExit, match='already registered'):
        native.register_models(final, dsp_costs={effect.name: 1200 for effect in MODELS})
    occupied = replace(MODELS[0], primitive=patch_microlooper.MODELS[0].primitive)
    with pytest.raises(SystemExit, match='already used'):
        effect_model.register_model(final, replace(occupied, name='GlasshouseCollision'),
                                    dsp_cost=1200, registry_address=0x200120)


@pytest.mark.parametrize('costs', [{}, {MODELS[0].name: 1200},
                                  {effect.name: 0 for effect in MODELS}])
def test_every_width_requires_an_explicit_valid_native_cost(costs):
    with pytest.raises(ValueError, match='cost'):
        native.register_models(b'', dsp_costs=costs)


@pytest.mark.firmware
def test_verifier_rejects_tampered_native_enable_policy(registered):
    _, _, image, _ = registered
    effect = MODELS[0]
    e0 = bytearray(kit.get_entry_swapped(image, 0))
    e3 = kit.get_entry_swapped(image, 3)
    item = kit.find_model(kit.parse_entry3_full(e3), effect.name)
    segs = kit._parse_e0_segments(e0)
    target = kit.e0_device(segs)
    off = lambda address, n=4: kit._e0_vaddr_to_foff(segs, address, n)
    table, = struct.unpack_from('<I', e0, off(target.TAB2_BASE_PTR))
    _, count = kit._decode_thumb_movw(e0[off(target.TAB2_CNT_INSN):][:4])
    row = next(off(table+44*i, 44) for i in range(count)
               if struct.unpack_from('<I', e0, off(table+44*i))[0] == item['words'][2])
    struct.pack_into('<I', e0, row+36, 0)
    changed, _, _ = kit.l6ia.rebuild_archive(image, {0: bytes(e0)})
    with pytest.raises(ValueError, match='enable-following'):
        effect_model.verify_model(changed, effect)
