"""Effect declarations are checked through real generated native structures."""
from dataclasses import replace
import struct

import pytest

import effect_model as native
from microlooper_definition import EFFECT
from firmware import stock


@pytest.mark.parametrize('field,value', [
    ('default', float('nan')), ('minimum', float('-inf')), ('default', 3),
    ('slot', True), ('state_index', -1), ('restore', 'replay'), ('labels', ('one',)),
])
def test_invalid_parameter_declarations_are_refused(field, value):
    with pytest.raises(ValueError):
        replace(EFFECT.parameters[0], **{field: value})


@pytest.mark.parametrize('field', ['slot', 'pid', 'state_index', 'state_key', 'name'])
def test_aliasing_parameter_identities_are_refused(field):
    params = list(EFFECT.parameters)
    params[1] = replace(params[1], **{field: getattr(params[0], field)})
    with pytest.raises(ValueError, match='duplicate'):
        replace(EFFECT, parameters=tuple(params))


def test_hidden_actions_cannot_become_visible_through_ui_order():
    params = list(EFFECT.parameters)
    params[-1] = replace(params[-1], ui_index=6)
    with pytest.raises(ValueError, match='UI prefix'):
        replace(EFFECT, parameters=tuple(params))


@pytest.mark.parametrize('instance', [
    native.InstanceWords(931, 0, 48000), native.InstanceWords(199, 481, 48000),
    native.InstanceWords(199, 0, 0x63001),
])
def test_private_payload_must_fit_the_host(instance):
    with pytest.raises(ValueError, match='host budget'):
        replace(EFFECT, instance=instance)


@pytest.mark.parametrize('words', [-1, True, 0x100000000])
def test_resource_counts_are_real_unsigned_words(words):
    with pytest.raises(ValueError):
        native.InstanceWords(words, 0, 0)


def test_callback_registry_distinguishes_reset_from_teardown():
    callbacks = native.Callbacks('init', 'control', 'process', reset='reset', teardown='teardown')
    effect = replace(EFFECT, callbacks=callbacks)
    symbols = dict(init=0xe0000, control=0xe0010, process=0xe0020, reset=0xe0030, teardown=0xe0040)
    assert effect.registry(symbols) == [0x12e, 0xe0000, 0xe0040, 0xe0030, 0xe0010, 0xe0020, 163, 0]
    with pytest.raises(KeyError):
        effect.registry({})
    with pytest.raises(ValueError, match='null'):
        effect.registry({**symbols, 'process': 0})


@pytest.fixture(scope='module')
def registered():
    # Deliberately separate state order from public/UI slot order. The native
    # state table and pmap must agree without silently changing public slots.
    params = tuple(replace(p, state_index=len(EFFECT.parameters)-1-p.state_index) for p in EFFECT.parameters)
    effect = replace(EFFECT, parameters=params)
    image, _ = native.register_model(stock(), effect, dsp_cost=1000,
                                     registry_address=0x200058, log=lambda _: None)
    return image, effect


@pytest.mark.firmware
def test_persisted_order_is_independent_of_public_slots(registered):
    image, effect = registered
    item, cost = native.verify_model(image, effect)
    assert cost == 1000
    assert [p['slot'] for p in item['params']] == [8, 7, 6, 5, 4, 3, 2, 1]
    params = effect.native_parameters()
    assert params[0]['state'] == 'OverdubState' and params[0]['slot'] == 8
    assert [p.restore for p in EFFECT.parameters[-3:]] == ['ignore', 'ignore', 'ignore']


@pytest.mark.firmware
@pytest.mark.parametrize('change', ['default', 'bounds', 'state_index', 'state_name', 'ui_count'])
def test_readback_refuses_inconsistent_native_state(registered, change):
    image, effect = registered
    item, _ = native.verify_model(image, effect)
    e3 = bytearray(native.kit.get_entry_swapped(image, 3))
    updates = {}
    if change in ('default', 'bounds'):
        p = item['params'][0]
        struct.pack_into('<I', e3, p['off']+(28 if change == 'default' else 20), 2)
    elif change.startswith('state'):
        offset = item['words'][10] + (16 if change == 'state_index' else 8)
        struct.pack_into('<I', e3, offset, 0xffffffff)
    else:
        e0 = bytearray(native.kit.get_entry_swapped(image, 0))
        segments = native.kit._parse_e0_segments(e0)
        target = native.kit.e0_device(segments)
        off = native.kit._e0_vaddr_to_foff
        table, = struct.unpack_from('<I', e0, off(segments, target.TAB2_BASE_PTR, 4))
        _, count = native.kit._decode_thumb_movw(e0[off(segments, target.TAB2_CNT_INSN, 4):][:4])
        row = off(segments, table+44*(count-1), 44)
        struct.pack_into('<I', e0, row+24, 7)
        updates[0] = bytes(e0)
    updates[3] = bytes(e3)
    changed, _, _ = native.kit.l6ia.rebuild_archive(image, updates)
    with pytest.raises(ValueError):
        native.verify_model(changed, effect)
