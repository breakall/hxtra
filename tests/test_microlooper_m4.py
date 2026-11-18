"""Native transport writes, switch routing and ordinary bypass behavior."""
import struct

import pytest

import microlooper_native as microlooper
from microlooper_definition import MODELS

CODE, STATE, BINDING, WRITE = 0x28e60000, 0x28600000, 0x28600100, 0x28f90000
CTX, BLOCK = 0x12340000, 73


class Binding:
    def __init__(self, m4emu, model=380):
        self.model = model
        code, self.symbols = m4emu.assemble('src/m4/microlooper.s', [], {}, inc={'microlooper_models.inc': microlooper.asm_include()})
        self.m = m4emu.M4(code, CODE)
        self.writes, self.fail = [], False

        def write(m):
            self.writes.append(tuple(m.reg(f'r{i}') for i in range(4)))
            m.reg('r0', -1 if self.fail else 0)
        self.m.stub(WRITE, write)
        self.bind()

    def bind(self, block=BLOCK, generation=1, model=None, at=BINDING):
        model = self.model if model is None else model
        self.m.write(at, struct.pack('<5I', CTX, WRITE | 1, block, generation, model))

    def update(self, pressed=False, now=0, state=STATE, binding=BINDING):
        return self.m.call(CODE + self.symbols['microlooper_binding_update'],
                           state, int(pressed), now & 0xffffffff, binding)


    def ready(self):
        assert self.update() == 1
        assert self.writes == [(CTX, BLOCK, 7, 0), (CTX, BLOCK, 8, 0)]
        self.writes.clear()


@pytest.mark.parametrize('model', [effect.preset_id for effect in MODELS])
def test_tap_capture_hold_overdub_release_and_tap_resume_listening(m4emu, model):
    b = Binding(m4emu, model); b.ready()
    assert b.update(True, 10) == 1
    assert b.writes == []
    assert b.update(False, 20) == 1
    assert b.writes == [(CTX, BLOCK, 7, 1)]
    b.writes.clear()
    b.update(True, 30)
    b.update(True, 400029)
    assert b.writes == []
    b.update(True, 400030)
    b.update(True, 400031)
    assert b.writes == [(CTX, BLOCK, 8, 1)]
    b.update(False, 400032)
    b.update(False, 400033)
    assert b.writes == [(CTX, BLOCK, 8, 1), (CTX, BLOCK, 8, 0)]
    b.writes.clear()
    b.update(True, 400040)
    b.update(False, 400041)
    assert b.writes == [(CTX, BLOCK, 7, 0)]


def test_listening_hold_has_no_capture_or_overdub_and_duplicate_release_has_no_tap(m4emu):
    b = Binding(m4emu); b.ready()
    b.update(True, 10); b.update(True, 400010); b.update(False, 400020)
    b.update(False, 400021)
    assert b.writes == []


def test_new_binding_initializes_listen_and_stops_overdub_without_capturing(m4emu):
    b = Binding(m4emu); b.ready()
    b.update(True, 10); b.update(False, 20)
    b.update(True, 30); b.update(True, 400030)
    b.writes.clear()
    b.bind(generation=2)
    b.update(False, 400040)
    assert b.writes == [(CTX, BLOCK, 7, 0), (CTX, BLOCK, 8, 0)]
    assert b.m.u32(STATE + 16) == b.m.u32(STATE + 20) == 0
    b.writes.clear(); b.update(False, 400050)
    assert b.writes == []


def test_initial_pressed_level_is_not_a_restored_capture_command(m4emu):
    b = Binding(m4emu)
    b.update(True, 20)
    assert b.writes == [(CTX, BLOCK, 7, 0), (CTX, BLOCK, 8, 0)]
    b.writes.clear()
    b.update(True, 400020); b.update(False, 400021)
    assert b.writes == []


@pytest.mark.parametrize('foreign_model', [147, 555])
def test_non_microlooper_binding_does_not_consume_event_or_modify_state(m4emu, foreign_model):
    b = Binding(m4emu)
    b.bind(model=foreign_model)
    before = b.m.read(STATE, 32)
    assert b.update(True, 20) == 0
    assert b.m.read(STATE, 32) == before
    assert b.writes == []


