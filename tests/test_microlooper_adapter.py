"""Native-context diagnostic, not proof of the HX Stomp stereo dispatcher ABI."""
import os
import random
import struct

import pytest

import microlooper_adapter as ma
import ssim

STATE, CALL, INSTANCE, RING = 0x94000, 0xb4000, 0x96000, 0x400000


def run_context(call=CALL, instance=INSTANCE, begin=RING, end=RING + 48000,
                deny_reads=()):
    sim = ssim.Sim()
    sim.strict_cbufen = True
    sections, syms = ma.assemble(0xe5000)
    sim.load(sections)
    rng = random.Random(82)
    for r in range(16):
        sim.setR(r, rng.getrandbits(32))
        sim.alt[r] = rng.getrandbits(32)
    for c in range(0x10, 0x50):
        sim.set(c, rng.randrange(1, 16) if 0x30 <= c < 0x40 else rng.randrange(0x100000))
    for c, value in ((0x10, STATE), (0x11, 0xabcde), (0x12, 0xbdf00), (0x13, call), (0x18, 0xe1234)):
        sim.set(c, value)
    for offset in range(-1, ma.STATE_WORDS + 1):
        sim.wr(STATE + offset, 0)
    sim.wr(STATE - 1, 0xdeadbeef)
    sim.wr(STATE + ma.STATE_WORDS, 0xdeadbeef)
    sim.wr(call + 2, instance)
    sim.wr(instance + 6, begin)
    sim.wr(instance + 7, end)
    sim.u[ssim.U_MODE1] = 0x1600000
    sim.set(ssim.U_ASTATX, 0x76543210)
    sim.set(ssim.U_ASTATY, 0x34567890)
    sim.set(0x78, 0x12345678)
    sim.set(0x79, 0x87654321)
    before = ([sim.R(r) for r in range(16)], list(sim.alt[:16]),
              [sim.get(c) for c in range(0x10, 0x50)], sim.u[ssim.U_MODE1],
              [sim.get(c) for c in (ssim.U_ASTATX, ssim.U_ASTATY, 0x78, 0x79)])
    original_read = sim.rd
    def no_audio_reads(address):
        assert address not in deny_reads, f'guarded pointer was dereferenced at {address:#x}'
        assert not (0xabcde <= address < 0xabcde + 32)
        assert not (0xbdf00 <= address < 0xbdf00 + 32)
        return original_read(address)
    sim.rd = no_audio_reads
    sim.call(syms['MICROLOOPER_ADAPTER_CONTEXT'], limit=1000)
    after = ([sim.R(r) for r in range(16)], list(sim.alt[:16]),
             [sim.get(c) for c in range(0x10, 0x50)], sim.u[ssim.U_MODE1],
             [sim.get(c) for c in (ssim.U_ASTATX, ssim.U_ASTATY, 0x78, 0x79)])
    assert before == after
    assert not sim.pcstk and not sim.loops
    assert sim.rd(STATE - 1) == sim.rd(STATE + ma.STATE_WORDS) == 0xdeadbeef
    return sim, ma.decode_snapshot([sim.rd(STATE + ma.SNAPSHOT_OFFSET + k) for k in range(16)])


def test_context_reports_raw_registers_and_descriptor_without_claiming_channel_layout():
    sim, report = run_context()
    assert report['calls'] == 1
    assert [report[k] for k in ('i0', 'i1', 'i2', 'i3', 'i8')] == [STATE, 0xabcde, 0xbdf00, CALL, 0xe1234]
    assert report['mode1'] == 0x1600000
    assert report['instance_candidate'] == INSTANCE
    assert report['sdram_begin'] == RING and report['sdram_end'] == RING + 48000
    assert report['plausible_extent'] == 1
    assert report['native_stereo_abi_verified'] is False
    assert all(sim.rd(STATE + k) == 0 for k in range(160))


@pytest.mark.parametrize('call,instance,begin,end', [
    (0, INSTANCE, RING, RING + 48000), (0xffffe, INSTANCE, RING, RING + 48000),
    (CALL, 0, RING, RING + 48000), (CALL, 0xffff9, RING, RING + 48000),
    (CALL, INSTANCE, 0, RING), (CALL, INSTANCE, RING, RING + 47999),
    (CALL, INSTANCE, RING, 0x4000001), (CALL, INSTANCE, RING, RING),
])
def test_bad_candidates_do_not_validate_a_ring(call, instance, begin, end):
    _, report = run_context(call, instance, begin, end)
    assert report['plausible_extent'] == 0


@pytest.mark.parametrize('low,high', ma.INTERNAL_DM_RANGES)
@pytest.mark.parametrize('edge', ['first', 'last'])
def test_complete_call_record_fits_at_each_sram_bank_edge(low, high, edge):
    call = low if edge == 'first' else high - 3
    _, report = run_context(call=call)
    assert report['instance_candidate'] == INSTANCE
    assert report['plausible_extent'] == 1


