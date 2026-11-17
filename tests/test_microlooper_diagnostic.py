"""Diagnostic linking keeps original audio graphs/allocation and proves fit."""
import struct

import pytest

import kit_patch_amp as kit
import patch_microlooper_probe as probe
from firmware import stock
from sharc import microlooper_adapter as adapter
from sharc import nam_multi
from sharc import microlooper as layout
from sharc import sasm


@pytest.fixture(scope='module')
def nam1():
    with nam_multi.flags(['--mid-sweep']):
        source, _ = nam_multi.build(1)
    image, _ = kit.patch_kernel(stock(), source, 'nam1.asm', relocate=False, log=lambda _: None)
    return image


@pytest.mark.firmware
def test_diagnostic_only_changes_entry2_and_original_process_pointer(nam1):
    out, report = probe.patch_diagnostic(nam1, log=lambda _: None)
    for index in range(len(kit.l6ia.parse(nam1))):
        if index != 2:
            assert kit.get_entry_swapped(out, index) == kit.get_entry_swapped(nam1, index)
    before = kit.l6ia.swap32(kit.get_entry_swapped(nam1, 2))
    after = kit.l6ia.swap32(kit.get_entry_swapped(out, 2))
    for i in range(8):
        expected = report['process_entry'] if i == 5 else adapter.ldr_word(before, probe.REGISTRY+i)
        assert adapter.ldr_word(after, probe.REGISTRY+i) == expected
    assert report['diagnostic_only'] and not report['native_stereo_abi_verified']
    sections, _ = adapter.assemble_diagnostic(report['pm_base'], report['sidecar_dm'])
    assert report['instructions'] == sum(len(s.words) for s in sections)
    assert report['entry2_remaining_bytes'] >= 0
    assert not report['changes_native_allocation'] and not report['changes_model_graphs']
    assert not report['telemetry_readback_implemented']
    assert all(adapter.ldr_word(after, report['sidecar_dm']+i) == 0 for i in range(200))
    with pytest.raises(ValueError, match='already instrumented'):
        probe.patch_diagnostic(out, log=lambda _: None)


@pytest.mark.firmware
def test_stock_without_verified_profile_is_rejected():
    with pytest.raises(ValueError, match='NAM1 mid-sweep'):
        probe.patch_diagnostic(stock(), log=lambda _: None)


@pytest.mark.firmware
def test_same_entrypoint_with_two_slot_kernel_is_not_accepted_as_nam1():
    with nam_multi.flags(['--mid-sweep']):
        source, _ = nam_multi.build(2)
    image, _ = kit.patch_kernel(stock(), source, 'nam2.asm', relocate=False, log=lambda _: None)
    with pytest.raises(ValueError, match='NAM1 mid-sweep'):
        probe.patch_diagnostic(image, log=lambda _: None)


@pytest.mark.firmware
@pytest.mark.parametrize('field', [1, 2, 3, 4, 6, 7])
def test_changed_native_initialization_or_allocation_is_rejected(nam1, field):
    raw = kit.l6ia.swap32(kit.get_entry_swapped(nam1, 2))
    changed = kit.inject_sharc_ldr_blocks(raw, kit.pack_init_l32(
        probe.REGISTRY+field, [probe.ORIGINAL_REGISTRY[field] ^ 1]))
    image, _, _ = kit.l6ia.rebuild_archive(nam1, {2: kit.l6ia.swap32(changed)})
    with pytest.raises(ValueError, match='registry is changed'):
        probe.patch_diagnostic(image, log=lambda _: None)


@pytest.mark.firmware
@pytest.mark.parametrize('kind', ['dm', 'pm'])
def test_existing_code_or_sidecar_reservation_is_not_overwritten(nam1, kind):
    _, report = probe.patch_diagnostic(nam1, log=lambda _: None)
    raw = kit.l6ia.swap32(kit.get_entry_swapped(nam1, 2))
    blocks = (kit.pack_init_l32(report['sidecar_dm'], [99]) if kind == 'dm'
              else kit.pack_init_l48(report['pm_base'], [0, 0]))
    raw = kit.inject_sharc_ldr_blocks(raw, blocks)
    changed, _, _ = kit.l6ia.rebuild_archive(nam1, {2: kit.l6ia.swap32(raw)})
    with pytest.raises(ValueError, match='overlaps existing'):
        probe.patch_diagnostic(changed, log=lambda _: None)


@pytest.fixture(scope='module')
def nam1_gr(nam1):
    import patch_comp
    lay = nam_multi.layout(['--mid-sweep', '--slots', '1'])
    return patch_comp.patch_dsp(nam1, log=lambda _: None, lay=lay)


