"""Explicit M4 diagnostic: actual Thumb RX/cache/USB code with native ABI stubs."""
import struct

import msgpack
import pytest

import hx_microlooper_probe as host
import microlooper_readback as rb
import patch_menu as pm
import usb_commands
from firmware import branch_target, reader, stock_e0, stock_entry

MOD, FRAME, OUT = 0x28e60000, 0x28f10000, 0x28f11000
CLOCK, REGISTER, NO_PARAMS = 0x28da6458, 0x28e165f0, 0x28e19204
WRITER, PREFIX_LEN, PREFIX, RESET, HEAD = 0x28e157c8, 0x28e157ec, 0x28e15810, 0x28e15834, 0x28e15878
LOCK, UNLOCK = 0x28e24c00, 0x28e24bb0
STREAM, VTABLE, WRITER_OBJ, COUNT, PREFIX_BUF, REQUEST = (0x28f80000 + n * 0x100 for n in range(6))
WRITE, FINISH, WRITER_FN = 0x28f90000, 0x28f90010, 0x28f90020


def swap(value):
    return ((value << 16) | (value >> 16)) & 0xffffffff


def context(calls=17):
    return [rb.CONTEXT_MAGIC, calls] + [0x12340000 + n for n in range(14)]


def frame(sequence=2, payload=None):
    # Non-diagnostic fields include the GR values and arbitrary nonzero data.
    words = [0x10000000 + n for n in range(256)]
    words[0], words[255] = 0xfacef00d, 0xd00fecaf
    words[219:239] = [rb.TAG, sequence, 16, *(context() if payload is None else payload), sequence]
    return struct.pack('<256I', *map(swap, words))


class Runtime:
    def __init__(self, m4emu, code, symbols):
        self.api, self.sym = m4emu, symbols
        self.m = m4emu.M4(code, MOD)
        self.now, self.ticks = 100, 0
        self.m.stub(CLOCK, self.clock)

    def clock(self, m):
        assert m.reg('sp') % 8 == 0
        self.ticks += 1
        m.reg('r0', self.now)

    def at(self, symbol):
        return MOD + self.sym[symbol]

    def hook(self, symbol, callback):
        address = self.at(symbol)
        return self.m.uc.hook_add(self.api.unicorn.UC_HOOK_CODE,
                                  lambda uc, a, size, data: callback(), begin=address, end=address)

    def receive(self, sequence=2, payload=None):
        self.m.write(FRAME, frame(sequence, payload))
        before = self.m.read(FRAME, 1024)
        self.m.reg('r12', 0xa1b2c3d4)
        assert self.m.call(self.at('mlr_frame'), 0x12345678, FRAME, 0x87654321, 42) == 0x12345678
        assert self.m.reg('r1') == FRAME and self.m.reg('r2') == 0x87654321 and self.m.reg('r3') == 42
        assert self.m.reg('r12') == 0xa1b2c3d4
        assert self.m.read(FRAME, 1024) == before, 'RX must leave GR and all other frame words intact'

    def cache(self, *, guard=2, sequence=2, received=100, valid=1, payload=None, end=None):
        self.m.write(self.at('mlr_cache'), struct.pack('<21I', guard, sequence, received, valid,
                     *(context() if payload is None else payload), guard if end is None else end))

    def reply(self):
        self.m.write(OUT, b'\xff' * 96)
        valid = self.m.call(self.at('mlr_copy_reply'), OUT)
        blob = self.m.read(OUT, 96)
        assert struct.unpack_from('<I', blob, 8)[0] == valid
        return host.decode_reply(blob), struct.unpack('<24I', blob)


@pytest.fixture(scope='module')
def assembled():
    import m4emu
    return m4emu.assemble(rb.MODULE, [], {}, inc={'microlooper_readback.inc': rb.asm_include()})


@pytest.fixture
def rt(m4emu, assembled):
    return Runtime(m4emu, *assembled)


