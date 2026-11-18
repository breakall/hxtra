"""Execute stock bypass/enable dispatch using generated model metadata.

The original M4 mutation and followEnable loop run unchanged. Library metadata
accessors are supplied from the generated Entry3 records, and the DSP-library
writer is the observed seam. This proves selection/boolean delivery and native
bypass modes, not hardware transport or model-constructor parsing.
"""
import struct

import pytest

import effect_model
import kit_patch_amp as kit
import patch_glasshouse
from firmware import reader, stock
from glasshouse_definition import MODELS, ENABLE_SLOT

ROOT, SESSION, LIBRARY, BLOCK, DESCRIPTOR = (0x28600000, 0x28610000, 0x28620000,
                                          0x28630000, 0x28640000)
MANAGER = ROOT + 0x43fc


@pytest.fixture(scope='module')
def registered():
    image, _ = patch_glasshouse.register_models(
        stock(), dsp_costs={effect.name: 1200 for effect in MODELS}, log=lambda _: None)
    return image


class NativeBypass:
    def __init__(self, api, image, effect, *, self_bypass=True):
        e0 = kit.get_entry_swapped(image, 0)
        self.read = reader(e0)
        self.m = m = api.M4(self.read(0x28d8fa80, 0xb005c), 0x28d8fa80)
        self.model, _ = effect_model.verify_model(image, effect)
        info = kit.parse_entry3_full(kit.get_entry_swapped(image, 3))
        self.strings = info['strings']
        self.writes = []
        m.u32(ROOT + 20, 1)  # grid effect0 -> native block ID1
        m.u32(MANAGER, SESSION)
        m.u32(MANAGER + 12, LIBRARY)
        m.u8(SESSION + 0x64ad, 0)  # live library path
        m.u8(BLOCK + 5, 1)  # ordinary native effect object
        m.u32(BLOCK + 32, 1)  # enabled
        m.u8(BLOCK + 40, 24 if self_bypass else 1)
        m.u32(BLOCK + 48, 0x500)  # host graph handle
        m.u32(BLOCK + 52, 0x600)  # parameter-map graph handle
        m.u32(BLOCK + 76, 0x123)  # host bypass-mode parameter
        m.u8(BLOCK + 104, int(effect.follow_enable))
        m.write(DESCRIPTOR, struct.pack('<2I', 6, 0))
        m.stub(0x28dfa794, lambda m: (m.u32(m.reg('r2'), BLOCK), m.reg('r0', 0)))
        m.stub(0x28df356c, lambda m: m.reg('r0', len(self.model['params'])))
        m.stub(0x28df3574, self.parameter)
        m.stub(0x28df35b8, self.metadata)
        m.stub(0x28df35e8, self.write)
        m.stub(0x28e1f844, lambda m: (m.write(m.reg('r1'), bytes(8)), m.reg('r0', 0)))

    def parameter(self, m):
        parameter = self.model['params'][m.reg('r3')]
        m.write(m.reg('r2'), struct.pack('<6I', 0, 0, 0, parameter['type'], parameter['slot'], 0))
        m.reg('r0', 0)

    def metadata(self, m):
        slot = m.u32(m.reg('r1') + 16)
        parameter = next(parameter for parameter in self.model['params'] if parameter['slot'] == slot)
        assert self.strings[m.reg('r2')] == 'followEnable'
        value = parameter['meta'].get('followEnable')
        if value is None:
            m.reg('r0', 0)
        else:
            m.write(m.reg('r3'), struct.pack('<2I', 1, self.strings.index(value)))
            m.reg('r0', 1)

    def write(self, m):
        self.writes.append((m.reg('r1'), m.reg('r2'), m.read(m.reg('r3'), 1)[0],
                            m.u32(m.reg('r3') + 4)))
        m.reg('r0', 0)

    def bypass(self, level):
        self.writes.clear()
        assert self.m.call(0x28e06b4c, ROOT, DESCRIPTOR, int(level)) >= 0
        return list(self.writes)


@pytest.mark.firmware
@pytest.mark.parametrize('effect', MODELS, ids=lambda effect: effect.name)
def test_native_bypass_keeps_graph_running_and_delivers_hidden_enable(m4emu, registered, effect):
    native = NativeBypass(m4emu, registered, effect)
    for bypass in (True, False, True, False):
        assert native.bypass(bypass) == [(0x500, 0x123, 2, 0),
                                         (0x600, ENABLE_SLOT, 1, int(not bypass))]
        assert native.m.u32(BLOCK + 32) & 1 == int(not bypass)
    # Assigning another block object at the same grid location uses its own
    # live metadata/graph handles; there is no cached instance or polling state.
    native.m.u32(BLOCK + 52, 0x700)
    assert native.bypass(True)[-1] == (0x700, ENABLE_SLOT, 1, 0)


