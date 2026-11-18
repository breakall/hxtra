"""Native-route controller, ownership boundaries, and stock recursive mutex."""
import hashlib
import struct

import pytest

import microlooper_native as native
from microlooper_definition import MODELS
import patch_menu as pm
from firmware import reader, stock_e0, stock_entry

CODE, OBJ, DSP, TABLE = 0x28e60000, 0x28128a80, 0x28500000, 0x28510000
MANAGER = 0x28128b4c  # native getter 0x28d96084; distinct from the UI listener context
CONTROLLERS = 0x28125d30  # native parameter Controller Assign manager, getter0x28d9608c
EVENT, STOCK, LP, THREAD = 0x28f50000, 0x28f90000, 0x28f90010, 0x28f70000


class Controller:
    def __init__(self, api, installed=None, model=380):
        self.api = api
        self.model = model
        if installed is None:
            code, self.sym = api.assemble(native.MODULE, [], {}, inc={'microlooper_models.inc': native.asm_include()})
            self.base = CODE
            self.m = api.M4(code, CODE)
        else:
            patch, report = installed
            self.base = report['module_va']
            self.sym = {symbol: address - self.base for symbol, address in report.items() if symbol.startswith('microlooper_')}
            self.m = api.M4(patch.cave.buf, patch.cave.va)
        self.now, self.mode, self.depth, self.assignment_depth = 0, 0, 0, 0
        self.assignments, self.models, self.bypass, self.writes = {}, {}, {}, []
        self.stock_events, self.lp_events, self.fail = [], [], False
        self.lock_order = []
        self.on_assignment_unlock = None
        m = self.m
        m.u32(0x28449e78, DSP)
        m.u32(DSP + 0x4400, TABLE)
        for fs in range(5):
            m.u8(0x28128a74 + 2 * fs, 2)
            m.u32(MANAGER + (fs + 1) * 32, MANAGER + (fs + 1) * 32)
        for index in range(64):
            m.u8(CONTROLLERS+0xac+0x48*index+0x44, 0x40)
        m.stub(0x28d96084, lambda m: m.reg('r0', MANAGER))
        m.stub(0x28d9608c, lambda m: m.reg('r0', CONTROLLERS))
        m.stub(0x28dd83c4, self.get_momentary)
        m.stub(0x28e07844, self.lock)
        m.stub(0x28e0785c, self.unlock)
        m.stub(0x28e24c00, lambda m: self.assignment_lock(m, 1))
        m.stub(0x28e24bb0, lambda m: self.assignment_lock(m, -1))
        m.stub(0x28e1f844, self.setting)
        m.stub(0x28e0fe94, self.info)
        m.stub(0x28e04514, self.get_bypass)
        m.stub(0x28e04864, self.write)
        m.stub(0x28da6458, lambda m: m.reg('r0', self.now))
        m.stub(STOCK, self.stock)
        m.stub(LP, self.long_press)

    def at(self, symbol):
        return self.base + self.sym[symbol]

    def lock(self, m):
        assert m.reg('r0') == 0 and self.assignment_depth == 0
        self.depth += 1
        self.lock_order.append(('graph', 1, self.assignment_depth))
        m.reg('r0', 0)

    def unlock(self, m):
        assert m.reg('r0') == 0 and self.depth > 0
        self.depth -= 1
        self.lock_order.append(('graph', -1, self.assignment_depth))
        m.reg('r0', 0)

    def assignment_lock(self, m, change):
        assert m.reg('r0') == CONTROLLERS + 4 and self.depth == 0
        self.assignment_depth += change
        assert self.assignment_depth >= 0
        self.lock_order.append(('controller', change, self.depth))
        if change == -1 and self.on_assignment_unlock is not None:
            callback, self.on_assignment_unlock = self.on_assignment_unlock, None
            callback()
        m.reg('r0', 0)

    def get_momentary(self, m):
        assert m.reg('r0') == MANAGER and m.reg('r1') < 5 and self.depth == self.assignment_depth == 0
        m.reg('r0', m.read(MANAGER+0x28+32*m.reg('r1'), 1)[0])

    def setting(self, m):
        if m.reg('r0') == 21:
            value = self.mode
        else:
            value = 1            # real long_press virtual Hold action: tuner
        m.u32(m.reg('r1') + 4, value)
        m.reg('r0', 0)

    def info(self, m):
        assert m.reg('r0') == 0 and self.depth
        block = m.reg('r1')
        if block not in self.models:
            m.reg('r0', -3)
        else:
            m.write(m.reg('r2') + 1, struct.pack('<I', self.models[block]))
            m.reg('r0', 0)

    def get_bypass(self, m):
        assert m.reg('r0') == 0 and self.depth
        m.u8(m.reg('r2'), self.bypass.get(m.reg('r1'), 0))
        m.reg('r0', 0)

    def write(self, m):
        assert m.reg('r0') == 0 and self.depth
        descriptor, value = m.reg('r2'), m.reg('r3')
        assert m.u32(descriptor) == 0xfffffffe and m.read(value, 1) == b'\x01'
        self.writes.append((m.reg('r1'), m.u32(descriptor + 4) + 1, m.read(value + 1, 1)[0]))
        m.reg('r0', -19 if self.fail else 0)

    def stock(self, m):
        cls, key, _, _, kind = struct.unpack('<4BI', m.read(m.reg('r0'), 8))
        self.stock_events.append((key, kind))
        if cls == 1 and 12 <= key <= 16 and kind in (1, 2):
            m.u8(OBJ + 0x78 + key - 12, kind == 1)
        m.reg('r0', 0)

    def long_press(self, m):
        self.lp_events.append(m.read(m.reg('r0'), 8))
        self.stock(m)

    def add(self, block=1, model=None, obj=None):
        self.models[block] = self.model if model is None else model
        slot = block - 1 if block <= 8 else block - 3
        obj = 0x28600000 + slot * 0x1000 if obj is None else obj
        self.m.u32(DSP + 0x14 + slot * 0x54, slot)
        self.m.u32(TABLE + 0x24 + slot * 4, obj)
        self.m.u8(obj + 5, 1)
        self.m.u32(obj + 0x24, 3)
        self.m.u32(obj + 0x9f0, 0x28700000 + slot * 0x100)
        return obj

    def assign_bypass(self, fs, blocks):
        """Stock kind1 Bypass Assign nodes, independent of Loop routing."""
        sentinel = MANAGER + (fs + 1) * 32
        nodes = [0x28f10000 + fs * 0x1000 + n * 0x38 for n in range(len(blocks))]
        self.m.u32(sentinel, nodes[0] if nodes else sentinel)
        for n, block in enumerate(blocks):
            self.m.u32(nodes[n], nodes[n + 1] if n + 1 < len(nodes) else sentinel)
            self.m.u8(nodes[n] + 9, 1)
            self.m.u32(nodes[n] + 12, block)

    def assign(self, fs, blocks, *, momentary=True):
        """Explicit Loop Controller Assign plus requested per-FS test setup.

        Native constructor0x28dded64 uses64 0x48-byte nodes; primary ordinary
        parameter descriptors are{-2,index5,flag0,secondary0}, controllerFS+3.
        Momentary is the shared native per-switch setting, not a per-node bit.
        """
        self.assignments[fs] = list(blocks)
        self.m.u8(MANAGER+0x28+32*fs, int(momentary))
        for index in range(64):
            node = CONTROLLERS+0xac+0x48*index
            self.m.write(node, bytes(0x48))
            self.m.u8(node+0x44, 0x40)
        index = 0
        for switch, ids in self.assignments.items():
            for block in ids:
                assert index < 64
                node = CONTROLLERS+0xac+0x48*index
                self.m.u8(node+0x10, switch+3)
                self.m.u8(node+0x18, 1)
                self.m.u32(node+0x1c, 0)
                self.m.u8(node+0x20, 1)
                self.m.u32(node+0x24, 1)
                self.m.u8(node+0x28, 0)
                self.m.u32(node+0x2c, block)
                self.m.u32(node+0x30, 0xfffffffe)
                self.m.u32(node+0x34, 5)
                self.m.u8(node+0x38, 0)
                self.m.u32(node+0x3c, 0)
                self.m.u8(node+0x44, index)
                self.m.u8(node+0x45, 1)
                index += 1

    def key(self, kind, fs=0, lp=True):
        self.m.write(EVENT, struct.pack('<4BI', 1, fs + 12, 0, 0, kind))
        self.m.call(self.at('microlooper_controller_key'), EVENT, OBJ, STOCK | 1, LP | 1 if lp else 0)
        assert self.depth == self.assignment_depth == 0

    def tick(self):
        self.m.write(EVENT, bytes([3]) + bytes(7))
        self.m.call(self.at('microlooper_controller_tick'), EVENT, OBJ)
        assert self.depth == self.assignment_depth == 0

    def routes(self):
        return [self.m.read(self.at('microlooper_controller_routes') + 80 * n, 80) for n in range(40)
                if self.m.u32(self.at('microlooper_controller_routes') + 80 * n + 56)]


