"""Physical external-code aliases and round-trip execution at the linked address."""
import struct

import pytest

import microlooper_placement as place
import sasm
import ssim


def test_documented_external_alias_and_least_significant_parcel_first():
    # Independent manufacturer example: ISA0x200000 occupies physical16
    #0x600000..2, equal to normal32 address0x300000 plus half the next word.
    p = place.plan(2, [], data_begin=0x300000, data_end=0x300003)
    section = sasm.Section('pm', 0x200000)
    section.words = [0x112233445566, 0xaabbccddeeff]
    record = place.pack(p, [section])
    assert record == [4, 3, 0x300000, 0x33445566, 0xeeff1122, 0xaabbccdd]
    assert p.data_end == 0x300003
    assert place.physical_span((5, 2, 0x200000, [])) == (0x600000, 0x600006)
    assert place.physical_span((4, 3, 0x300000, [])) == (0x600000, 0x600006)


@pytest.mark.parametrize('tag,base,count', [(4, 0x324ce7, 1), (1, 0x324ce7, 1),
                                         (10, 0x324ce7, 1), (5, 0x21889a, 2),
                                         (2, 0x21889a, 2), (3, 0x6499ce, 1)])
def test_refuses_boot_writes_and_zero_fills_through_every_supported_alias(tag, base, count):
    with pytest.raises(ValueError, match='overlaps boot'):
        place.plan(1236, [(tag, count, base, [])], data_begin=0x324ce6, data_end=0x328000)


def test_nominally_overlapping_addresses_in_different_spaces_are_not_false_collisions():
    p = place.plan(1236, [(4, 6076, 0x2188c4, [])],
                   data_begin=0x324ce6, data_end=0x328000)
    assert p.code_pm == 0x21889a
    assert p.data_begin == 0x324ce7
    assert p.data_end == 0x325425
    assert p.words32 == 1854


def test_alignment_exact_fit_exhaustion_and_runtime_reservation():
    p = place.plan(3, [], data_begin=0x324ce6, data_end=0x324ced)
    assert p.instructions == 4 and p.data_begin == 0x324ce7
    with pytest.raises(ValueError, match='does not fit'):
        place.plan(3, [], data_begin=0x324ce6, data_end=0x324cec)
    with pytest.raises(ValueError, match='runtime reservation'):
        place.plan(2, [], data_begin=0x324ce6, data_end=0x328000,
                   claims=[(0x324ce9, 0x324cf0)])
    # Adjacent reservations are valid; they must not overlap physically.
    place.plan(2, [], data_begin=0x324ce6, data_end=0x328000,
               claims=[(0x324500, 0x324ce7), (0x324cea, 0x328000)])


def test_unknown_external_initializer_is_not_silently_ignored():
    with pytest.raises(ValueError, match='unsupported external'):
        place.plan(2, [(6, 1, 0x324ce7, [])], data_begin=0x324ce6, data_end=0x328000)


def native_reservation_records():
    sites = ((0x17884b, 'M0', 0x328000), (0x178855, 'I4', 0xed7000),
             (0x17885e, 'R4', 0x328000), (0x1788b6, 'M3', 0x30d100),
             (0x1788c0, 'I3', 0x324497), (0x1788c9, 'R4', 0x30d100))
    out = []
    for pc, register, value in sites:
        sections, _ = sasm.assemble(f'.section pm 0xe0000\n{register} = {value};', 'heap-literal.asm')
        word = sections[0].words[0]
        out.append((3, 3, pc, [(word >> 32) << 16 | (word >> 16 & 0xffff),
                               (word & 0xffff) << 16]))
    return out


def test_native_reservation_is_checked_by_code_address_independent_of_record_order():
    records = native_reservation_records()
    assert place.require_native_reservation(reversed(records)) == (0x324497, 0x328000)


@pytest.mark.parametrize('site', range(6))
def test_any_changed_heap_start_end_or_clear_refuses_resident_placement(site):
    records = native_reservation_records()
    records[site][3][1] ^= 1 << 16
    with pytest.raises(ValueError, match='native DDR2 reservation setup changed'):
        place.require_native_reservation(records)


@pytest.mark.parametrize('instructions,begin,end', [(0, 0x324ce6, 0x328000),
                         (True, 0x324ce6, 0x328000), (2, 0x200000, 0x200100),
                         (2, 0x324ce6, 0x324ce6), (2, 0x900000, 0x900100)])
def test_invalid_reservations_are_not_accepted(instructions, begin, end):
    with pytest.raises(ValueError):
        place.plan(instructions, [], data_begin=begin, data_end=end)


def test_packed_external_bytes_execute_branches_calls_and_return_at_actual_address():
    base = place.plan(16, [], data_begin=0x324ce6, data_end=0x328000).code_pm
    source = f'''.section pm {base:#x}
    entry:
        R0 = 7;
        CALL add_value;
        R2 = 3;
        COMP(R0,R2);
        IF GT JUMP done;
        R0 = 0;
    done:
        RTS;
    add_value:
        R1 = 5;
        R0 = R0 + R1;
        RTS;
    '''
    sections, symbols = sasm.assemble(source, 'external-call.asm')
    p = place.plan(len(sections[0].words), [], data_begin=0x324ce6, data_end=0x328000)
    record = place.pack(p, sections)
    # Reconstruct instructions from the emitted normal32 boot words through
    # the documented physical16 aliases, rather than loading source sections.
    raw = struct.pack(f'<{record[1]}I', *record[3:])
    sim = ssim.Sim()
    for i in range(p.instructions):
        sim.pm[p.code_pm + i] = int.from_bytes(raw[6*i:6*i+6], 'little')
    sim.call(symbols['ENTRY'], limit=100)
    assert sim.get(0) == 12
    assert not sim.pcstk