def test_failed_writes_retry_without_overtaking_or_losing_tap(m4emu):
    b = Binding(m4emu); b.ready()
    b.update(True, 10)
    b.fail = True
    assert b.update(False, 20) == 5
    assert b.writes == [(CTX, BLOCK, 7, 1)]
    assert b.update(False, 21) == 5
    b.fail = False
    assert b.update(False, 22) == 1
    assert b.writes == [(CTX, BLOCK, 7, 1)] * 3
    assert b.m.u32(STATE + 24) == 0
    b.writes.clear(); b.update(False, 23)
    assert b.writes == []


def test_initial_listen_write_failure_prevents_overdub_write_until_retry(m4emu):
    b = Binding(m4emu); b.fail = True
    assert b.update(False, 0) == 5
    assert b.writes == [(CTX, BLOCK, 7, 0)]
    b.fail = False
    assert b.update(False, 1) == 1
    assert b.writes == [(CTX, BLOCK, 7, 0), (CTX, BLOCK, 7, 0), (CTX, BLOCK, 8, 0)]


def test_two_block_bindings_keep_independent_transport_and_sentinels(m4emu):
    b = Binding(m4emu)
    other_state, other_binding = STATE + 36, BINDING + 24
    b.m.write(STATE - 4, b'LEFT' + bytes(32) + b'MIDL' + bytes(32) + b'RGHT')
    b.bind(block=74, generation=2, at=other_binding)
    b.ready()
    b.update(False, 0, other_state, other_binding)
    b.writes.clear()
    b.update(True, 10); b.update(False, 20)
    b.update(True, 30); b.update(True, 400030)
    b.update(True, 400040, other_state, other_binding)
    b.update(False, 400050, other_state, other_binding)
    assert b.writes == [(CTX, BLOCK, 7, 1), (CTX, BLOCK, 8, 1), (CTX, 74, 7, 1)]
    assert b.m.read(STATE - 4, 4) == b'LEFT'
    assert b.m.read(STATE + 32, 4) == b'MIDL'
    assert b.m.read(other_state + 32, 4) == b'RGHT'


def test_wraparound_time_is_forwarded_to_gesture_without_a_long_press(m4emu):
    b = Binding(m4emu); b.ready()
    b.update(True, 0xffffff00); b.update(False, 0xffffff80)
    assert b.writes == [(CTX, BLOCK, 7, 1)]
    b.update(True, 0xfffffff0); b.update(True, 0xfffffff0 + 400000)
    assert b.writes[-1] == (CTX, BLOCK, 8, 1)


def test_atmosphere_is_opt_in_and_uses_one_feature_owner():
    import features
    mods = features.load()
    feature = next(m for m in mods if features.name(m) == 'microlooper')
    assert feature.FLAG == 'HX_MICRO_LOOPER' and feature.WEB is False
    assert feature not in features.enabled(mods, {})
    assert feature in features.enabled(mods, {'HX_MICRO_LOOPER': '1'})


@pytest.mark.firmware
@pytest.mark.parametrize('env', [{}, {'HX_LONG_PRESS': '1'}])
def test_ordinary_builds_preserve_native_handlers(env):
    from firmware import built
    read, on = built(env)
    assert 'microlooper' not in on
    assert read(microlooper.BYPASS_SITE, 4) == microlooper.BYPASS_STOCK
    assert read(microlooper.PARAMETER_FILTER_SITE, 4) == microlooper.PARAMETER_FILTER_STOCK
    assert struct.unpack('<I', read(microlooper.TICK_LITERAL, 4))[0] == microlooper.TICK_STOCK