@pytest.mark.parametrize('low,high', ma.INTERNAL_DM_RANGES)
@pytest.mark.parametrize('edge', ['first', 'last'])
def test_complete_descriptor_fits_at_each_sram_bank_edge(low, high, edge):
    instance = low if edge == 'first' else high - 8
    _, report = run_context(instance=instance)
    assert report['instance_candidate'] == instance
    assert report['plausible_extent'] == 1


BAD_CALLS = sorted({address for low, high in ma.INTERNAL_DM_RANGES
                    for address in (low - 1, high - 2, high)} |
                   {0, 0x80000, 0x8ffff, 0x90000, 0xa0000, 0xb0000,
                    0xd0000, 0xf0000, 0xffffffff})
BAD_DESCRIPTORS = sorted({address for low, high in ma.INTERNAL_DM_RANGES
                          for address in (low - 1, high - 7, high)} |
                         {0, 0x80000, 0x8ffff, 0x90000, 0xa0000, 0xb0000,
                          0xd0000, 0xf0000, 0xffffffff})


@pytest.mark.parametrize('call', BAD_CALLS)
def test_rom_gap_and_cross_bank_call_records_are_never_dereferenced(call):
    _, report = run_context(call=call, deny_reads=(call + 2,))
    assert report['instance_candidate'] == 0
    assert report['plausible_extent'] == 0


@pytest.mark.parametrize('instance', BAD_DESCRIPTORS)
def test_rom_gap_and_cross_bank_descriptors_are_never_dereferenced(instance):
    _, report = run_context(instance=instance, deny_reads=(instance + 6, instance + 7))
    assert report['instance_candidate'] == instance
    assert report['plausible_extent'] == 0


def test_snapshot_decoder_rejects_wrong_length_and_magic():
    for words in ([], [ma.MAGIC] * 15, [0] * 16):
        with pytest.raises(ValueError):
            ma.decode_snapshot(words)


def test_absolute_diagnostic_uses_reserved_sidecar_and_preserves_native_context():
    sidecar = 0xe7000
    sim = ssim.Sim()
    sim.strict_cbufen = True
    sections, symbols = ma.assemble_diagnostic(0xe5000, sidecar)
    sim.load(sections)
    for code in range(0x60):
        sim.set(code, 0x5a000000 + code)
    sim.set(0x10, STATE)
    sim.set(0x13, CALL)
    sim.wr(CALL + 2, INSTANCE)
    sim.wr(INSTANCE + 6, RING)
    sim.wr(INSTANCE + 7, RING + 48000)
    sim.set(ssim.U_MODE1, 0x1600000)
    for code in (ssim.U_ASTATX, ssim.U_ASTATY, 0x78, 0x79):
        sim.set(code, 0x76543210 + code)
    for offset in range(ma.STATE_WORDS):
        sim.wr(STATE + offset, 0x12340000 + offset)
    sim.wr(sidecar - 1, 0x11223344)
    sim.wr(sidecar + ma.STATE_WORDS, 0x11223344)
    regs = list(range(0x60)) + [ssim.U_MODE1, ssim.U_ASTATX, ssim.U_ASTATY, 0x78, 0x79]
    before = [sim.get(code) for code in regs]
    sim.call(symbols['MICROLOOPER_ADAPTER_GLOBAL_CONTEXT'], limit=256)
    assert [sim.get(code) for code in regs] == before
    assert [sim.rd(STATE + offset) for offset in range(ma.STATE_WORDS)] == [
        0x12340000 + offset for offset in range(ma.STATE_WORDS)]
    assert sim.rd(sidecar - 1) == sim.rd(sidecar + ma.STATE_WORDS) == 0x11223344
    snapshot = ma.decode_snapshot([sim.rd(sidecar + ma.SNAPSHOT_OFFSET + k) for k in range(16)])
    assert snapshot['i0'] == STATE
    assert snapshot['instance_candidate'] == INSTANCE
    assert snapshot['plausible_extent'] == 1
    assert not sim.pcstk and not sim.loops


@pytest.mark.parametrize('pm,dm', [(1, 0xe7000), (0xe5000, 1), (0xe5000, 0x100000)])
def test_absolute_diagnostic_requires_explicit_bounded_aligned_placement(pm, dm):
    with pytest.raises(ValueError):
        ma.assemble_diagnostic(pm, dm)


def test_ldr_reader_obeys_later_overrides_and_rejects_truncation():
    def image(*words):
        return bytes(384 * 4) + struct.pack('<%dI' % len(words), *words)
    data = image(4, 2, 0x200000, 4, 5, 4, 1, 0x200001, 9, 0, 0, 0)
    assert ma.ldr_word(data, 0x200000) == 4
    assert ma.ldr_word(data, 0x200001) == 9
    assert ma.ldr_word(data, 0x200002) is None
    with pytest.raises(ValueError, match='truncated'):
        ma.ldr_word(image(4, 8, 0x200000, 1), 0x200000)
    for bad in (b'', bytes(384 * 4 + 1), image(13, 1, 0)):
        with pytest.raises(ValueError):
            list(ma.ldr_blocks(bad))