def test_reserved_command_is_unused_by_stock_and_not_an_automatic_feature():
    assert rb.CMD == usb_commands.DIAGNOSTIC_CONTEXT == 0x51
    assert rb.CMD in usb_commands.FREE
    assert rb.CMD not in usb_commands.registered(reader(stock_e0()), branch_target)
    assert sum(command == rb.CMD for command, _, _ in usb_commands.COMMANDS) == 1
    assert next(name for command, name, _ in usb_commands.COMMANDS if command == rb.CMD) is None
    assert not hasattr(rb, 'FLAG') and not hasattr(rb, 'apply')


def test_no_data_and_accepted_halfword_swapped_context(rt):
    decoded, words = rt.reply()
    assert decoded['status'] == 'no_data' and words[5] == 100
    rt.receive()
    rt.now = 900
    decoded, words = rt.reply()
    assert words == (rb.TAG, 96, 1, 2, 100, 900, 800, 0, *context())
    assert decoded['context']['calls'] == 17


@pytest.mark.parametrize('index,value', [(0, 0), (255, 0), (219, 0), (221, 15),
                                        (220, 3), (238, 6), (222, 0)])
def test_bad_frame_does_not_replace_cache_or_sample_clock(rt, index, value):
    rt.receive()
    old = rt.m.read(rt.at('mlr_cache'), 84)
    rt.m.write(FRAME, frame(4, context(18)))
    rt.m.u32(FRAME + 4 * index, swap(value))
    rt.m.call(rt.at('mlr_frame'), 0, FRAME)
    assert rt.m.read(rt.at('mlr_cache'), 84) == old
    assert rt.ticks == 1


def test_duplicate_source_never_refreshes_receive_time_and_stale_is_visible(rt):
    rt.receive()
    rt.now = 2_000_000
    rt.receive(2, context(999))
    assert rt.ticks == 1
    result, words = rt.reply()
    assert result['status'] == 'stale' and words[4] == 100
    assert words[8:] == tuple(context())


@pytest.mark.parametrize('cached,incoming', [(100, 98), (0, 0xfffffffe),
                                            (2, 0x80000002), (0xfffffffe, 0xfffffffc)])
def test_older_or_ambiguous_source_cannot_replace_newer_cache_or_refresh_age(rt, cached, incoming):
    rt.cache(sequence=cached, received=100)
    before = rt.m.read(rt.at('mlr_cache'), 84)
    rt.now = 2_000_000
    rt.receive(incoming, context(999))
    assert rt.ticks == 0
    assert rt.m.read(rt.at('mlr_cache'), 84) == before
    result, words = rt.reply()
    assert result['status'] == 'stale' and words[3:5] == (cached, 100)
    assert words[8:] == tuple(context())


def test_alternating_replayed_frames_cannot_keep_a_stopped_source_fresh(rt):
    rt.receive(100, context(100))
    rt.now = 2_000_000
    rt.receive(98, context(98))
    rt.now += 10
    rt.receive(100, context(100))
    assert rt.ticks == 1
    result, words = rt.reply()
    assert result['status'] == 'stale'
    assert words[3:5] == (100, 100) and words[6] == 1_999_910
    assert words[8:] == tuple(context(100))


@pytest.mark.parametrize('cached,incoming', [(100, 102), (0xfffffffe, 0),
                                            (0x7ffffffe, 0x80000000)])
def test_positive_modular_source_progress_replaces_cache_and_refreshes_age(rt, cached, incoming):
    rt.cache(sequence=cached, received=100)
    rt.now = 2_000_000
    rt.receive(incoming, context(999))
    assert rt.ticks == 1
    result, words = rt.reply()
    assert result['status'] == 'fresh' and words[3:5] == (incoming, rt.now)
    assert words[8:] == tuple(context(999))


def test_source_cache_and_clock_wrap_are_unsigned(rt):
    rt.cache(guard=0xfffffffe, sequence=0xfffffffe, received=0xfffffff0)
    rt.now = 0xfffffff8
    rt.receive(0)
    assert rt.m.u32(rt.at('mlr_cache')) == rt.m.u32(rt.at('mlr_cache') + 80) == 0
    rt.now = 20
    result, words = rt.reply()
    assert result['valid'] and words[3] == 0 and words[6] == 28