@pytest.fixture(params=[effect.preset_id for effect in MODELS])
def controller(m4emu, request):
    return Controller(m4emu, model=request.param)


@pytest.mark.parametrize('bypass_only', [False, True])
def test_unassigned_or_bypass_only_block_has_no_automatic_loop_route(controller, bypass_only):
    c = controller; c.add()
    if bypass_only:
        c.assign_bypass(0, [1])
    before = c.m.read(MANAGER+0x28, 1)
    c.key(1, lp=False); c.key(2, lp=False); c.tick()
    assert c.writes == [] and c.routes() == []
    assert c.stock_events == [(12, 1), (12, 2)]
    assert c.m.read(MANAGER+0x28, 1) == before


def test_loop_requires_explicit_momentary_without_changing_the_shared_setting(controller):
    c = controller; c.add(); c.assign(0, [1], momentary=False)
    c.tick(); c.key(1); c.now = 400000; c.tick(); c.key(2)
    assert c.writes == [] and c.routes() == []
    assert c.m.read(MANAGER+0x28, 1) == b'\0'


def test_graph_mutation_between_assignment_copy_and_drive_cannot_create_a_gesture(controller):
    c = controller; c.add(); c.assign(0, [1]); c.tick()
    c.key(1); c.key(2); c.key(1); c.now = 400000; c.writes.clear()
    generation = c.at('microlooper_controller_graph_epoch')
    def mutation():
        assert c.depth == c.assignment_depth == 0
        c.m.u32(generation, c.m.u32(generation)+1)
    c.on_assignment_unlock = mutation
    c.tick()
    assert all(slot == 8 and value == 0 for _, slot, value in c.writes)
    assert struct.unpack_from('<I', c.routes()[0], 16)[0] == 1
    c.writes.clear(); c.key(2)
    assert c.writes == [], 'an old held release cannot capture after a graph epoch race'