def test_section_gaps_and_changed_instruction_counts_are_refused():
    p = place.plan(4, [], data_begin=0x324ce6, data_end=0x328000)
    first = sasm.Section('pm', p.code_pm)
    first.words = [0]
    last = sasm.Section('pm', p.code_pm + 3)
    last.words = [0]
    with pytest.raises(ValueError, match='noncontiguous'):
        place.pack(p, [first, last])
    with pytest.raises(ValueError, match='instruction count'):
        place.pack(p, [first])
    first.kind = 'dm'
    with pytest.raises(ValueError, match='PM sections'):
        place.pack(p, [first])


def micro_sections():
    import microlooper_audio as audio
    import microlooper_bridge as bridge
    import microlooper_init as callbacks
    counts = [audio.instructions(), bridge.instructions(), callbacks.instructions()]
    p = place.plan(sum(n + n % 2 for n in counts), [],
                   data_begin=0x324ce6, data_end=0x328000)
    core, symbols = audio.assemble(p.code_pm)
    bridge_base = p.code_pm + counts[0] + counts[0] % 2
    shim, bridge_symbols = bridge.assemble(bridge_base, symbols[audio.ENTRY])
    init, _ = callbacks.assemble(bridge_base + counts[1] + counts[1] % 2)
    return p, core + shim + init, bridge_symbols[bridge.ENTRY]


@pytest.mark.parametrize('mode', [0, 1, 2])
@pytest.mark.parametrize('inplace', [False, True])
def test_full_micro_engine_from_packed_external_boot_bytes_matches_internal(mode, inplace):
    import microlooper_bridge as bridge
    p, sections, process = micro_sections()
    record = place.pack(p, sections)
    raw = struct.pack(f'<{record[1]}I', *record[3:])
    runner = bridge.Bridge(core_base=p.code_pm, bridge_base=process)
    runner.sim.pm.clear()
    runner.sim.pm.update((p.code_pm + i, int.from_bytes(raw[6*i:6*i+6], 'little'))
                         for i in range(p.instructions))
    reference = bridge.Bridge()
    for who in (runner, reference):
        who.params(mode=mode, length=.63, modify=.8125, clock=1., mix=.8)
    for block in range(32):
        changes = {4: {'play': True}, 8: {'overdub': True},
                   14: {'overdub': False}, 16: {'length': .05},
                   20: {'mode': (mode + 1) % 3, 'clock': .5},
                   24: {'play': False}, 28: {'play': True}}.get(block, {})
        for who in (runner, reference):
            who.params(**changes)
        samples = [((((i*37) % 127)-63)/256., (((i*19) % 113)-56)/256.)
                   for i in range(block*16, (block+1)*16)]
        assert runner.block(samples, inplace=inplace) == reference.block(samples, inplace=inplace)
    assert runner.sim.dm == reference.sim.dm


@pytest.mark.firmware
@pytest.mark.parametrize('slots', [2, 3])
def test_baseline_nam_boot_and_runtime_reservations_are_preserved(slots):
    from firmware import stock
    import kit_patch_amp as kit
    import nam_multi
    import microlooper_adapter as loader
    import ldr_compact
    with nam_multi.flags(['--mid-sweep']):
        source, lay = nam_multi.build(slots)
    image, _ = kit.patch_kernel(stock(), source, f'nam{slots}.asm',
                               relocate=False, log=lambda _: None)
    original = kit.l6ia.swap32(kit.get_entry_swapped(image, 2))
    before = list(loader.ldr_blocks(original))
    # The unexpanded stock fixture has not moved Heap6. Model registration in
    # the complete builder does so; establish and guard that same change here.
    original, _ = kit.expand_sharc_blob0_buffer(original)
    before = list(loader.ldr_blocks(original))
    assert place.require_native_reservation(before) == (0x324497, 0x328000)
    p, sections, _ = micro_sections()
    verified = place.plan(p.instructions, before, data_begin=lay.ddr2_to,
                          data_end=nam_multi.DDR2_END, claims=lay.claims())
    assert verified == p
    record = place.pack(p, sections)
    compact, _ = ldr_compact.compact(original)
    linked = kit.inject_sharc_ldr_blocks(compact, record)
    after = list(loader.ldr_blocks(linked))
    assert after[:-1] == list(loader.ldr_blocks(compact))
    assert after[-1] == (4, p.words32, p.data_begin, tuple(record[3:]))
    assert linked[:384*4] == original[:384*4]
    # Every original resident code block and NAM table record is untouched;
    # compaction changes only equivalent zero data in eligible internal spans.
    for boot in before:
        if boot[0] in (3, 5, 10) or boot[2] == nam_multi.DDR2:
            assert boot in after
    assert p.data_begin >= lay.ddr2_to and p.data_end <= nam_multi.DDR2_END
    assert len(linked) <= 0x80000