@pytest.mark.firmware
@pytest.mark.parametrize('slot,value', [(7, 0), (7, 1), (8, 0), (8, 29)])
def test_native_bool_writer_runs_actual_stock_setter_and_preserves_typed_descriptor(m4emu, slot, value):
    from firmware import reader, stock_e0
    e0 = stock_e0(); read = reader(e0)
    b = Binding(m4emu)
    native = 0x28e04864
    assert read(native, 4) == bytes.fromhex('2de9 f043')
    b.m.load(native, read(native, 0x120))
    b.m.stub(0x28e07714, lambda m: m.reg('r0', 0))  # ordinary block path
    seen = []

    def lower(m):
        seen.append((m.reg('r0'), m.reg('r1'), m.read(m.reg('r2'), 12), m.read(m.reg('r3'), 5)))
        m.reg('r0', 0)
    b.m.stub(0x28e02040, lower)
    assert b.m.call(CODE + b.symbols['microlooper_native_write'], CTX, 1, slot, value) == 0
    assert seen == [(CTX, 1, struct.pack('<3I', 0xfffffffe, slot - 1, 0), bytes([1, bool(value), 0, 0, 0]))]


@pytest.mark.parametrize('slot', [1, 5, 6, 9])
def test_native_writer_rejects_non_transport_slots_without_calling_firmware(m4emu, slot):
    b = Binding(m4emu)
    assert b.m.call(CODE + b.symbols['microlooper_native_write'], CTX, 1, slot, 1) == 0xfffffffd


@pytest.mark.firmware
def test_stock_stomp_dispatch_confirms_type_one_node_and_block_field(m4emu):
    from firmware import reader, stock_e0
    read = reader(stock_e0())
    b = Binding(m4emu)
    native, obj, node = 0x28dd10c0, 0x28601000, 0x28602000
    assert read(native, 4) == bytes.fromhex('2de9 f04f')
    b.m.load(native, read(native, 0x3e0))
    head = obj + 0x20  # first footswitch sentinel, as native0x28dd71c4 computes
    b.m.u32(head, node)
    b.m.u32(node, head)
    b.m.u8(node + 9, 1)
    b.m.u32(node + 12, 5)
    b.m.stub(0x28d96084, lambda m: m.reg('r0', obj))
    b.m.stub(0x28dd71c4, lambda m: m.reg('r0', head))
    b.m.stub(0x28dd83a4, lambda m: m.reg('r0', 0))
    b.m.stub(0x28e24970)
    b.m.stub(0x28dd71e4, lambda m: m.reg('r0', 0))
    b.m.stub(0x28d92a98, lambda m: m.reg('r0', CTX))

    def clear(m):
        m.write(m.reg('r0'), bytes(m.reg('r2')))
    b.m.stub(0x28e24b78, clear)
    seen = []

    def lookup(m):
        seen.append((m.reg('r0'), m.reg('r1')))
        # The original branch exits cleanly on unknown block; no live native
        # DSP state or hardware access is necessary to establish this call ABI.
        m.reg('r0', -1)
    b.m.stub(0x28e0fe94, lookup)
    b.m.call(native, obj, 0)
    assert seen == [(CTX, 5)]


@pytest.mark.firmware
def test_stock_tick_listener_shares_queued_dispatch_and_preserves_native_tick(m4emu):
    from firmware import reader, stock_e0
    read = reader(stock_e0())
    b = Binding(m4emu)
    dispatch, tick = 0x28db8830, 0x28dd1014
    # Existing stomp class-3 listener, a concrete chain_ptr target. It is not
    # the deferred work callback at0x28dd18b0, which has no periodic cadence.
    assert read(0x28dd2944, 4) == struct.pack('<I', tick | 1)
    assert read(dispatch, 4) == bytes.fromhex('f8b5 0446')
    assert read(tick, 4) == bytes.fromhex('8b6d 10b5')
    b.m.load(dispatch, read(dispatch, 0x70))
    b.m.load(tick, read(tick, 0xac))
    event, obj = 0x28601000, 0x28602000
    first, observer, observe_fn = 0x28603000, 0x28603100, WRITE + 0x100
    head = 0x281f5d50 + 3 * 8
    b.m.write(event, bytes([3]) + bytes(7))
    b.m.u32(head, first)
    b.m.write(first, struct.pack('<4I', observer, head, tick | 1, obj))
    b.m.write(observer, struct.pack('<4I', head, first, observe_fn | 1, CTX))
    b.m.u32(obj + 0x58, 2)
    b.m.u8(obj + 0x70, 1)
    b.m.u32(obj + 0x74, 20)
    b.m.stub(0x28e249a0)
    b.m.stub(0x28e24a30)
    seen = []

    def observe(m):
        seen.append((m.reg('r0'), m.reg('r1')))
        assert m.u32(obj + 0x58) == 1
        assert m.u32(obj + 0x74) == 21
    b.m.stub(observe_fn, observe)
    b.m.call(dispatch, event)
    assert seen == [(event, CTX)]