def test_encoded_bridge_stops_before_visa_and_has_a_real_instruction_bound():
    sections, symbols = ma.sasm.assemble('''
.section pm 0x8c100;
BRIDGE:
    R4 = I1;
    R8 = I2;
    R12 = DM(2,I3);
    CJUMP 0x170000 (DB);
    NOP;
    NOP;
''', 'synthetic_bridge.asm')
    code = next(section.words for section in sections if section.kind == 'pm')
    payload = b''.join(word.to_bytes(6, 'little') for word in code)
    payload += bytes((-len(payload)) % 12)
    record = struct.pack('<3I', 5, len(code), symbols['BRIDGE']) + payload
    short = struct.pack('<4I', 3, 1, 0x170000, 0)
    # FINAL_INIT follows the one packed INIT16 payload word.
    image = bytes(384 * 4) + record + short + bytes(12)
    report = ma.trace_process_bridge(image, symbols['BRIDGE'])
    assert report['c_argument_registers'] == {'r4': 0xb8000, 'r8': 0xb8100, 'r12': 0xb6000}
    assert report['read_addresses'] == [0xb4002]
    assert report['visa_entry'] == 0x170000
    assert report['synthetic_context'] and not report['native_stereo_abi_verified']
    with pytest.raises(ValueError, match='bound'):
        ma.trace_process_bridge(image, symbols['BRIDGE'], limit=1)
    with pytest.raises(ValueError, match='absent code'):
        ma.trace_process_bridge(image, 0x8c200)


@pytest.mark.firmware
def test_stock_host_graph_is_stereo_without_inferring_runtime_samples():
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    report = ma.inspect(stock)
    assert report['composite'] == 0x600096
    assert report['primitive'] == 0x9c51
    assert report['registry_address'] == 0x200580
    assert report['process_address'] == 0x8e9e3
    assert report['root_ports'] == [0, 2]
    assert report['primitive_ports'] == [2, 2]
    assert report['input_buffers'] == report['output_buffers'] == [0, 1]
    assert not report['native_stereo_abi_verified']
    bridge = report['process_bridge']
    assert bridge['c_argument_registers'] == {'r4': 0xb8000, 'r8': 0xb8100, 'r12': 0xb6000}
    assert bridge['read_addresses'] == [0xb4002]
    assert bridge['visa_entry'] == 0x17ad40
    assert bridge['visa_boot_block'] == [0x17973b, 10432]
    assert bridge['cjump_addresses'] == [0x8e9e4]
    assert bridge['isa_steps'] == 55


@pytest.mark.firmware
@pytest.mark.parametrize('sidecar', [None, 0xe7000])
def test_diagnostic_tail_calls_real_stock_bridge_with_identical_handoff_context(sidecar):
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    image, _ = ma.kit.load_l6ia_from_any(stock)
    entry = ma.kit.l6ia.parse(image)[2]
    raw = image[entry['payload_off']:entry['payload_off'] + entry['payload_len']]
    original = ma.trace_process_bridge(raw, 0x8e9e3, include_context=True)
    wrapped = ma.trace_process_bridge(raw, 0x8e9e3, diagnostic_base=0xe5000,
                                     diagnostic_sidecar=sidecar,
                                     include_context=True)
    for field in ('native_entry_context', 'handoff_context', 'pc_stack', 'loop_stack',
                  'c_argument_registers', 'visa_entry'):
        assert original[field] == wrapped[field], field
    assert wrapped['isa_steps'] > original['isa_steps']
    assert not wrapped['native_stereo_abi_verified']


@pytest.mark.parametrize('previous,next_sequence', [(0, 2), (0xfffffffe, 0)])
def test_source_publication_invalidates_before_payload_and_even_sequence_wraps(previous, next_sequence):
    sim = ssim.Sim()
    sections, symbols = ma.assemble_diagnostic(0xe5000, STATE)
    sim.load(sections)
    sim.wr(STATE + ma.SOURCE_SEQUENCE_OFFSET, previous)
    sim.set(0x10, 0x94500)
    sim.set(0x13, CALL)
    sim.wr(CALL + 2, INSTANCE)
    sim.wr(INSTANCE + 6, RING)
    sim.wr(INSTANCE + 7, RING + 48000)
    writes, during = [], []
    write = sim.wr

    def observe(address, value):
        write(address, value)
        if (STATE + ma.SNAPSHOT_OFFSET <= address < STATE + ma.SNAPSHOT_OFFSET + 16
                or address == STATE + ma.SOURCE_SEQUENCE_OFFSET):
            writes.append((address, value & 0xffffffff))
            during.append(sim.rd(STATE + ma.SOURCE_SEQUENCE_OFFSET))
    sim.wr = observe
    sim.call(symbols['MICROLOOPER_ADAPTER_GLOBAL_CONTEXT'], limit=256)
    assert writes[0] == (STATE + ma.SOURCE_SEQUENCE_OFFSET, previous | 1)
    assert writes[-1] == (STATE + ma.SOURCE_SEQUENCE_OFFSET, next_sequence)
    assert all(value & 1 for value in during[:-1])
    assert during[-1] == next_sequence
    report = ma.decode_snapshot([sim.rd(STATE + ma.SNAPSHOT_OFFSET + k) for k in range(16)])
    assert report['calls'] == 1