def test_unrelated_binding_generation_change_does_not_interrupt_overdub(controller):
    c = controller; c.add(); c.assign(0, [1]); c.tick()
    c.key(1); c.key(2); c.key(1); c.now = 400000; c.tick(); c.writes.clear()
    generation = c.at('microlooper_controller_generation')
    c.on_assignment_unlock = lambda: c.m.u32(generation, c.m.u32(generation)+1)
    c.tick()
    assert c.writes == []
    assert struct.unpack_from('<I', c.routes()[0], 20)[0] == 1
    c.key(2)
    assert c.writes == [(1, 8, 0)]


@pytest.mark.parametrize('level', [False, True])
def test_restored_loop_parameter_level_cannot_synthesize_a_physical_tap(controller, level):
    c = controller; c.add(); c.assign(0, [1]); c.tick(); c.writes.clear()
    stock = reader(stock_e0())
    # Enter the real parameter filter directly; its pass path executes the
    # original native setter body, without replacing the owned-writer stub.
    c.m.load(native.PARAMETER_FILTER_SITE+4, stock(native.PARAMETER_FILTER_SITE+4, 0x11c))
    c.m.stub(0x28e07714, lambda m: m.reg('r0', 0))
    levels = []
    def lower(m):
        descriptor, value = m.reg('r2'), m.reg('r3')
        assert struct.unpack('<2I', m.read(descriptor, 8)) == (0xfffffffe, 5)
        levels.append(m.read(value, 2))
        m.reg('r0', 0)
    c.m.stub(0x28e02040, lower)
    descriptor, value = 0x28f51000, 0x28f51020
    c.m.write(descriptor, struct.pack('<3I', 0xfffffffe, 5, 0))
    c.m.write(value, bytes([1, int(level), 0, 0, 0]))
    assert c.m.call(c.at('microlooper_native_parameter_filter'), 0, 1, descriptor, value) == 0
    c.tick()
    assert levels == [bytes([1, int(level)])] and c.writes == []
    assert struct.unpack_from('<I', c.routes()[0], 16)[0] == 0
    c.key(1); c.key(2)
    assert c.writes == [(1, 7, 1)]


def test_discovers_deduplicates_and_tap_hold_routes_all_micro_instances(controller):
    c = controller
    for block in (1, 2, 11):
        c.add(block)
    c.assign(0, [1, 1, 2]); c.assign(1, [11])
    c.key(1)
    assert c.writes == [(1, 7, 0), (1, 8, 0), (2, 7, 0), (2, 8, 0), (11, 7, 0), (11, 8, 0)]
    assert len(c.routes()) == 3 and not c.lp_events
    c.writes.clear(); c.now = 100; c.key(2)
    assert c.writes == [(1, 7, 1), (2, 7, 1)]
    c.now = 200; c.key(1); c.now = 400200; c.tick()
    assert c.writes[-2:] == [(1, 8, 1), (2, 8, 1)]
    c.key(5)
    assert (12, 5) not in c.stock_events and not c.lp_events
    c.now += 1; c.key(2)
    assert c.writes[-2:] == [(1, 8, 0), (2, 8, 0)]
    c.key(1, 1); c.key(2, 1)
    assert c.writes[-1] == (11, 7, 1)


def test_one_block_shared_by_two_switches_has_one_transport(controller):
    c = controller; c.add(); c.assign(0, [1]); c.assign(1, [1])
    c.tick(); c.writes.clear()
    c.key(1, 0); c.key(1, 1); c.key(2, 0)
    assert c.writes == []
    c.key(2, 1)
    assert c.writes == [(1, 7, 1)] and len(c.routes()) == 1


@pytest.mark.parametrize('reason', ['mode', 'function', 'bypass', 'unassign'])
def test_eligibility_change_cancels_and_disarms_until_release(controller, reason):
    c = controller; c.add(); c.assign(0, [1]); c.tick()
    c.key(1); c.key(2); c.key(1); c.now = 400000; c.tick()
    c.writes.clear()
    if reason == 'mode': c.mode = 2
    elif reason == 'function': c.m.u8(0x28128a74, 1)
    elif reason == 'bypass': c.bypass[1] = 1
    else: c.assign(0, [])
    c.tick()
    assert c.writes == [(1, 8, 0)] and len(c.routes()) == 1
    c.mode = 0; c.m.u8(0x28128a74, 2); c.bypass[1] = 0; c.assign(0, [1])
    c.now += 1; c.tick(); c.writes.clear(); c.key(2)
    assert c.writes == [], 'release of the old held input cannot capture after rebind'
    assert struct.unpack_from('<I', c.routes()[0], 16)[0] == 1, 'same DSP allocation must keep playing'


def test_other_switches_and_direct_stock_fallback_preserve_events(controller):
    c = controller; c.add(); c.assign(0, [1])
    c.key(1, 1); c.key(2, 1)
    assert len(c.lp_events) == 2
    c.key(1, 2, lp=False); c.key(2, 2, lp=False)
    assert c.stock_events[-2:] == [(14, 1), (14, 2)]


def test_object_invalidation_is_before_reuse_and_does_not_stop_unrelated_block(controller):
    c = controller; obj = c.add(); c.add(2); c.assign(0, [1]); c.assign(1, [2]); c.tick()
    c.key(1); c.key(2); c.key(1); c.now = 400000; c.tick(); c.writes.clear()
    c.m.call(c.at('microlooper_controller_object_before'), DSP + 0x43fc, obj)
    assert c.depth == 1 and c.writes == [(1, 8, 0)]
    c.m.call(c.at('microlooper_controller_unlock'))
    assert len(c.routes()) == 2
    # A successful initializer is an independent allocation epoch, even if the
    # native allocator reuses both object and runtime-link addresses.
    c.m.call(c.at('microlooper_controller_lock'))
    c.m.call(c.at('microlooper_controller_after'), 0, obj, 1)
    assert len(c.routes()) == 1
    c.tick()
    assert c.writes[-2:] == [(1, 7, 0), (1, 8, 0)]
    c.writes.clear(); c.key(2)
    assert c.writes == []