@pytest.mark.firmware
@pytest.mark.parametrize('first_model', [380, 555])
def test_native_bypass_remains_stock_for_atmosphere_and_other_blocks(m4emu, first_model):
    import patch_menu as pm
    from firmware import reader, stock_e0
    patch = pm.Patch(stock_e0(), [], {})
    microlooper.install(patch); patch.finish_chains()
    read = reader(patch.entry0())
    b = Binding(m4emu)
    native, obj, first, second = 0x28dd10c0, 0x28601000, 0x28602000, 0x28602100
    b.m.load(native, read(native, 0x3e0))
    assert read(microlooper.BYPASS_SITE, 4) == microlooper.BYPASS_STOCK
    head = obj + 0x20
    b.m.u32(head, first)
    for node, next_node, block in ((first, second, 5), (second, head, 6)):
        b.m.u32(node, next_node)
        b.m.u8(node + 9, 1)
        b.m.u32(node + 12, block)
        b.m.u8(node + 32, 1)
        b.m.write(node + 33, b'RGB')
    b.m.stub(0x28d96084, lambda m: m.reg('r0', obj))
    b.m.stub(0x28dd71c4, lambda m: m.reg('r0', head))
    b.m.stub(0x28dd83a4, lambda m: m.reg('r0', 0))
    b.m.stub(0x28e24970)
    b.m.stub(0x28e24ae8)
    b.m.stub(0x28dd71e4, lambda m: m.reg('r0', 0))
    b.m.stub(0x28d92a98, lambda m: m.reg('r0', CTX))

    def clear(m):
        m.write(m.reg('r0'), bytes(m.reg('r2')))
    b.m.stub(0x28e24b78, clear)

    def lookup(m):
        model = first_model if m.reg('r1') == 5 else 777
        m.write(m.reg('r2'), bytes([0]) + struct.pack('<I', model) + bytes(47))
        m.reg('r0', 0)
    b.m.stub(0x28e0fe94, lookup)

    def colour_index(m):
        m.u8(m.reg('r3'), 0)
        m.reg('r0', 0)
    b.m.stub(0x28e0f0ec, colour_index)
    colour = 0x28604000
    b.m.write(colour, b'NEW')
    b.m.stub(0x28db7e1c, lambda m: m.reg('r0', colour))
    sent = []

    def bypass(m):
        sent.append((m.reg('r0'), m.reg('r1'), m.reg('r2'), m.reg('r3')))
        m.reg('r0', 0)
    b.m.stub(0x28e0f884, bypass)
    b.m.call(native, obj, 0)
    assert sent == [(CTX, block, 1, 1) for block in (5, 6)]
    assert b.m.read(first + 32, 4) == b'\x00NEW'
    assert b.m.read(second + 32, 4) == b'\x00NEW'


def install_parameter_filter(b, read):
    import patch_menu as pm
    native = microlooper.PARAMETER_FILTER_SITE
    assert read(native, 4) == microlooper.PARAMETER_FILTER_STOCK
    b.m.load(native, read(native, 0x120))
    b.m.load(native, pm.thumb_bw(native, CODE + b.symbols['microlooper_native_parameter_filter']))
    b.m.stub(0x28e07714, lambda m: m.reg('r0', 0))


