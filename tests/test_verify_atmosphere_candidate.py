"""Candidate gate checks final bytes, ownership and fail-closed alias handling."""
import copy
import hashlib
import json
import os
import struct
import zlib

import pytest

import kit_patch_amp as kit
import m4cache
import patch_click
import patch_comp
import patch_menu
import patch_microlooper_build as build
import verify_atmosphere_candidate as verify
from microlooper_definition import EFFECT, MONO_EFFECT, MODELS
from patch_microlooper import REGISTRY_ADDRESSES
from sharc import microlooper as layout
from sharc import microlooper_adapter as loader
from sharc import nam_multi
from sharc import sasm


def test_existing_external_report_normalizes_without_source_instruction_counts():
    section = dict(kind='external_isa48', code_pm=0x21889a, instructions=1232,
                   data_begin=0x324ce7, data_end=0x32541f)
    assert verify.executable_sections({'code_storage': section}) == [section]


@pytest.mark.parametrize('change', [{'kind': 'unknown'}, {'instructions': 3},
                                  {'instructions': 0}, {'code_pm': 7}])
def test_bad_section_contract_is_rejected(change):
    section = dict(kind='external_isa48', code_pm=0x21889a, instructions=1232)
    section.update(change)
    with pytest.raises(ValueError):
        verify.executable_sections({'executable_sections': [section]})


def family_report():
    rows = [dict(effect=json.loads(json.dumps(effect.describe())),
                 preset_id=effect.preset_id, primitive=effect.primitive,
                 registry_address=REGISTRY_ADDRESSES[effect.name],
                 private_dm_words=effect.instance.dm_words,
                 private_pm_words=effect.instance.pm_words,
                 private_sdram_words=effect.instance.sdram_words,
                 process_entry=0x218000, control_entry=0x218100,
                 init_entry=0x218200+2*i, declared_dsp_cost=2000)
            for i, effect in enumerate(MODELS)]
    return dict(rows[0], models=rows)


@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'registry', 'width', 'ring'])
def test_family_report_cannot_invent_or_misbind_mono_allocation(mutation):
    report = family_report()
    mono = report['models'][1]
    if mutation == 'missing':
        report['models'].pop()
    elif mutation == 'duplicate':
        report['models'][1] = report['models'][0]
    elif mutation == 'registry':
        mono['registry_address'] = report['models'][0]['registry_address']
    elif mutation == 'width':
        mono['effect']['width'] = 2
    elif mutation == 'ring':
        mono['private_sdram_words'] = EFFECT.instance.sdram_words
    with pytest.raises(ValueError, match='report'):
        verify.model_reports(report)


def test_mono_memory_guard_rejects_right_buffers_and_stereo_ring_extent():
    runner = verify.bridge.Bridge(channels=1)
    verify.guard_audio_memory(runner, MONO_EFFECT)
    for address in (0xb8010, 0xb8110, runner.ring+24000, runner.state+163):
        with pytest.raises(ValueError, match='reads outside'):
            runner.sim.rd(address)
        with pytest.raises(ValueError, match='writes outside'):
            runner.sim.wr(address, 0)
    assert runner.block([.125]*16) == pytest.approx([.125]*16)


def test_late_external_instruction_alias_is_rejected_instead_of_simulating_old_data():
    pm, dm = 0x21889a, 0x324ce7
    span = (2*dm, 2*dm+6)
    records = [(4, 3, dm, [1, 2, 3]), (5, 2, pm, [0, 0, 0])]
    with pytest.raises(ValueError, match='late boot write'):
        verify.require_last_writer_space(records, span, 'external_isa48')
    # Reversing the order is valid: the complete data initializer wins.
    verify.require_last_writer_space(list(reversed(records)), span, 'external_isa48')


def test_late_internal_data_alias_is_rejected_but_earlier_clear_is_allowed():
    pm = 0xe5300
    dm = layout.normal_word(pm)
    span = (2*dm, 2*dm+6)
    records = [(5, 2, pm, [1, 2, 3]), (1, 3, dm, [])]
    with pytest.raises(ValueError, match='late boot write'):
        verify.require_last_writer_space(records, span, 'internal_isa48')
    verify.require_last_writer_space(list(reversed(records)), span, 'internal_isa48')