def test_initial_short_held_rebind_is_disarmed(controller):
    c = controller; c.add(); c.assign(0, [1]); c.m.u8(OBJ + 0x78, 1)
    c.tick(); c.writes.clear(); c.now = 1; c.key(2)
    assert c.writes == []


def test_assignment_change_while_released_accepts_the_next_fresh_press(controller):
    c = controller; c.add(); c.assign(0, [1]); c.tick(); c.key(1); c.key(2)
    c.assign(0, []); c.assign(1, [1]); c.writes.clear()
    c.key(1, 1); c.key(2, 1)
    assert c.writes == [(1, 7, 0)], 'new assigned switch should respond on its first fresh tap'


def test_install_uses_guarded_native_entries(m4emu):
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    report = native.install(p)
    assert report['microlooper_controller_key'] and not report['shared_long_press']
    p.finish_chains()
    assert p.u32(native.TICK_LITERAL) != native.TICK_STOCK


def test_actual_rom_mutex_counts_same_task_recursion(m4emu):
    read = reader(stock_e0())
    m = m4emu.M4(read(0x100003b0, 0x460), 0x100003b0)
    m.stub(0x100003c8, lambda m: m.reg('r0', 0))  # task context
    m.stub(0x100003b0, lambda m: m.reg('r0', 0))  # save interrupt state
    m.stub(0x100003c0)                           # restore interrupt state
    m.stub(0x100007c8, lambda m: m.reg('r0', THREAD))
    m.stub(0x100007bc, lambda m: m.reg('r0', 0))
    mutex = 0x28f60000
    assert m.call(0x100004f4, mutex) == 0
    assert m.call(0x10000500, mutex) == 0
    assert (m.u32(mutex), m.u32(mutex + 4)) == (THREAD, 1)
    assert m.call(0x10000500, mutex) == 0
    assert (m.u32(mutex), m.u32(mutex + 4)) == (THREAD, 2)
    assert m.call(0x100005b4, mutex) == 0
    assert (m.u32(mutex), m.u32(mutex + 4)) == (THREAD, 1)
    assert m.call(0x100005b4, mutex) == 0
    assert (m.u32(mutex), m.u32(mutex + 4)) == (0, 0)


def test_real_native_mutation_failure_preserves_live_playback_with_off_retries(m4emu):
    entry, error = 0x28dfc2c4, -45
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    report = native.install(p); p.finish_chains()
    c = Controller(m4emu, installed=(p, report))
    obj = c.add(); c.assign(0, [1]); c.tick()
    c.key(1); c.key(2); c.key(1); c.now = 400000; c.tick()
    c.writes.clear(); c.fail = True
    patched_read = reader(p.entry0())
    c.m.load(entry, patched_read(entry, 0x600 if entry == 0x28dfc2c4 else 0xd4))
    descriptor = 0x28f5f000
    c.m.write(descriptor, bytes(16))  # invalid constructor kind; destructor has no owner
    assert c.m.call(entry, DSP + 0x43fc, obj, descriptor) == error & 0xffffffff
    assert c.depth == 0 and c.writes == [(1, 8, 0)]
    c.tick()
    assert c.writes[-1] == (1, 8, 0)
    assert len(c.routes()) == 1
    c.fail = False; c.tick()
    assert all(slot == 8 and value == 0 for _, slot, value in c.writes)
    c.writes.clear(); c.key(2)
    assert c.writes == []


def test_failed_eligibility_cancel_retries_without_old_hold_or_capture(controller):
    c = controller; c.add(); c.assign(0, [1]); c.tick()
    c.key(1); c.key(2); c.key(1); c.now = 400000; c.tick()
    c.fail = True; c.mode = 2; c.writes.clear(); c.tick(); c.tick()
    assert c.writes and all(write == (1, 8, 0) for write in c.writes)
    c.mode = 0; c.tick()
    assert c.writes[-1] == (1, 8, 0)
    c.fail = False; c.tick(); c.writes.clear(); c.key(2)
    assert c.writes == []


def test_actual_native_bool_setter_recurses_graph_lock_then_restores_outer_owner(m4emu):
    read = reader(stock_e0())
    code, symbols = m4emu.assemble(native.MODULE, [], {}, inc={'microlooper_models.inc': native.asm_include()})
    m = m4emu.M4(code, CODE)
    for address, size in ((0x100003b0, 0x460), (0x100034b0, 0x2c),
                          (0x28e24bb0, 8), (0x28e24c00, 8), (0x28e07844, 48),
                          (0x28e04864, 0x120), (0x28e02040, 0xf0)):
        m.load(address, read(address, size))
    for address in (0x100003b0, 0x100003c0, 0x100003c8):
        m.stub(address, lambda m: m.reg('r0', 0))
    m.stub(0x100007c8, lambda m: m.reg('r0', THREAD))
    m.stub(0x100007bc, lambda m: m.reg('r0', 0))
    m.u32(0x28449e78, DSP); m.u8(0x2843ebb8, 2)
    m.stub(0x28e05d34, lambda m: m.reg('r0', DSP))
    m.stub(0x28e05c50, lambda m: m.reg('r0', 1))
    m.stub(0x28e07714, lambda m: m.reg('r0', 0))
    def resolve(m):
        m.write(m.reg('r1'), struct.pack('<2I', 6, 0)); m.reg('r0', 0)
    m.stub(0x28e07328, resolve)
    m.stub(0x28e07788, lambda m: m.reg('r0', 0))
    m.stub(0x28e07f80, lambda m: m.reg('r0', 0))
    def lower(m):
        assert m.u32(DSP + 12) == 2, 'actual setter acquired the same mutex recursively'
        m.reg('r0', -19)
    m.stub(0x28e08454, lower)
    assert m.call(0x28e07844, 0) == 0
    assert m.u32(DSP + 12) == 1
    assert m.call(CODE + symbols['microlooper_native_write'], 0, 1, 7, 0) == (-19 & 0xffffffff)
    assert m.u32(DSP + 8) == THREAD and m.u32(DSP + 12) == 1
    assert m.call(0x28e0785c, 0) == 0
    assert m.u32(DSP + 8) == m.u32(DSP + 12) == 0