@pytest.mark.firmware
@pytest.mark.parametrize('model,selector,index,allowed', [
    (147, -2, 6, True), (555, -2, 6, True),
    (380, -2, 5, True), (381, -2, 5, True),  # public Loop remains an ordinary parameter
    (380, -2, 6, False), (381, -2, 6, False),
    (380, -2, 7, False), (381, -2, 7, False),
    (380, 380, 6, False), (381, 381, 7, False),
    (380, -2, 4, True), (381, -3, 6, True), (380, -3, 7, True),
])
def test_native_parameter_filter_blocks_external_transport_only(m4emu, model, selector, index, allowed):
    from firmware import reader, stock_e0
    b = Binding(m4emu)
    install_parameter_filter(b, reader(stock_e0()))
    descriptor, value = BINDING + 0x100, BINDING + 0x120
    b.m.write(descriptor, struct.pack('<3I', selector & 0xffffffff, index, 1))
    b.m.write(value, b'\x01\x01\x00\x00\x00')

    def lookup(m):
        assert (m.reg('r0'), m.reg('r1')) == (CTX, 1)
        m.write(m.reg('r2'), bytes([0]) + struct.pack('<I', model) + bytes(47))
        m.reg('r0', 0)
    b.m.stub(0x28e0fe94, lookup)
    seen = []

    def lower(m):
        seen.append(tuple(m.reg(f'r{i}') for i in range(4)))
        m.reg('r0', 17)
    b.m.stub(0x28e02040, lower)
    assert b.m.call(microlooper.PARAMETER_FILTER_SITE, CTX, 1, descriptor, value) == (17 if allowed else 0)
    assert seen == ([(CTX, 1, descriptor, value)] if allowed else [])


@pytest.mark.firmware
def test_native_parameter_filter_authorizes_only_actual_native_writer_return_address(m4emu):
    from firmware import reader, stock_e0
    b = Binding(m4emu)
    install_parameter_filter(b, reader(stock_e0()))
    # Authorized writer skips the model query; a stub is intentionally absent.
    seen = []

    def lower(m):
        seen.append((m.reg('r0'), m.reg('r1'), m.read(m.reg('r2'), 12), m.read(m.reg('r3'), 5)))
        m.reg('r0', 0)
    b.m.stub(0x28e02040, lower)
    assert b.m.call(CODE + b.symbols['microlooper_native_write'], CTX, 1, 7, 1) == 0
    assert seen == [(CTX, 1, struct.pack('<3I', 0xfffffffe, 6, 0), b'\x01\x01\x00\x00\x00')]


@pytest.mark.firmware
def test_native_parameter_filter_handles_actual_getter_success_without_info_for_invalid_block(m4emu):
    from firmware import reader, stock_e0
    b = Binding(m4emu)
    read = reader(stock_e0())
    b.m.load(0x28e0fe94, read(0x28e0fe94, 0x100))
    b.m.stub(0x28e07714, lambda m: m.reg('r0', 0))
    b.m.stub(0x28e05d34, lambda m: m.reg('r0', 0x28608000))
    b.m.stub(0x28e02190, lambda m: m.reg('r0', 1))
    b.m.stub(0x28e05c50, lambda m: m.reg('r0', 1))
    b.m.stub(0x28e07328, lambda m: m.reg('r0', -3))
    node, out = BINDING + 0x100, BINDING + 0x200
    b.m.write(out, b'?' * 52)
    assert b.m.call(0x28e0fe94, CTX, 0xffffffff, out) == 0
    assert b.m.read(out, 52) == b'?' * 52  # stock success0 does not imply filled record
    install_parameter_filter(b, read)
    descriptor, value = BINDING + 0x300, BINDING + 0x320
    b.m.write(descriptor, struct.pack('<3I', 0xfffffffe, 6, 1))
    b.m.write(value, b'\x01\x01\x00\x00\x00')
    b.m.u32(m4emu.STACK_TOP - 96 + 1, 380)
    b.m.stub(0x28e02040, lambda m: m.reg('r0', -3))
    assert b.m.call(microlooper.PARAMETER_FILTER_SITE, CTX, 0xffffffff, descriptor, value) == 0xfffffffd


