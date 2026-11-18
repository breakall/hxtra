"""Native Controller Assign codec and ordinary shared-switch parameter writes.

Firmware code is read from the user's stock fixture at test time. Serialization,
MessagePack decoding, descriptor decoding, and ROM list manipulation execute;
stream I/O, heap allocation, locks and hardware notifications are isolated seams.
"""
import copy
import struct

import msgpack
import pytest

import hx_ctl
import microlooper_native as native
import patch_menu as pm
from firmware import reader, stock_e0, stock_entry
from microlooper_definition import MODELS

CM, BM = 0x28125d30, 0x28128b4c
STREAM, CONTEXT, CALLBACK, BUFFER = 0x28630000, 0x28630100, 0x28f80000, 0x28640000


class NativeControllers:
    def __init__(self, api):
        self.read = reader(stock_e0())
        self.m = api.M4(self.read(0x28d8fa80, 0xb005c), 0x28d8fa80)
        self.m.load(0x10001228, self.read(0x10001228, 0x300))
        self.m.reg('c1_c0_2', 0xf00000)
        self.m.reg('fpexc', 0x40000000)
        self.heap = 0x28700000
        m = self.m
        m.stub(0x28dadd50, self.allocate)
        m.stub(0x28dade24, lambda m: m.reg('r0', 0))
        m.stub(0x28dae7f8, lambda m: m.reg('r0', 0))
        m.stub(0x28e24c00, lambda m: m.reg('r0', 0))
        m.stub(0x28e24bb0, lambda m: m.reg('r0', 0))
        m.stub(0x28e24c78, lambda m: m.write(m.reg('r0'), m.read(m.reg('r1'), m.reg('r2'))))
        m.stub(0x28e24b78, lambda m: m.write(m.reg('r0'), bytes([m.reg('r1') & 255])*m.reg('r2')))
        m.stub(0x28d96084, lambda m: m.reg('r0', BM))
        m.stub(0x28dd8af4, lambda m: m.reg('r0', 0))
        m.stub(0x28dddef4, lambda m: m.reg('r0', 0))
        m.stub(0x28d96990, lambda m: m.reg('r0', 0))
        m.stub(0x28e1f844, lambda m: (m.u32(m.reg('r1')+4, 0), m.reg('r0', 0)))
        for controller in range(10):
            head = CM+12+8*controller
            m.u32(head, head); m.u32(head+4, head)
        for index in range(64):
            m.u8(CM+0xac+0x48*index+0x44, 0x40)

    def allocate(self, m):
        size, address = m.reg('r0'), self.heap
        self.heap += (size+7)//8*8
        assert self.heap < 0x287f0000
        m.write(address, bytes(size)); m.reg('r0', address)

    def add(self, controller, *, index=5, block=1, slot=0, snapshot=False):
        """Fields independently established by actual native0x28dded64."""
        m, head, node = self.m, CM+12+8*controller, CM+0xac+0x48*slot
        previous = m.u32(head+4)
        m.u32(node, head); m.u32(node+4, previous)
        m.u32(previous, node); m.u32(head+4, node)
        for offset, value in ((0x10, controller), (0x18, 1), (0x20, 1), (0x28, 0),
                              (0x38, 0), (0x40, int(snapshot)), (0x44, slot), (0x45, 1)):
            m.u8(node+offset, value)
        for offset, value in ((0x14, 0), (0x1c, 0), (0x24, 1), (0x2c, block),
                              (0x30, 0xfffffffe), (0x34, index), (0x3c, 0)):
            m.u32(node+offset, value)
        return node

    def encode(self):
        parts = []
        def write(m):
            assert m.reg('r0') == CONTEXT
            parts.append(m.read(m.reg('r1'), m.reg('r2')))
            m.reg('r0', m.reg('r2'))
        self.m.stub(CALLBACK, write)
        self.m.write(STREAM, struct.pack('<2I', CONTEXT, CALLBACK | 1))
        assert self.m.call(0x28de0d3c, CM, STREAM, 0) == 0
        return b''.join(parts)

    def decode(self, encoded):
        # The preset section reader passes its key followed by its value.
        payload = b'\x04'+encoded
        self.m.write(BUFFER, payload)
        assert self.m.call(0x28de0f24, CM, BUFFER, len(payload), 0) == 0


@pytest.mark.firmware
@pytest.mark.parametrize('controller', [3, 7])
@pytest.mark.parametrize('snapshot', [False, True])
def test_native_loop_controller_assignment_roundtrips_section_four(m4emu, controller, snapshot):
    engine = NativeControllers(m4emu)
    engine.add(controller, snapshot=snapshot)
    encoded = engine.encode()
    section = msgpack.unpackb(encoded, raw=False, strict_map_key=False)
    expected = [None]*10
    expected[controller] = [{0: 0, 1: {0: controller, 1: 0, 2: False, 3: True,
                           4: 0, 5: 1, 6: {28: 0, 29: 5, 41: False},
                           7: 0, 13: snapshot}}]
    assert section == expected
    restored = NativeControllers(m4emu)
    restored.decode(encoded)
    assert restored.encode() == encoded
    # Byte45 is transient: real native load clears it; allocation is byte44.
    assert restored.m.read(CM+0xac+0x44, 2) == bytes([0, 0])