@pytest.mark.parametrize('status', [0, -17])
def test_actual_native_destructor_invalidates_before_pointer_reuse(m4emu, status):
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    report = native.install(p); p.finish_chains()
    c = Controller(m4emu, installed=(p, report))
    obj = c.add(); c.assign(0, [1]); c.tick()
    c.key(1); c.key(2); c.key(1); c.now = 400000; c.tick(); c.writes.clear()
    generation = struct.unpack_from('<I', c.routes()[0], 12)[0]
    owner, ref, preset, mutex = 0x28700000, 0x28780000, 0x28790000, 0x287a0000
    c.m.u32(owner + 4, obj); c.m.u32(owner + 8, ref); c.m.u32(ref, preset)
    c.m.u32(obj + 0x30, mutex)
    c.m.stub(0x28da6d5c, lambda m: m.reg('r0', 1))
    c.m.stub(0x28dfa774, lambda m: m.reg('r0', 0))
    c.m.stub(0x28dfcba8, lambda m: m.reg('r0', 0))
    def unhook(m):
        assert c.writes == [(1, 8, 0)], 'OverdubOff precedes native ownership destruction'
        assert c.m.u32(obj + 0x9f0) == owner
        m.reg('r0', status)
    c.m.stub(0x28df35e8, unhook)
    patched = reader(p.entry0())
    c.m.load(0x28df38d0, patched(0x28df38d0, 0xd4))
    assert c.m.call(0x28df38d0, DSP + 0x43fc, obj) == status & 0xffffffff
    assert c.depth == 0 and not c.routes() and c.m.u32(obj + 0x9f0) == 0
    c.add()                      # same native object and runtime-link addresses reused
    c.tick()
    assert struct.unpack_from('<I', c.routes()[0], 12)[0] != generation
    assert c.writes[-2:] == [(1, 7, 0), (1, 8, 0)]
    c.writes.clear(); c.key(2)
    assert c.writes == []


def test_actual_native_move_retargets_owned_transport_without_stopping_playback(m4emu):
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    report = native.install(p); p.finish_chains()
    c = Controller(m4emu, installed=(p, report))
    obj = c.add(); c.assign(0, [1]); c.tick(); c.key(1); c.key(2)
    generation = struct.unpack_from('<I', c.routes()[0], 12)[0]
    c.key(1); c.now = 400000; c.tick(); c.writes.clear()
    patched = reader(p.entry0())
    c.m.load(0x28e030bc, patched(0x28e030bc, 0x1ac))
    c.m.u8(0x2843ebb8, 2)
    c.m.stub(0x28e05d34, lambda m: m.reg('r0', DSP))
    c.m.stub(0x28e05c50, lambda m: m.reg('r0', 1))
    c.m.stub(0x28e07714, lambda m: m.reg('r0', 0))
    c.m.stub(0x28e08384, lambda m: m.reg('r0', 1))
    c.m.stub(0x28e0e878, lambda m: m.reg('r0', 0))
    c.m.stub(0x28e05320, lambda m: m.reg('r0', 0))
    def resolve(m):
        m.write(m.reg('r1'), struct.pack('<2I', 6, m.reg('r0') - 1)); m.reg('r0', 0)
    c.m.stub(0x28e07328, resolve)
    c.m.stub(0x28e24c78, lambda m: m.write(m.reg('r0'), m.read(m.reg('r1'), m.reg('r2'))))
    def move(m):
        assert c.writes == [(1, 8, 0)] and c.depth == 2
        c.m.u32(DSP + 0x14, 0xffffffff)
        c.m.u32(DSP + 0x14 + 0x54, 0)
        c.models[2] = c.models.pop(1); c.assign(0, [2])
        m.reg('r0', 0)
    c.m.stub(0x28e0d5a4, move)
    assert c.m.call(0x28e030bc, 0, 1, 2) == 0
    assert c.depth == 0
    route, = c.routes()
    assert struct.unpack_from('<I', route, 8)[0] == 2
    assert struct.unpack_from('<I', route, 12)[0] == generation
    assert struct.unpack_from('<I', route, 16)[0] == 1
    c.tick(); c.key(2)
    assert c.writes == [(1, 8, 0)], 'retained native allocation preserves Play and disarms old release'


def test_manifest_version_matches_assembled_source(m4emu):
    code, symbols = m4emu.assemble(native.MODULE, [], {}, inc={'microlooper_models.inc': native.asm_include()})
    assert hashlib.sha256(code).hexdigest() == native.MODULE_SHA256
    assert {name: symbols[name] for name in native.LAYOUT} == native.LAYOUT


