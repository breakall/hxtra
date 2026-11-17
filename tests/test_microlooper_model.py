"""Real stock-image registration; no test fixture is a runnable looper kernel."""
import struct

import pytest

import patch_amp as kit
import patch_microlooper as ml
from microlooper_definition import EFFECT
from firmware import stock, reader


def table1(data):
    e0 = kit.get_entry_swapped(data, 0)
    segs = kit._parse_e0_segments(e0)
    device = kit.e0_device(segs)
    read = reader(e0)
    base = struct.unpack('<I', read(device.TAB1_BASE_PTRS[0], 4))[0]
    _, count = kit._decode_thumb_movw(read(device.TAB1_CNT_INSN, 4))
    return [struct.unpack('<IHHI', read(base + 12 * i, 12)) for i in range(count)]


@pytest.mark.parametrize('cost', [None, 0, -1, 7501, 100., True])
def test_requires_explicit_usable_native_cost(cost):
    with pytest.raises(ValueError, match='DSP cost'):
        ml.register_model(b'', dsp_cost=cost)


@pytest.fixture(scope='module')
def registered():
    # 1000 is a structural test value, NOT a measured or advertised DSP cost.
    original = stock()
    return original, ml.register_model(original, dsp_cost=1000, log=lambda _: None)


@pytest.mark.firmware
def test_registers_stereo_graph_and_unchanged_stock_models_with_native_cost(registered):
    original, (out, result) = registered
    before, after = table1(original), table1(out)
    assert after[:-1] == before
    assert after[-1][1:] == (380, 0, 1000)
    assert result['preset_id'] == ml.PRESET_ID
    e3 = kit.get_entry_swapped(out, 3)
    info = kit.parse_entry3_full(e3)
    model = kit.find_model(info, ml.NAME)
    assert [(p['name'], p['slot'], p['type']) for p in model['params']] == [
        (p.name, p.slot, p.type) for p in EFFECT.parameters]
    assert model['meta']['displayParamCount'] == '5'
    e0 = kit.get_entry_swapped(out, 0)
    segs = kit._parse_e0_segments(e0)
    device = kit.e0_device(segs)
    read = reader(e0)
    ui_table, = struct.unpack('<I', read(device.TAB2_BASE_PTR, 4))
    _, ui_count = kit._decode_thumb_movw(read(device.TAB2_CNT_INSN, 4))
    rows = [read(ui_table + 44*i, 44) for i in range(ui_count)]
    row = next(row for row in rows if struct.unpack_from('<I', row)[0] == model['words'][2])
    assert struct.unpack_from('<3I', row, 24) == (5, 7, 7)
    assert result['instance']['sdram_words'] == 48000
    e4 = kit.get_entry_swapped(out, 4)
    words = struct.unpack(f'<{len(e4)//4}I', e4)
    b0 = kit.entry4_blob.blob(words, 0)
    comp = kit.entry4_blob.parse_composite(b0, result['composite'])
    member = comp['members'][1]
    # Composite root fields do not describe primitive inputs: even the stock
    # stereo host reports root0-in/2-out. The audio member must be2-in/2-out.
    assert (member['n_in'], member['n_out']) == (2, 2)
    assert member['type_id'] == ml.PRIM[0]
    assert not kit.pmap_slots_without_param(e4, result['blob'], model['params'])
    # Kernel registry bytes unchanged by metadata registration.
    assert kit._scan_e2_injected(kit.l6ia.swap32(kit.get_entry_swapped(out, 2)))[1] == \
           kit._scan_e2_injected(kit.l6ia.swap32(kit.get_entry_swapped(original, 2)))[1]


@pytest.mark.firmware
def test_registration_is_not_repeated_or_allowed_to_overwrite_model_id(registered):
    original, (out, _) = registered
    with pytest.raises(SystemExit, match='already registered'):
        ml.register_model(out, dsp_cost=1000)
    e0 = bytearray(kit.get_entry_swapped(original, 0))
    segs = kit._parse_e0_segments(e0)
    a = kit.e0_device(segs)
    read = reader(e0)
    base = struct.unpack('<I', read(a.TAB1_BASE_PTRS[0], 4))[0]
    # Occupy the reserved ID in a fixture; the existing generic writer must refuse it.
    struct.pack_into('<H', e0, kit._e0_vaddr_to_foff(segs, base + 4), ml.PRESET_ID)
    changed, _, _ = kit.l6ia.rebuild_archive(original, {0: bytes(e0)})
    with pytest.raises(SystemExit, match='already-used'):
        ml.register_model(changed, dsp_cost=1000, log=lambda _: None)