@pytest.fixture(scope='module')
def candidate(tmp_path_factory):
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    base = m4cache.nam_base(stock, str(tmp_path_factory.mktemp('candidate-base')))
    data, _ = kit.load_l6ia_from_any(base)
    data, _ = build.prepare_metadata(data, dsp_cost=7200, log=lambda _: None)
    with nam_multi.flags(['--mid-sweep']):
        source, lay = nam_multi.build(2)
    data, _ = kit.patch_kernel(data, source, 'nam2.asm', relocate=False, log=lambda _: None)
    data, _ = patch_click.add_click(data, log=lambda _: None, lay=lay)
    data = patch_comp.patch_comp(data, log=lambda _: None)
    data = patch_comp.patch_dsp(data, log=lambda _: None, lay=lay)
    updates, _ = patch_menu.menu_entries(lambda n: kit.get_entry_swapped(data, n),
                                        env={'HX_MICRO_LOOPER': '1', 'HX_LONG_PRESS': '1'})
    data, _, _ = kit.l6ia.rebuild_archive(data, updates)
    return build.link_dsp(data, log=lambda _: None)


@pytest.mark.firmware
@pytest.mark.parametrize('mutation', [None, 'md5', 'directory', 'chunk_extent'])
def test_hxf_envelope_integrity_and_actual_stomp_region_version(candidate, tmp_path, mutation):
    data, _ = candidate
    entries = kit.l6ia.parse(data)
    end = entries[-1]['payload_off']+entries[-1]['payload_len']
    head = bytearray(52)
    struct.pack_into('>H', head, 10, 6)
    struct.pack_into('>I', head, 16, len(data))
    head[20:36] = hashlib.md5(data).digest()
    if mutation == 'md5':
        head[20] ^= 1
    chunks = [(b'HEAD', head), (b'dinf', struct.pack('>4I', 0, 0x10000, 0, end)),
              (b'dinf', struct.pack('>4I', 5, 0x10000, end+(mutation == 'directory'), len(data)-end)),
              (b'data', zlib.compress(data, 1))]
    body = bytearray(b'L6FF')
    for kind, payload in chunks:
        body += kind+struct.pack('>I', len(payload))+payload+bytes(len(payload) % 2)
    if mutation == 'chunk_extent':
        body[-1:] = b''
    raw = b'FORM'+struct.pack('>I', len(body))+body
    path = tmp_path/'candidate.hxf'
    path.write_bytes(raw)
    if mutation:
        with pytest.raises(ValueError):
            verify.load_image(path)
    else:
        assert verify.load_image(path) == data


@pytest.mark.firmware
def test_complete_built_image_gate_runs_native_callbacks_and_independent_oracle(candidate):
    data, report = candidate
    result = verify.verify_archive(data, report)
    assert result['allocation_verified_offline'] and result['audio_verified_offline']
    assert result['nam_slots'] == 2 and result['declared_dsp_cost'] == 7200
    assert result['audio']['stereo_frames'] == 3136
    assert result['audio']['mono_frames'] == 3136
    assert result['audio']['cases'] == 14
    assert {r['width'] for r in result['audio']['models']} == {1, 2}
    assert result['audio']['maximum_absolute_error'] <= 2e-6
    assert not result['hardware_timing_verified'] and not result['hardware_audio_qualified']


@pytest.mark.firmware
def test_allocation_only_cannot_claim_audio_or_callback_execution(candidate):
    data, report = candidate
    result = verify.verify_archive(data, report, audio=False)
    assert result['allocation_verified_offline']
    assert not result['audio_verified_offline'] and 'audio' not in result


@pytest.mark.firmware
def test_corrupt_container_is_rejected_before_metadata_or_execution(candidate):
    data, report = candidate
    data = bytearray(data)
    data[kit.l6ia.parse(data)[2]['payload_off']+1800] ^= 1
    with pytest.raises(ValueError, match='Fletcher mismatch'):
        verify.verify_archive(bytes(data), report, audio=False)