@pytest.mark.parametrize('long_press', [False, True])
def test_real_feature_installation_and_single_input_owner_manifest(long_press):
    import features
    import setting_ids
    p = pm.Patch(stock_e0(), features.load(), setting_ids.by_name(), load=stock_entry)
    shared = None
    if long_press:
        hook = p.own_entry(native.HANDLER, native.HANDLER_STOCK, 'shared input')
        lp = p.module('src/m4/long_press.s')
        shared = (hook, hook.stock, lp['lp_event'])
    native.install(p, shared_input_hook=shared); p.finish_chains()
    report = native.verify_installed(p.entry0())
    assert report['shared_long_press'] == long_press and report['lifecycle_hooks'] == 9


@pytest.mark.parametrize('target', ['input', 'parameter', 'bypass', 'tick', 'runtime', 'lifecycle', 'manifest'])
def test_manifest_requires_real_hook_relationships_not_marker(target):
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    report = native.install(p); p.finish_chains()
    e0 = bytearray(p.entry0())
    addresses = dict(input=native.HANDLER, parameter=native.PARAMETER_FILTER_SITE,
                     bypass=native.BYPASS_SITE, tick=native.TICK_LITERAL,
                     runtime=report['microlooper_controller_key'], lifecycle=native.LIFECYCLE[0][0],
                     manifest=report['manifest_va'] + 20)
    offset = p.off(addresses[target], 1) if addresses[target] < p.cave.va else None
    if offset is None:
        # p.read addresses the original mapped image; the serialized image also
        # includes appended code, so use its segment table for appended bytes.
        q = pm.Patch(e0, [], {}); offset = q.off(addresses[target], 1)
    e0[offset] ^= 1
    with pytest.raises(ValueError):
        native.verify_installed(e0)


def test_stock_and_duplicate_or_truncated_manifest_are_rejected():
    with pytest.raises(ValueError, match='exactly one'):
        native.verify_installed(stock_e0())
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    native.install(p); p.finish_chains()
    p.add(native.MANIFEST_MAGIC)
    with pytest.raises(ValueError, match='exactly one'):
        native.verify_installed(p.entry0())


@pytest.mark.parametrize('changed', [False, True])
def test_actual_lower_bypass_for_ui_midi_and_snapshot_preserves_play(controller, changed):
    c = controller
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    report = native.install(p); p.finish_chains()
    c = Controller(c.api, installed=(p, report))
    c.add(); c.assign(0, [1]); c.tick(); c.key(1); c.key(2)
    c.key(1); c.now = 400000; c.tick(); c.writes.clear()
    before = c.routes()[0]
    patched = reader(p.entry0())
    c.m.load(0x28e06b4c, patched(0x28e06b4c, 0xc0))
    c.m.stub(0x28dfc244, lambda m: (m.u8(m.reg('r2'), c.bypass.get(1, 0)), m.reg('r0', 0)))
    def bypass(m):
        assert c.depth == 1
        if changed:
            assert c.writes == [(1, 8, 0)], 'stop overdub before native bypass'
        else:
            assert not c.writes, 'unchanged snapshot bypass must leave transport untouched'
        c.bypass[1] = int(not m.reg('r2'))
        m.reg('r0', 0)
    c.m.stub(0x28dfc0b4, bypass)
    c.m.stub(0x28e001c0, lambda m: m.reg('r0', 0))
    address = 0x28f5f000; c.m.write(address, struct.pack('<2I', 6, 0))
    assert c.m.call(0x28e06b4c, DSP, address, int(changed)) in (0, 1)
    assert c.depth == 0 and struct.unpack_from('<I', c.routes()[0], 16)[0] == 1
    if not changed:
        assert c.routes()[0] == before
    else:
        c.tick(); c.bypass[1] = 0; c.tick(); c.key(2)
        assert c.writes == [(1, 8, 0)]


def test_installed_controller_composes_real_lp_event_for_other_switch(m4emu):
    import features
    import setting_ids
    c = Controller(m4emu); c.add(); c.assign(0, [1]); c.tick()
    lp_code, lp_symbols = m4emu.assemble('src/m4/long_press.s', features.load(), setting_ids.by_name())
    lp_base = 0x28e80000; c.m.load(lp_base, lp_code)
    c.m.stub(0x28d96084, lambda m: m.reg('r0', MANAGER))
    c.m.stub(0x28d96134, lambda m: m.reg('r0', 0))
    c.m.stub(0x28d96588)
    def key(fs, kind):
        c.m.write(EVENT, struct.pack('<4BI', 1, 12 + fs, 0, 0, kind))
        c.m.call(c.at('microlooper_controller_key'), EVENT, OBJ, STOCK | 1,
                 lp_base + lp_symbols['lp_event'] | 1)
    key(0, 1); key(0, 5)
    assert not c.m.calls(0x28d96588)
    assert c.stock_events == [(12, 1)]
    key(1, 1)
    assert c.stock_events == [(12, 1)], 'ordinary long-press holds back another switch press'
    key(1, 5)
    assert len(c.m.calls(0x28d96588)) == 1


def test_retained_link_changed_primary_model_cannot_receive_transport_slot_writes(controller):
    c = controller; c.add(); c.assign(0, [1]); c.tick(); c.key(1); c.key(2)
    c.key(1); c.now = 400000; c.tick(); c.writes.clear()
    c.models[1] = 555             # same object and runtime link, different primary identity
    c.m.call(c.at('microlooper_controller_lock'))
    assert c.m.call(c.at('microlooper_controller_write'), 0, 1, 8, 0) == (-3 & 0xffffffff)
    c.m.call(c.at('microlooper_controller_unlock'))
    c.tick()
    assert not c.writes and not c.routes()