@pytest.mark.firmware
@pytest.mark.parametrize('effect', MODELS, ids=lambda effect: effect.name)
def test_full_native_preset_keeps_loop_assignment_and_other_sections(m4emu, effect):
    factory = stock_entry(12)
    offset = factory.index(b'\xa9l6-helix\0')
    unpacker = msgpack.Unpacker(raw=False, strict_map_key=False, unicode_errors='surrogateescape')
    unpacker.feed(factory[offset:])
    unpacker.unpack(); unpacker.unpack(); unpacker.unpack()
    original = factory[offset:offset+unpacker.tell()]
    magic, sections = hx_ctl.decode_preset(original)
    sections = copy.deepcopy(sections)
    used = {row[0] for group in sections[4] if group for row in group}
    free = next(index for index in range(64) if index not in used)
    engine = NativeControllers(m4emu); engine.add(3, slot=free, snapshot=True)
    loop = msgpack.unpackb(engine.encode(), raw=False, strict_map_key=False)[3][0]
    old_controllers = copy.deepcopy(sections[4])
    sections[4][3] = [*(sections[4][3] or []), loop]
    parameters = [bool(p.default) if p.type == 1 else p.default for p in effect.parameters]+[False]
    hx_ctl.set_model(sections, 0, 0, effect.preset_id, params=parameters, kind=8)
    blob = hx_ctl.encode_preset(magic, sections, like=original)
    _, restored = hx_ctl.decode_preset(blob)
    assert restored[0][22][1][20][24][25] == effect.preset_id
    assert restored[4][3][-1] == loop
    assert all(restored[4][i] == old_controllers[i] for i in range(10) if i != 3)
    before, after = hx_ctl.raw_sections(original), hx_ctl.raw_sections(blob)
    assert all(after[k][1] == before[k][1] for k in before if k not in (0, 4))
    toc = struct.unpack_from('<12I', blob, 13)
    assert toc[-2:] == (len(blob), len(blob))
    for index, section in enumerate(hx_ctl.SECTION_ORDER, 1):
        if section in restored:
            assert blob[toc[index]] == section
    # Run the actual native parser against the resulting whole-file section4,
    # retaining its preexisting ordinary EXP assignment as well as new Loop.
    native_restored = NativeControllers(m4emu)
    native_restored.decode(after[4][1])
    assert msgpack.unpackb(native_restored.encode(), raw=False, strict_map_key=False) == restored[4]


@pytest.mark.firmware
@pytest.mark.parametrize('pressed', [False, True])
def test_native_switch_drives_loop_and_other_parameter_with_normal_bool_values(m4emu, pressed):
    engine = NativeControllers(m4emu)
    engine.add(3, index=5, block=1)
    engine.add(3, index=0, block=2, slot=1)
    m = engine.m
    # Run the real stock controller driver through the installed parameter
    # filter and original outer setter. Isolate the downstream graph mutation.
    patch = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    native.install(patch); patch.finish_chains()
    m.load(patch.cave.va, patch.cave.buf)
    patched = reader(patch.entry0())
    m.load(native.PARAMETER_FILTER_SITE, patched(native.PARAMETER_FILTER_SITE, 0x120))
    m.stub(0x28e07844, lambda m: m.reg('r0', 0))
    m.stub(0x28e0785c, lambda m: m.reg('r0', 0))
    m.stub(0x28d92a98, lambda m: m.reg('r0', 0))
    m.stub(0x28e07714, lambda m: m.reg('r0', 0))
    fs_node = 0x28650000
    m.u8(fs_node+0x20, int(pressed))
    m.stub(0x28dd77ac, lambda m: m.reg('r0', fs_node))
    m.stub(0x28e0f610, lambda m: (m.u8(m.reg('r3'), 0), m.reg('r0', 0)))
    m.stub(0x28e02644, lambda m: m.reg('r0', 0))
    writes = []
    def lower(m):
        descriptor, value = m.reg('r2'), m.reg('r3')
        writes.append((m.reg('r1'), struct.unpack('<2I', m.read(descriptor, 8)),
                       m.read(descriptor+8, 1), m.read(value, 2)))
        m.reg('r0', 0)
    m.stub(0x28e02040, lower)
    level = struct.unpack('<I', struct.pack('<f', float(not pressed)))[0]
    m.call(0x28dde408, CM, 3, 0, level)
    assert writes == [(block, (0xfffffffe, index), b'\0', bytes([1, int(pressed)]))
                      for block, index in ((1, 5), (2, 0))]