@pytest.mark.parametrize('guard', ['begin', 'end', 'both'])
@pytest.mark.parametrize('during', ['mlr_frame_copy', 'mlr_frame_validate'])
def test_source_changes_during_copy_are_rejected(rt, guard, during):
    rt.receive()
    old = rt.m.read(rt.at('mlr_cache'), 84)
    rt.m.write(FRAME, frame(4, context(18)))
    touched = []
    def tear():
        if touched:
            return
        touched.append(True)
        if guard in ('begin', 'both'):
            rt.m.u32(FRAME + 220 * 4, swap(5))
        if guard in ('end', 'both'):
            rt.m.u32(FRAME + 238 * 4, swap(5))
        rt.m.u32(FRAME + 230 * 4, 0xdeadbeef)
    rt.hook(during, tear)
    rt.m.call(rt.at('mlr_frame'), 0, FRAME)
    assert touched and rt.ticks == 1 and rt.m.read(rt.at('mlr_cache'), 84) == old


def test_initial_mismatched_end_is_rejected_before_payload_read(rt):
    rt.m.write(FRAME, frame())
    rt.m.u32(FRAME + 238 * 4, swap(4))
    rt.hook('mlr_frame_copy', lambda: pytest.fail('an initially torn source must not be copied'))
    rt.m.call(rt.at('mlr_frame'), 0, FRAME)
    assert rt.ticks == 0


@pytest.mark.parametrize('guard,end', [(1, 1), (2, 4), (0xfffffffe, 0)])
def test_incoherent_cache_returns_bounded_no_data(rt, guard, end):
    rt.cache(guard=guard, end=end)
    tries = []
    rt.hook('mlr_reply_try', lambda: tries.append(1))
    result, words = rt.reply()
    assert len(tries) == 3 and result['status'] == 'no_data'
    assert words[2:5] == (0, 0, 0) and words[6:] == (0,) * 18


@pytest.mark.parametrize('during', ['mlr_reply_copy', 'mlr_reply_validate'])
def test_cache_changes_retry_then_return_one_complete_record(rt, during):
    rt.cache()
    changed, tries = [], []
    def publish():
        if not changed:
            changed.append(True)
            rt.cache(guard=4, sequence=4, received=50, payload=context(999))
    rt.hook(during, publish)
    rt.hook('mlr_reply_try', lambda: tries.append(1))
    _, words = rt.reply()
    assert len(tries) == 2 and words[3:5] == (4, 50) and words[8:] == tuple(context(999))


def test_continuously_changing_cache_fails_after_three_copies(rt):
    rt.cache()
    changes = []
    def publish():
        changes.append(1)
        rt.cache(guard=2 + 2 * len(changes), sequence=2 + 2 * len(changes))
    rt.hook('mlr_reply_validate', publish)
    result, _ = rt.reply()
    assert len(changes) == 3 and result['status'] == 'no_data'


def test_every_cache_publication_instruction_is_either_old_new_or_unreadable(rt, m4emu, assembled):
    rt.cache()
    reader_rt = Runtime(m4emu, *assembled)
    new_context = [rb.CONTEXT_MAGIC, 999] + [0x56780000 + n for n in range(14)]
    seen = set()
    def observe(uc, address, size, user):
        raw = rt.m.read(rt.at('mlr_cache'), 84)
        if raw in seen:
            return
        seen.add(raw)
        reader_rt.m.write(reader_rt.at('mlr_cache'), raw)
        _, words = reader_rt.reply()
        assert words[8:] in ((0,) * 16, tuple(context()), tuple(new_context))
        if words[2]:
            assert (words[3], words[4], words[8:]) in ((2, 100, tuple(context())),
                                                    (4, 200, tuple(new_context)))
    rt.m.uc.hook_add(m4emu.unicorn.UC_HOOK_CODE, observe,
                     begin=rt.at('mlr_cache_invalidate'), end=rt.at('mlr_copy_reply') - 1)
    rt.now = 200
    rt.receive(4, new_context)
    assert len(seen) > 16