def test_controller_assignment_mutex_is_released_before_graph_writes_even_on_failure(controller):
    c = controller; c.add(); c.assign(0, [1]); c.tick(); c.key(1)
    c.fail = True
    seen = []
    address = 0x28e04864
    c.m.uc.hook_add(c.api.unicorn.UC_HOOK_CODE,
        lambda uc, address, size, user: seen.append((c.depth, c.assignment_depth)),
        begin=address, end=address)
    c.key(2)
    assert seen == [(1, 0)]
    assert c.depth == c.assignment_depth == 0


def test_actual_identical_reload_dispatches_native_ordinary_deletion_before_rebuild(m4emu):
    """Execute reload dispatcher→clear→ordinary removal, with the same model/grid.

    Native lower creation is recorded at its graph-builder seam; SHARC native
    constructors are tested separately. This runs actual clear/removal bodies,
    rather than inferring a graph epoch from unchanged model/slot metadata.
    """
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    report = native.install(p); p.finish_chains()
    c = Controller(m4emu, installed=(p, report))
    preset, section, owner = 0x28790000, 0x28800000, 0x28700000
    obj = c.add(obj=preset + 0xaf0); c.assign(0, [1]); c.tick()
    c.key(1); c.key(2); c.key(1); c.now = 400000; c.tick(); c.writes.clear()
    c.m.u32(DSP + 0x43fc, preset)
    for offset in (0xa1c, 0xa70, 0x554): c.m.u32(DSP + offset, 0xffffffff)
    c.m.u8(preset + 0xac4, 1)
    c.m.u32(preset + 0x544, 0xffffffff); c.m.u32(preset + 0x6a0, 0xffffffff)
    c.m.u32(owner + 4, obj); c.m.u32(owner + 8, preset + 0x7f8)
    c.m.u32(preset + 0x7f8, preset)
    c.m.u32(obj + 0x30, 0x287a0000)
    c.m.u8(obj + 0x28, 1)
    c.m.write(section, bytes(20 * 290))
    c.m.u8(section + 290 + 1, 1)
    c.m.write(section + 290 + 6, struct.pack('<I', 380))
    patched = reader(p.entry0())
    c.m.load(0x28e07878, patched(0x28e07878, 0x84))
    c.m.reg('c1_c0_2', 0xf00000); c.m.reg('fpexc', 0x40000000)
    assert c.m.call(0x28e07878) == 0  # actual native20-position rebuild-order initializer
    for address, size in ((0x28e0e5d0, 0x2a8), (0x28e0b4ec, 0x40c),
                          (0x28df4a98, 0x1d4), (0x28dfcee4, 0x8c),
                          (0x28df5530, 0x198), (0x28df38d0, 0xd4)):
        c.m.load(address, patched(address, size))
    for address in (0x28e13748, 0x28e13754, 0x28dfa434, 0x28dfa5f8,
                    0x28df4c6c, 0x28df48ac, 0x28dfa774, 0x28dfcba8,
                    0x28dfa978, 0x28e00230, 0x28e001c0,
                    0x28e09dfc, 0x28e0b3cc,
                    0x28e0a720, 0x28e0e3ec, 0x28e13720, 0x28e13714):
        c.m.stub(address, lambda m: m.reg('r0', 0))
    c.m.stub(0x28e13870, lambda m: m.reg('r0', 10))
    c.m.stub(0x28da6d5c, lambda m: m.reg('r0', 1))
    c.m.stub(0x28e24b78, lambda m: m.write(m.reg('r0'), bytes(m.reg('r2'))))
    def object_lookup(m):
        assert m.reg('r1') == 0
        m.u32(m.reg('r2'), obj); m.reg('r0', 0)
    c.m.stub(0x28dfa794, object_lookup)
    c.m.stub(0x28dfa864, object_lookup)
    destroyed, rebuilt = [], []
    def dsp_stop(m):
        assert c.writes == [(1, 8, 0)]
        destroyed.append(True); m.reg('r0', 0)
    c.m.stub(0x28df35e8, dsp_stop)
    def select(m):
        # Descriptor validity/graph construction is an independent metadata
        # seam. Let the complete dispatcher traverse its ordinary records.
        m.reg('r0', 1)
    c.m.stub(0x28e05d44, select)
    def rebuild(m):
        assert destroyed and c.m.u32(obj + 0x9f0) == 0 and not c.routes()
        rebuilt.append((m.read(m.reg('r1'), 8), m.read(m.reg('r2') + 5, 4)))
        m.reg('r0', 0)
    c.m.stub(0x28e0cc80, rebuild)
    # This lower dispatcher is normally called with the native graph lock held
    # by 0x28e024e0; retain that same precondition in this focused replay.
    c.m.call(c.at('microlooper_controller_lock'))
    assert c.m.call(0x28e0e5d0, DSP, 0, section) == 0
    c.m.call(c.at('microlooper_controller_unlock'))
    assert destroyed and rebuilt and not c.routes()
    assert any(descriptor == struct.pack('<I', 380) for _, descriptor in rebuilt)