@pytest.mark.firmware
def test_telemetry_links_without_changing_models_allocations_or_gr_addresses(nam1_gr):
    import patch_comp
    import patch_menu
    from firmware import reader
    from sharc import microlooper_publisher as publisher
    out, report = probe.patch_diagnostic(nam1_gr, telemetry=True, log=lambda _: None)
    assert report['telemetry_readback_implemented'] and not report['hardware_telemetry_verified']
    assert report['source_sequence_dm'] == report['sidecar_dm'] + 180
    assert report['instructions'] == report['adapter_instructions'] + report['publisher_instructions']
    assert report['entry2_remaining_bytes'] >= 0
    for index in range(len(kit.l6ia.parse(nam1_gr))):
        if index not in (0, 2):
            assert kit.get_entry_swapped(out, index) == kit.get_entry_swapped(nam1_gr, index)
    before = kit.l6ia.swap32(kit.get_entry_swapped(nam1_gr, 2))
    after = kit.l6ia.swap32(kit.get_entry_swapped(out, 2))
    # Every installed GR registry word, including all callbacks, is untouched.
    for prim, _ in patch_comp.WRAPS:
        registry = next(addr for addr in range(0x200000, 0x2008d0, 8)
                        if adapter.ldr_word(before, addr) == prim)
        assert [adapter.ldr_word(before, registry+i) for i in range(8)] == [
            adapter.ldr_word(after, registry+i) for i in range(8)]
    variant, _ = publisher.assemble_gr(report['gr_dm'], report['gr_pm'], report['publisher_pm'])
    memory = layout.pm_words(adapter.ldr_blocks(after))
    for section in variant:
        if section.kind == 'pm':
            assert [memory[section.addr+i] for i in range(len(section.words))] == section.words
    # Chaining appends to existing code rather than rebuilding its prefix.
    old = patch_menu.Patch(kit.get_entry_swapped(nam1_gr, 0), [], {})
    read = reader(kit.get_entry_swapped(out, 0))
    for address, size in ((0x28e165f0, 8), (0x28da6458, 6)):
        assert read(address, size) == old.read(address, size)


@pytest.mark.firmware
def test_telemetry_rejects_missing_or_modified_gr(nam1, nam1_gr):
    with pytest.raises(ValueError, match='installed GR process/control'):
        probe.patch_diagnostic(nam1, telemetry=True, log=lambda _: None)
    import patch_comp
    lay = nam_multi.layout(['--mid-sweep', '--slots', '1'])
    _, pm = patch_comp.dsp_place(lay)
    raw = kit.l6ia.swap32(kit.get_entry_swapped(nam1_gr, 2))
    raw = kit.inject_sharc_ldr_blocks(raw, kit.pack_init_l48(pm, [0, 0]))
    changed, _, _ = kit.l6ia.rebuild_archive(nam1_gr, {2: kit.l6ia.swap32(raw)})
    with pytest.raises(ValueError, match='existing GR code'):
        probe.patch_diagnostic(changed, telemetry=True, log=lambda _: None)


@pytest.mark.firmware
@pytest.mark.parametrize('primitive', [0x271a, 0x2719, 0x2710])
@pytest.mark.parametrize('field', [4, 5])
def test_telemetry_rejects_disconnected_gr_callback(nam1_gr, primitive, field):
    raw = kit.l6ia.swap32(kit.get_entry_swapped(nam1_gr, 2))
    registry = next(addr for addr in range(0x200000, 0x2008d0, 8)
                    if adapter.ldr_word(raw, addr) == primitive)
    # Retain the exact complete GR code, but disconnect one installed callback.
    changed = kit.inject_sharc_ldr_blocks(raw, kit.pack_init_l32(registry+field, [0x8d342]))
    image, _, _ = kit.l6ia.rebuild_archive(nam1_gr, {2: kit.l6ia.swap32(changed)})
    with pytest.raises(ValueError, match='installed GR process/control'):
        probe.patch_diagnostic(image, telemetry=True, log=lambda _: None)


@pytest.mark.parametrize('tag', [2, 5])
def test_pm_overlap_guard_intersects_a_record_starting_in_another_bank(tag):
    assert layout.internal_span(tag, 4, 0xdfffe) == (0xe0000, 0xe0003)
    assert layout.internal_span(tag, 5, 0xdfffe) == (0xe0000, 0xe0006)
    assert layout.internal_span(tag, 2, 0xdfffe) == (0, 0)


def test_pm_rewrite_preserves_boot_record_size_and_only_rewrites_final_writer():
    sections, _ = sasm.assemble('.section pm 0xe0000\n.word 1,2,3,4\n')
    replacement, _ = sasm.assemble('.section pm 0xe0000\n.word 1,2,0x123456789abc,4\n')
    first = kit.pack_init_l48(0xe0000, [1, 2, 99, 4])
    last = kit.pack_init_l48(0xe0002, [3, 4])
    words = first + last + [0, 0, 0]
    raw = bytes(384*4) + struct.pack(f'<{len(words)}I', *words)
    patched = probe._replace_pm(raw, sections[0], replacement[0])
    offset = 384*4 + len(first)*4 + 12
    assert patched[:offset] == raw[:offset] and patched[offset+6:] == raw[offset+6:]
    assert len(patched) == len(raw)
    assert layout.pm_words(adapter.ldr_blocks(patched))[0xe0002] == 0x123456789abc
    with pytest.raises(ValueError, match='exact existing GR'):
        probe._replace_pm(patched, sections[0], replacement[0])


@pytest.mark.parametrize('source', ['.section dm 0xe0000\n.word 1,2,3,4',
                                  '.section pm 0xe0002\n.word 1,2,3,4',
                                  '.section pm 0xe0000\n.word 1,2'])
def test_pm_rewrite_refuses_changed_section_extent(source):
    before, _ = sasm.assemble('.section pm 0xe0000\n.word 1,2,3,4')
    after, _ = sasm.assemble(source)
    with pytest.raises(ValueError, match='complete PM section'):
        probe._replace_pm(b'', before[0], after[0])