@pytest.mark.firmware
def test_correctly_checksummed_boot_alias_is_rejected(candidate):
    data, report = candidate
    e2 = kit.l6ia.swap32(kit.get_entry_swapped(data, 2))
    e2 = kit.inject_sharc_ldr_blocks(e2, kit.pack_init_l48(report['pm_base'], [0, 0]))
    changed, _, _ = kit.l6ia.rebuild_archive(data, {2: kit.l6ia.swap32(e2)})
    report = dict(report, entry2_bytes=len(e2),
                  entry2_remaining_bytes=layout.ENTRY2_INJECTION_LIMIT-len(e2))
    with pytest.raises(ValueError, match='late boot write'):
        verify.verify_archive(changed, report, audio=False)


@pytest.mark.firmware
def test_report_cannot_expand_its_own_reservation(candidate):
    data, report = candidate
    report = copy.deepcopy(report)
    section = report.get('executable_sections', [report['code_storage']])[0]
    section['data_end'] = (nam_multi.DDR2_END//3+2)*3
    section['instructions'] = (section['data_end']-section['data_begin'])*2//3
    report['code_storage'].update(data_end=section['data_end'], instructions=section['instructions'])
    with pytest.raises(ValueError, match='proven reservation'):
        verify.verify_archive(data, report, audio=False)


@pytest.mark.firmware
def test_report_cannot_choose_a_different_callback(candidate):
    data, report = candidate
    report = dict(report, process_entry=report['process_entry']+2)
    with pytest.raises(ValueError, match='primitive registry'):
        verify.verify_archive(data, report, audio=False)


@pytest.mark.firmware
@pytest.mark.parametrize('field', ['preset_id', 'primitive', 'private_dm_words',
                                  'private_pm_words', 'private_sdram_words', 'entry2_bytes'])
def test_report_resource_fields_bind_to_actual_image_and_contract(candidate, field):
    data, report = candidate
    report = dict(report)
    report[field] += 1
    with pytest.raises(ValueError, match='report identity/private-allocation/partition'):
        verify.verify_archive(data, report, audio=False)


@pytest.mark.firmware
def test_parameter_graph_must_still_deliver_play_to_the_declared_pid(candidate):
    data, report = candidate
    info = kit.parse_entry3_full(kit.get_entry_swapped(data, 3))
    item = kit.find_model(info, build.EFFECT.name)
    e4 = kit.get_entry_swapped(data, 4)
    words = struct.unpack(f'<{len(e4)//4}I', e4)
    blob = list(kit.entry4_blob.blob(words, item['blob_index']))
    pmap, count, play = blob[6], len(build.EFFECT.parameters), 5
    writer = pmap+blob[pmap]+10*(count+play)
    blob[pmap+blob[writer]+1] = 11
    changed, _, _ = kit.l6ia.rebuild_archive(data, {4: patch_comp.e4_replace_blob(e4, item['blob_index'], blob)})
    with pytest.raises(ValueError, match='parameter map'):
        verify.verify_archive(changed, report, audio=False)


@pytest.mark.firmware
def test_native_init_callback_executes_image_bytes_instead_of_source(candidate):
    data, report = candidate
    e2 = bytearray(kit.l6ia.swap32(kit.get_entry_swapped(data, 2)))
    sections, _ = sasm.assemble('.section pm 0\nR0 = 0;\n', 'bad_init.asm')
    word = sections[0].words[0]
    cursor = 384*4
    for tag, count, base, payload in loader.ldr_blocks(e2):
        if tag == 4 and base == report['code_storage']['data_begin']:
            offset = cursor+12+6*(report['init_entry']-report['pm_base'])
            e2[offset:offset+6] = word.to_bytes(6, 'little')
            break
        cursor += 12+len(payload)*4
    else:
        raise AssertionError('candidate callback storage absent')
    changed, _, _ = kit.l6ia.rebuild_archive(data, {2: kit.l6ia.swap32(bytes(e2))})
    with pytest.raises(ValueError, match='native callback writes outside instance|native init did not reset transport|native init channel count'):
        verify.verify_archive(changed, report)


@pytest.mark.firmware
@pytest.mark.parametrize('neighbor', ['nam_cold_code', 'nam_data', 'gr', 'click', 'native_heap_setup'])
def test_late_physical_alias_cannot_corrupt_other_native_owners(candidate, neighbor):
    data, report = candidate
    e2 = kit.l6ia.swap32(kit.get_entry_swapped(data, 2))
    baseline = layout.require_baseline(list(loader.ldr_blocks(e2)))
    if neighbor == 'nam_cold_code':
        address = layout.normal_word(baseline.cold_pm)
        extra = kit.pack_init_l32(address, [0xdeadbeef])
    elif neighbor == 'nam_data':
        # The DDR2 NAM table begins on a complete ISA-alias boundary.
        pm = (nam_multi.DDR2+2)//3*2
        extra = kit.pack_init_l48(pm, [0, 0])
    elif neighbor == 'gr':
        _, pm = patch_comp.dsp_place(baseline)
        extra = kit.pack_init_l32(layout.normal_word(pm), [0xdeadbeef])
    elif neighbor == 'click':
        pm = patch_click.pm_base(patch_click.kernel_size(), baseline)
        extra = kit.pack_init_l32(layout.normal_word(pm), [0xdeadbeef])
    else:
        extra = kit.pack_init_l32(0x17884b//2, [0xdeadbeef])
    e2 = kit.inject_sharc_ldr_blocks(e2, extra)
    changed, _, _ = kit.l6ia.rebuild_archive(data, {2: kit.l6ia.swap32(e2)})
    report = dict(report, entry2_bytes=len(e2),
                  entry2_remaining_bytes=layout.ENTRY2_INJECTION_LIMIT-len(e2))
    with pytest.raises(ValueError, match='aliased boot writes change pinned NAM/native neighbor'):
        verify.verify_archive(changed, report, audio=False)


@pytest.mark.firmware
def test_native_callback_cannot_write_one_word_past_its_allocation(candidate):
    data, report = candidate
    e2 = bytearray(kit.l6ia.swap32(kit.get_entry_swapped(data, 2)))
    sections, _ = sasm.assemble(f'.section pm 0\nDM({EFFECT.instance.dm_words},I4) = R0;\n', 'bad_store.asm')
    word = sections[0].words[0]
    cursor = 384*4
    # Init sets I4=private state; its shared C return begins seven words in.
    target = report['init_entry']+7
    for tag, count, base, payload in loader.ldr_blocks(e2):
        if tag == 4 and base == report['code_storage']['data_begin']:
            offset = cursor+12+6*(target-report['pm_base'])
            e2[offset:offset+6] = word.to_bytes(6, 'little')
            break
        cursor += 12+len(payload)*4
    else:
        raise AssertionError('candidate callback storage absent')
    changed, _, _ = kit.l6ia.rebuild_archive(data, {2: kit.l6ia.swap32(bytes(e2))})
    with pytest.raises(ValueError, match='native callback writes outside instance'):
        verify.verify_archive(changed, report)


@pytest.mark.firmware
def test_correctly_checksummed_audio_change_is_caught_by_final_byte_execution(candidate):
    data, report = candidate
    e2 = bytearray(kit.l6ia.swap32(kit.get_entry_swapped(data, 2)))
    sections, _ = sasm.assemble('.section pm 0\nRTS (LR);\n', 'bad_core.asm')
    word = sections[0].words[0]
    cursor = 384*4
    for tag, count, base, payload in loader.ldr_blocks(e2):
        if tag == 4 and base == report['code_storage']['data_begin']:
            e2[cursor+12:cursor+18] = word.to_bytes(6, 'little')
            break
        cursor += 12+len(payload)*4
    else:
        raise AssertionError('candidate core storage absent')
    changed, _, _ = kit.l6ia.rebuild_archive(data, {2: kit.l6ia.swap32(bytes(e2))})
    # Layout/integrity remain valid; only execution reveals the dry-output bug.
    assert verify.verify_archive(changed, report, audio=False)['allocation_verified_offline']
    with pytest.raises(ValueError, match=r'C\+\+ audio mismatch'):
        verify.verify_archive(changed, report)


def replace_external_instruction(data, report, pc, source):
    """Mutate a real emitted ISA word and repair the archive checksums."""
    e2 = bytearray(kit.l6ia.swap32(kit.get_entry_swapped(data, 2)))
    sections, _ = sasm.assemble('.section pm 0\n'+source+'\n', 'bad_candidate.asm')
    word = sections[0].words[0]
    cursor = 384*4
    for tag, count, base, payload in loader.ldr_blocks(e2):
        if tag == 4 and 4*base <= 6*pc and 6*pc+6 <= 4*(base+count):
            offset = cursor+12+6*pc-4*base
            e2[offset:offset+6] = word.to_bytes(6, 'little')
            break
        cursor += 12+len(payload)*4
    else:
        raise AssertionError('candidate external ISA word absent')
    changed, _, _ = kit.l6ia.rebuild_archive(data, {2: kit.l6ia.swap32(bytes(e2))})
    return changed


@pytest.mark.firmware
def test_mono_native_initializer_cannot_silently_select_stereo(candidate):
    data, report = candidate
    mono = next(row for row in report['models'] if row['preset_id'] == MONO_EFFECT.preset_id)
    changed = replace_external_instruction(data, report, mono['init_entry'], 'R1 = 2;')
    assert verify.verify_archive(changed, report, audio=False)['allocation_verified_offline']
    with pytest.raises(ValueError, match='native init channel count'):
        verify.verify_archive(changed, report)


@pytest.mark.firmware
def test_actual_shared_process_must_not_read_right_buffer_for_mono(candidate):
    data, report = candidate
    # The bridge's delay NOP precedes its first R0 spill. The extra read is legal
    # for stereo and must fail for mono even if it does not affect output audio.
    changed = replace_external_instruction(data, report, report['process_entry']+2,
                                           'R0 = DM(16,I1);')
    assert verify.verify_archive(changed, report, audio=False)['allocation_verified_offline']
    with pytest.raises(ValueError, match='reads outside its instance/buffers at 0xb8010'):
        verify.verify_archive(changed, report)


@pytest.mark.firmware
def test_mono_registry_cannot_bind_existing_stereo_primitive(candidate):
    data, report = candidate
    e2 = kit.l6ia.swap32(kit.get_entry_swapped(data, 2))
    e2 = kit.inject_sharc_ldr_blocks(e2, kit.pack_init_l32(
        REGISTRY_ADDRESSES[MONO_EFFECT.name], [EFFECT.primitive]))
    changed, _, _ = kit.l6ia.rebuild_archive(data, {2: kit.l6ia.swap32(e2)})
    report = dict(report, entry2_bytes=len(e2),
                  entry2_remaining_bytes=layout.ENTRY2_INJECTION_LIMIT-len(e2))
    with pytest.raises(ValueError, match='primitive registry'):
        verify.verify_archive(changed, report, audio=False)


@pytest.mark.firmware
@pytest.mark.parametrize('field', ['width', 'ring'])
def test_actual_mono_graph_cannot_allocate_stereo_width_or_history(candidate, field):
    data, report = candidate
    e4 = kit.get_entry_swapped(data, 4)
    info = kit.parse_entry3_full(kit.get_entry_swapped(data, 3))
    item = kit.find_model(info, MONO_EFFECT.name)
    words = struct.unpack(f'<{len(e4)//4}I', e4)
    model_blob = kit.entry4_blob.blob(words, item['blob_index'])
    blob = kit.entry4_blob.blob(words, 0)
    graph = kit.entry4_blob.parse_composite(blob, kit.entry4_blob.top_type(model_blob))
    member = graph['members_off']+20
    changed_e4 = bytearray(e4)
    _, blob_offset = kit.entry4_blob.directory(words)[0]
    if field == 'width':
        for offset in (7, 9):
            struct.pack_into('<I', changed_e4, 4*(blob_offset+member+offset), 2)
    else:
        struct.pack_into('<I', changed_e4, 4*(blob_offset+member+15), EFFECT.instance.sdram_words)
    changed, _, _ = kit.l6ia.rebuild_archive(data, {4: bytes(changed_e4)})
    with pytest.raises(ValueError, match='native instance contract or history allocation'):
        verify.verify_archive(changed, report, audio=False)