@pytest.mark.parametrize('enabled_bit,expected_bypass', [(0, 1), (1, 0)])
def test_actual_native_bypass_getter_inverts_enabled_flag(m4emu, enabled_bit, expected_bypass):
    """Run the actual outer getter, address getter and node-bit getter.

    Stub only tone/address lookup and lock boundaries; the native boolean
    extraction and inversion must run, independently of controller stubs.
    """
    read = reader(stock_e0())
    m = m4emu.M4(read(0x28e04514, 0x8c), 0x28e04514)
    m.load(0x28e06ab4, read(0x28e06ab4, 0x98))
    m.load(0x28dfc244, read(0x28dfc244, 0x20))
    node, out = 0x28600000, 0x28f51000
    m.u8(m.u32(0x28e0459c) + 8, 2)
    m.u32(DSP + 0x14, 0)
    m.u32(node + 0x20, enabled_bit)
    m.u8(out, 0xff)
    m.stub(0x28e05d34, lambda m: m.reg('r0', DSP))
    m.stub(0x28e05c50, lambda m: m.reg('r0', 1))
    def resolve(m):
        assert m.reg('r0') == 1
        m.write(m.reg('r1'), struct.pack('<II', 6, 0))
        m.reg('r0', 0)
    m.stub(0x28e07328, resolve)
    for address in (0x28e07714, 0x28e07788, 0x28e07844, 0x28e0785c):
        m.stub(address, lambda m: m.reg('r0', 0))
    def lookup(m):
        assert m.reg('r0') == DSP + 0x43fc and m.reg('r1') == 0
        m.u32(m.reg('r2'), node)
        m.reg('r0', 0)
    m.stub(0x28dfa794, lookup)
    assert m.call(0x28e04514, 0, 1, out) == 0
    assert m.read(out, 1) == bytes([expected_bypass])


def test_input_resolves_controller_and_bypass_managers_separately_from_ui_context(controller):
    c = controller
    assert len({OBJ, MANAGER, CONTROLLERS}) == 3
    c.add(); c.assign(0, [1])
    listener = c.m.read(OBJ, 0x70)
    c.tick(); c.writes.clear()
    c.key(1); c.key(2)
    assert c.writes == [(1, 7, 1)]
    assert c.m.read(OBJ, 0x70) == listener
    assert c.m.calls(0x28d96084)
    assert all(args[0] == CONTROLLERS+4 for args in c.m.calls(0x28e24c00))


@pytest.mark.firmware
@pytest.mark.parametrize('slot', [7, 8])
def test_native_transport_writer_uses_effect_parameter_space(m4emu, slot):
    """The real native getter must validate an effect control, not a special field."""
    read = reader(stock_e0())
    code, symbols = m4emu.assemble(native.MODULE, [], {}, inc={'microlooper_models.inc': native.asm_include()})
    m = m4emu.M4(code, CODE)
    for address, size in ((0x28e04864, 0x120), (0x28e02040, 0xf0),
                          (0x28e07f80, 0x108), (0x28dfbb0c, 0x13c)):
        m.load(address, read(address, size))
    node = 0x28600000
    m.u8(0x2843ebb8, 2)
    m.u8(node + 5, 1)
    m.u8(node + 0x28, 8)            # native delay host
    m.u32(node + 0x60, 1)          # one special field; indices6/7 must reject here
    m.u32(node + 0x64, 8)          # eight real Atmosphere controls
    m.u8(node + 0x90 + (slot-1)*0x2c, 1)
    m.u32(node + 0x94 + (slot-1)*0x2c, 0)
    m.stub(0x28e05d34, lambda m: m.reg('r0', DSP))
    m.stub(0x28e05c50, lambda m: m.reg('r0', 1))
    m.stub(0x28e07714, lambda m: m.reg('r0', 0))
    def resolve(m):
        m.write(m.reg('r1'), struct.pack('<2I', 6, 0)); m.reg('r0', 0)
    m.stub(0x28e07328, resolve)
    m.stub(0x28e07788, lambda m: m.reg('r0', 0))
    m.stub(0x28e07844)
    m.stub(0x28e0785c)
    m.stub(0x28e07d58, lambda m: m.reg('r0', 0))
    m.stub(0x28e24b78, lambda m: m.write(m.reg('r0'), bytes(m.reg('r2'))))
    m.stub(0x28e24c78, lambda m: m.write(m.reg('r0'), m.read(m.reg('r1'), m.reg('r2'))))
    def lookup(m):
        m.u32(m.reg('r2'), node); m.reg('r0', 0)
    m.stub(0x28dfa794, lookup)
    writes = []
    def lower(m):
        descriptor, value = m.reg('r2'), m.reg('r3')
        writes.append((m.u32(descriptor+4), m.read(descriptor+8, 1), m.read(value, 2)))
        m.reg('r0', 0)
    m.stub(0x28e08454, lower)
    m.stub(0x28e0bc50, lambda m: m.reg('r0', 1))
    assert m.call(CODE + symbols['microlooper_native_write'], 0, 1, slot, 1) == 0
    assert writes == [(slot-1, b'\x00', b'\x01\x01')]


def test_variant_replacement_with_retained_native_object_and_link_rebinds_model_identity(controller):
    c = controller; c.add(); c.assign(0, [1]); c.tick()
    c.key(1); c.key(2); c.key(1); c.now = 400000; c.tick()
    c.writes.clear()
    replacement = next(effect.preset_id for effect in MODELS if effect.preset_id != c.model)
    c.models[1] = replacement
    c.tick()
    assert c.writes == [(1, 7, 0), (1, 8, 0)]
    route, = c.routes()
    assert struct.unpack_from('<I', route, 28)[0] == replacement
    assert struct.unpack_from('<I', route, 48)[0] == replacement
    c.writes.clear(); c.key(2)
    assert c.writes == []
    c.key(1); c.key(2)
    assert c.writes == [(1, 7, 1)]