class Editor(Runtime):
    def __init__(self, m4emu, code, symbols):
        super().__init__(m4emu, code, symbols)
        self.prefix, self.out, self.locked = b'', b'', False
        self.events, self.on_head, self.fail = [], None, None
        m = self.m
        m.u32(STREAM, VTABLE)
        m.u32(VTABLE + 4, WRITE | 1)
        m.u32(VTABLE + 12, FINISH | 1)
        m.write(WRITER_OBJ, struct.pack('<II', 0x1234, WRITER_FN | 1))
        for address, result in ((WRITER, WRITER_OBJ), (PREFIX_LEN, COUNT), (PREFIX, PREFIX_BUF)):
            m.stub(address, lambda m, result=result: self.service(m, result))
        m.stub(RESET, self.reset)
        m.stub(HEAD, self.head)
        m.stub(WRITER_FN, self.bin_header)
        m.stub(LOCK, lambda m: self.lock(m, True))
        m.stub(UNLOCK, lambda m: self.lock(m, False))
        m.stub(WRITE, self.write)
        m.stub(FINISH, self.finish)
        m.stub(REGISTER, lambda m: m.reg('r0', 0))

    def service(self, m, result):
        assert m.reg('r0') == 6
        m.reg('r0', result)

    def reset(self, m):
        assert m.reg('r0') == 6
        self.prefix = b''
        m.u32(COUNT, 0)

    def add(self, data):
        self.m.write(PREFIX_BUF + len(self.prefix), data)
        self.prefix += data
        self.m.u32(COUNT, len(self.prefix))

    def head(self, m):
        assert m.reg('r0') == WRITER_OBJ and m.reg('r2') == 0
        self.add(bytes([0x83, 0x66, 0xcd]) + struct.pack('>H', m.reg('r1')) + bytes([0x67, 0, 0x68]))
        if self.on_head:
            self.on_head()

    def bin_header(self, m):
        assert m.reg('r0') == 0x1234 and m.reg('sp') % 8 == 0
        self.add(m.read(m.reg('r1'), m.reg('r2')))
        m.reg('r0', -71 if self.fail == 'prefix' else 0)

    def lock(self, m, on):
        assert m.reg('r0') == STREAM - 8 and self.locked != on
        self.locked = on
        self.events.append('lock' if on else 'unlock')

    def write(self, m):
        assert m.reg('r0') == STREAM and self.locked and m.reg('sp') % 8 == 0
        self.events.append('write')
        self.out += m.read(m.reg('r1'), m.reg('r2'))
        m.reg('r0', -72 if self.events.count('write') == self.fail else m.reg('r2'))

    def finish(self, m):
        assert m.reg('r0') == STREAM and m.reg('r1') == 0 and self.locked
        self.events.append('finish')
        m.reg('r0', -73 if self.fail == 'finish' else 0)

    def command(self, sequence=0x1234):
        self.m.u32(REQUEST + 12, sequence)
        return self.m.call(self.at('mlr_cmd'), STREAM, REQUEST)


@pytest.fixture
def editor(m4emu, assembled):
    return Editor(m4emu, *assembled)


def test_registers_the_reserved_no_parameter_command(editor):
    editor.m.call(editor.at('mlr_register'))
    (command, descriptor, _, _), = editor.m.calls(REGISTER)
    assert command == rb.CMD
    assert struct.unpack('<3I', editor.m.read(descriptor, 12)) == (editor.at('mlr_cmd') | 1, NO_PARAMS | 1, 0)


@pytest.mark.parametrize('valid', [False, True])
def test_actual_usb_binary_reply_decodes_on_host(editor, valid):
    if valid:
        editor.receive()
    editor.now = 150
    assert editor.command() == 0 and not editor.locked
    assert struct.unpack_from('<HHI', editor.out) == (0, 6, len(editor.out) - 8)
    reply = msgpack.unpackb(editor.out[8:], strict_map_key=False)
    assert reply[0x66] == 0x1234 and reply[0x67] == 0 and len(reply[0x68]) == 96
    result = host.decode_reply(reply[0x68])
    assert result['valid'] == valid
    if valid:
        assert result['context']['calls'] == 17 and result['age_us'] == 50


def test_usb_uses_private_snapshot_even_when_rx_updates_during_prefix(editor):
    editor.cache()
    editor.on_head = lambda: editor.cache(guard=4, sequence=4, received=70, payload=context(999))
    assert editor.command() == 0
    reply = msgpack.unpackb(editor.out[8:], strict_map_key=False)
    result = host.decode_reply(reply[0x68])
    assert result['source_sequence'] == 2 and result['context']['calls'] == 17