@pytest.mark.firmware
@pytest.mark.parametrize('other_cost,expected', [(6499, 1), (6500, 1), (6501, 0)])
def test_registered_cost_uses_the_unmodified_native_admission_limit(m4emu, registered, other_cost, expected):
    original, (out, _) = registered
    limit = 0x28e01e88
    stock_read = reader(kit.get_entry_swapped(original, 0))
    patched_read = reader(kit.get_entry_swapped(out, 0))
    # Execute the supplied firmware's admission function, not a Python copy
    # of its threshold. UI graying still requires on-device verification.
    code = stock_read(limit, 14)
    assert patched_read(limit, len(code)) == code
    native = m4emu.M4(code, limit)
    cost = table1(out)[-1][3]
    assert native.call(limit, 0, 1500 + other_cost + cost) == expected


def native_browser_budget(m4emu, registered):
    """Actual pricing, replacement-budget and total functions; no cost stubs."""
    _, (out, _) = registered
    read = reader(kit.get_entry_swapped(out, 0))
    budget, price, total = 0x28dfae0c, 0x28e01d50, 0x28dfa31c
    m = m4emu.M4(read(budget, 0x44), budget)
    m.load(price, read(price, 0x146))
    m.load(total, read(total, 0xf0))
    # The registered image relocates both the table and the lookup bounds.
    base, = struct.unpack('<I', read(0x28e01e80, 4))
    m.write(base, read(base, 12 * len(table1(out))))
    preset, replaced, descriptor, result = 0x28600000, 0x28610000, 0x28611000, 0x28612000
    name, _, _, cost = table1(out)[-1]
    m.write(descriptor, struct.pack('<3I', 6, name, 0))
    # Fifth argument lives above the native caller's stack frame.
    m.u32(m4emu.STACK_TOP, result)
    return m, (budget, total), (preset, replaced, descriptor, result), cost


@pytest.mark.firmware
@pytest.mark.parametrize('current,old,expected', [
    (7999, None, 1), (8000, None, 1), (8001, None, 0),
    (9000, 999, 0), (9000, 1000, 1), (9000, 4000, 1),
])
def test_native_browser_prices_registered_model_and_refunds_replacement(m4emu, registered, current, old, expected):
    m, (budget, _), (preset, replaced, descriptor, result), _ = native_browser_budget(m4emu, registered)
    m.u32(preset + 0xa88, current)
    if old is not None:
        m.u32(replaced + 0x44, old)
    assert m.call(budget, 0, preset, replaced if old is not None else 0, descriptor) == 0
    assert m.read(result, 1) == bytes([expected])
    assert m.u32(preset + 0xa88) == current, 'browsing must not mutate the preset total'


@pytest.mark.firmware
def test_native_total_removal_restores_looper_admission(m4emu, registered):
    m, (budget, total), (preset, _, descriptor, result), _ = native_browser_budget(m4emu, registered)
    m.u8(preset + 0xac4, 2)
    blocks = [preset + 0xaf0 + 0x9f4 * i for i in range(2)]
    for block, cost in zip(blocks, (4000, 3001)):
        m.u32(block + 0x24, 1)
        m.u32(block + 0x44, cost)
    assert m.call(total, preset) == 0
    assert m.u32(preset + 0xa88) == 8501
    assert m.call(budget, 0, preset, 0, descriptor) == 0
    assert m.read(result, 1) == b'\0'
    m.u32(blocks[1] + 0x24, 0)
    assert m.call(total, preset) == 0
    assert m.u32(preset + 0xa88) == 5500
    assert m.call(budget, 0, preset, 0, descriptor) == 0
    assert m.read(result, 1) == b'\1'