@pytest.mark.parametrize('capacity', [0, 1, 3])
def test_native_assignment_snapshot_copies_explicit_loop_ids_under_controller_lock(m4emu, capacity):
    b = Binding(m4emu)
    b.m.stub(0x28d96084, lambda m: m.reg('r0', 0x28128b4c))
    b.m.stub(0x28dd83c4, lambda m: m.reg('r0', 1))
    manager, out = 0x28601000, 0x28604000
    nodes = [manager+0xac+0x48*i for i in range(64)]
    for node in nodes:
        b.m.u8(node+0x44, 0x40)
    for index, block in ((0, 5), (1, 20), (2, 21), (3, 7), (4, 99), (5, 33), (6, 44)):
        node = nodes[index]
        b.m.u8(node+0x10, 5)  # FS3: controller switch_index+3
        b.m.u8(node+0x18, 1); b.m.u32(node+0x1c, 0)
        b.m.u8(node+0x20, 1); b.m.u32(node+0x24, 1)
        b.m.u8(node+0x28, 0); b.m.u32(node+0x2c, block)
        b.m.u32(node+0x30, 0xfffffffe); b.m.u32(node+0x34, 5)
        b.m.u8(node+0x38, 0); b.m.u32(node+0x3c, 0)
        b.m.u8(node+0x44, index); b.m.u8(node+0x45, 1)
    b.m.u8(nodes[1]+0x28, 2)  # a standard bypass-controller assignment
    b.m.u32(nodes[2]+0x34, 4)  # ordinary Mix, not Loop
    b.m.u8(nodes[4]+0x44, 0x40)
    b.m.u32(nodes[5]+0x30, 0xfffffffd)  # secondary model
    b.m.u32(nodes[6]+0x1c, 1); b.m.u32(nodes[6]+0x24, 0)  # reversed bounds
    b.m.write(out-4, b'LEFT'+b'?'*12+b'RGHT')
    order = []

    def lock(m):
        assert m.reg('r0') == manager+4
        assert m.read(out, 12) == b'?'*12
        order.append('lock')

    def unlock(m):
        assert m.reg('r0') == manager+4
        assert m.read(out, min(capacity, 2)*4) == struct.pack('<2I', 5, 7)[:capacity*4]
        order.append('unlock')
        for node in nodes:
            m.write(node, b'\xff'*0x48)
    b.m.stub(0x28e24c00, lock)
    b.m.stub(0x28e24bb0, unlock)
    assert b.m.call(CODE+b.symbols['microlooper_native_assignment_ids'], manager, 2, out, capacity) == 2
    assert order == ['lock', 'unlock']
    assert b.m.read(out-4, 4) == b'LEFT'
    assert b.m.read(out+min(capacity, 2)*4, 12-min(capacity, 2)*4) == b'?'*(12-min(capacity, 2)*4)
    assert b.m.read(out+12, 4) == b'RGHT'


def test_invalid_switch_assignment_snapshot_does_not_call_firmware(m4emu):
    b = Binding(m4emu)
    assert b.m.call(CODE + b.symbols['microlooper_native_assignment_ids'], 0, 5, 0, 0) == 0


@pytest.mark.parametrize('model', [effect.preset_id for effect in MODELS])
def test_replacing_variant_with_reused_handle_and_generation_resets_transport(m4emu, model):
    b = Binding(m4emu, model); b.ready()
    b.update(True, 10); b.update(False, 20)
    b.update(True, 30); b.update(True, 400030)
    b.writes.clear()
    replacement = next(effect.preset_id for effect in MODELS if effect.preset_id != model)
    b.bind(model=replacement)
    b.update(True, 400040)
    assert b.writes == [(CTX, BLOCK, 7, 0), (CTX, BLOCK, 8, 0)]
    assert b.m.u32(STATE + 28) == replacement
    b.writes.clear(); b.update(False, 400050)
    assert b.writes == [], 'release from the old variant cannot capture'