@pytest.mark.firmware
def test_ordinary_bypass_would_skip_audio_so_glasshouse_requires_native_kind24(m4emu, registered):
    native = NativeBypass(m4emu, registered, MODELS[0], self_bypass=False)
    assert native.bypass(True)[0] == (0x500, 0x123, 2, 3)
    assert native.bypass(False)[0] == (0x500, 0x123, 2, 0)


@pytest.mark.firmware
def test_without_model_follow_enable_flag_native_bypass_does_not_write_any_controls(m4emu, registered):
    native = NativeBypass(m4emu, registered, MODELS[0])
    native.m.u8(BLOCK + 104, 0)
    assert native.bypass(True) == [(0x500, 0x123, 2, 0)]


@pytest.mark.firmware
@pytest.mark.parametrize('effect', MODELS, ids=lambda effect: effect.name)
def test_native_edit_navigation_reaches_all_thirty_seven_visible_controls(m4emu, registered, effect):
    """Run real model-count lookup, Edit refresh and Page Right/Left routines.

    Graph membership and graphics are fixture seams; page counts, clamping and
    knob indices execute from the user's stock firmware against generated tables.
    """
    e0 = kit.get_entry_swapped(registered, 0)
    segments = kit._parse_e0_segments(e0)
    _, payload, size, address, _ = segments[6]
    m = m4emu.M4(e0[payload:payload+size], address)
    read = reader(e0)
    item, _ = effect_model.verify_model(registered, effect)
    view = 0x28600000
    # Boot normally builds this preset-ID -> Entry3-name-index lookup array.
    # Populate the live membership fixture; the native Table2 lookup remains real.
    model_lookup, = struct.unpack('<I', read(0x28e01d4c, 4))
    m.u32(model_lookup+4*effect.preset_id, item['words'][2])
    m.stub(0x28e24b78, lambda m: (m.write(m.reg('r0'), bytes([m.reg('r1') & 255])*m.reg('r2')),
                                 m.reg('r0', 0)))
    def selected(m):
        if m.reg('r0'):
            m.u8(m.reg('r0'), 0)
        m.reg('r0', 1)
    m.stub(0x28df0280, selected)
    m.stub(0x28d92a98, lambda m: m.reg('r0', 0))
    m.stub(0x28e05d34, lambda m: m.reg('r0', 0x28610000))
    m.stub(0x28e02190, lambda m: m.reg('r0', 1))
    m.stub(0x28e05c50, lambda m: m.reg('r0', 1))
    m.stub(0x28e07328, lambda m: (m.write(m.reg('r1'), struct.pack('<2I', 6, 0)), m.reg('r0', 0)))
    m.stub(0x28e07714, lambda m: m.reg('r0', 0))
    m.stub(0x28e07788, lambda m: m.reg('r0', 0))
    def block_descriptor(m):
        out = m.reg('r2')
        m.write(out, bytes(76))
        m.u32(out+12, effect.preset_id)
        m.u32(out+16, 0xffffffff)
        m.reg('r0', 0)
    m.stub(0x28e064f8, block_descriptor)
    m.stub(0x28e0f0ec, lambda m: (m.u8(m.reg('r3'), 3), m.reg('r0', 0)))
    m.stub(0x28d9e01c, lambda m: (m.write(m.reg('r1'), bytes(44)), m.reg('r0', 0)))
    for function in (0x28e07844, 0x28e0785c, 0x28dc5b5c, 0x28dc5964, 0x28dbea98,
                     0x28dc6010, 0x28dc6004, 0x28dc6688, 0x28dc66e0, 0x28dc6028,
                     0x28dc601c, 0x28dc651c, 0x28dc6534, 0x28dc6454, 0x28dc6504,
                     0x28dc6598, 0x28db8508):
        m.stub(function, lambda m: m.reg('r0', 0))
    controls = []
    m.stub(0x28dbf5c4, lambda m: (controls.append((m.reg('r0'), m.reg('r1'))), m.reg('r0', 0)))
    m.stub(0x28d96148, lambda m: m.reg('r0', 1))
    m.stub(0x28d96134, lambda m: m.reg('r0', 0))
    m.stub(0x28e0289c, lambda m: (m.write(m.reg('r2'), bytes(9)), m.reg('r0', 0)))
    m.u8(view+0x83, 1)
    assert m.call(0x28dbfac4, view, 0) == 0
    assert m.read(view+0x6e, 2) == bytes((0, 13))
    assert controls == [(0, 0), (1, 1), (2, 2)]
    all_indices = {index for _, index in controls}
    for page in range(1, 13):
        controls.clear()
        m.call(0x28dc0ca4, view)
        assert m.read(view+0x6e, 2) == bytes((page, 13))
        all_indices.update(index for _, index in controls)
    assert controls == [(0, 36)]
    assert item['params'][36]['name'] == 'Sag'
    assert all_indices == set(range(37))
    m.call(0x28dc0ca4, view)
    assert m.read(view+0x6e, 2) == bytes((12, 13))
    m.call(0x28dc0c00, view)
    assert m.read(view+0x6e, 2) == bytes((11, 13))