@pytest.mark.parametrize('failure,expected', [('prefix', -71), (1, -72), (2, -72), (3, -72), ('finish', -73)])
def test_stream_failure_returns_native_status_and_unlocks(editor, failure, expected):
    editor.fail = failure
    assert editor.command() == expected & 0xffffffff and not editor.locked
    if failure == 'prefix':
        assert editor.events == []
    else:
        assert editor.events[0] == 'lock' and editor.events[-1] == 'unlock'
        assert editor.events.count('unlock') == 1
        assert ('finish' in editor.events) == (failure == 'finish')


def test_stock_guards_install_and_existing_callback_are_preserved(m4emu):
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    report = rb.install(p)
    assert report['prior_rx'] == rb.RX_STOCK and report['prior_register'] == rb.REGISTER_ALL
    with pytest.raises(SystemExit, match='already staged'):
        rb.install(p)
    p.finish_chains()
    m = m4emu.M4(bytes(p.cave.buf), p.cave.va)
    m.stub(CLOCK, lambda m: m.reg('r0', 10))
    m.stub(rb.RX_STOCK, lambda m: m.reg('r0', 42))
    m.write(FRAME, frame())
    assert m.call(p.u32(rb.RX_LITERAL), 123, FRAME, 456, 789) == 42
    assert m.calls(rb.RX_STOCK) == [(123, FRAME, 456, 789)]
    assert m.read(FRAME, 1024) == frame()
    assert m.u32(report['mlr_cache'] + 12) == 1


def test_install_preserves_finalized_prior_rx_and_registration_chains(m4emu):
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    p.chain_ptr(rb.RX_LITERAL, rb.RX_STOCK, before=0x28f91000)
    p.chain_bl(rb.REGISTER_CALL, rb.REGISTER_ALL, after=0x28f91010)
    p.finish_chains()
    previous_rx = p.u32(rb.RX_LITERAL)
    previous_register = branch_target(rb.REGISTER_CALL, p.read(rb.REGISTER_CALL, 4))
    # Serialize/reopen to model appending a diagnostic to a completed HXtra build.
    finalized = p.output()[0]
    q = pm.Patch(finalized, [], {}, load=stock_entry)
    report = rb.install(q)
    assert (report['prior_rx'], report['prior_register']) == (previous_rx, previous_register)
    q.finish_chains()
    m = m4emu.M4(bytes(q.cave.buf), q.cave.va)
    # Previous chain is in the existing Entry 0 rather than the newly appended cave.
    m.load(p.cave.va, p.cave.buf)
    m.stub(CLOCK, lambda m: m.reg('r0', 10))
    for address in (rb.RX_STOCK, rb.REGISTER_ALL, 0x28f91000, 0x28f91010, REGISTER):
        m.stub(address, lambda m: m.reg('r0', 0))
    m.write(FRAME, frame())
    m.call(q.u32(rb.RX_LITERAL), 123, FRAME)
    assert len(m.calls(0x28f91000)) == len(m.calls(rb.RX_STOCK)) == 1
    m.call(branch_target(rb.REGISTER_CALL, q.read(rb.REGISTER_CALL, 4)))
    assert len(m.calls(rb.REGISTER_ALL)) == len(m.calls(0x28f91010)) == len(m.calls(REGISTER)) == 1


@pytest.mark.parametrize('address', [va for va, _ in rb.CALLED])
def test_changed_native_abi_is_rejected(address):
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    offset = p.off(address, 1)
    p.e0[offset] ^= 1
    with pytest.raises(SystemExit, match='not at its stock address'):
        rb.install(p)


def test_registration_must_be_bl_and_rx_must_be_thumb():
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    p.e0[p.off(rb.REGISTER_CALL, 4):p.off(rb.REGISTER_CALL, 4) + 4] = b'\0' * 4
    with pytest.raises(SystemExit, match='Thumb BL'):
        rb.install(p)
    p = pm.Patch(stock_e0(), [], {}, load=stock_entry)
    with pytest.raises(SystemExit, match='Thumb function pointer'):
        rb.install(p, rx_target=rb.RX_STOCK & ~1)
