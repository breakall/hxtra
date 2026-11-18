"""Execute the shipped startup decoder and preserve every preexisting boot owner."""
import random
import struct

import pytest

import kit_patch_amp as kit
from firmware import stock
from sharc import glasshouse_storage as storage
from sharc import microlooper_adapter as loader


@pytest.mark.parametrize('values', [list(range(1000)), [3]*5000,
    [1, 2, 3, 4]*1000, [0xffffffff, 0x80000000, 0, 0x7fffffff]*100])
def test_lz32_roundtrip_retains_arbitrary_word_bits_and_overlapping_matches(values):
    encoded = storage.encode(values)
    assert storage.decode(encoded, len(values)) == values
    assert storage.encode(values) == encoded


def test_lz32_random_sequences_and_long_literal_runs():
    rng = random.Random(7341)
    for size in (1, 2, 3, 30, 32768):
        values = [rng.randrange(0x100000000) for _ in range(size)]
        assert storage.decode(storage.encode(values), size) == values


@pytest.mark.parametrize('tokens,count', [([0], 1), ([3, 1, 2], 3),
    ([2, 1, 2], 1), ([0x80030000], 3), ([0x80030001], 3),
    ([1, 4, 0x80020001], 3), ([1, 4, 0x80040001], 3),
    ([1, -1], 1), ([1, 0x100000000], 1), ([1, 2], 0),
    ([1, 2], storage.MAX_OUTPUT_WORDS+1)])
def test_lz32_rejects_malformed_lengths_backreferences_and_words(tokens, count):
    with pytest.raises(ValueError):
        storage.decode(tokens, count)


@pytest.fixture(scope='module')
def boot_transport():
    # The ordinary model writer relocates Heap6 in this same checked routine.
    # This fixture exercises stock3.80.0 data without committing a firmware blob.
    archive = stock()
    raw = kit.l6ia.swap32(kit.get_entry_swapped(archive, 2))
    raw, _ = kit.expand_sharc_blob0_buffer(raw)
    encoded, report = storage.install(raw, 0x219000)
    return raw, encoded, report


@pytest.mark.firmware
def test_actual_encoded_decoder_reconstructs_stock_data_and_preserves_entry_state(boot_transport):
    original, encoded, report = boot_transport
    result = storage.verify_transport(encoded)
    assert result['emitted_decoder_executed']
    assert result['decoded_memory_identical']
    assert result['startup_registers_preserved'] and result['reset_vector_restored']
    assert result['original_entry'] == storage.ORIGINAL_ENTRY
    assert result['decoded_words'] == 53338
    assert not result['hardware_boot_verified']
    assert report['saved_bytes'] == 45000
    assert len(encoded) == len(original)-45000
    assert encoded[:1536] == original[:1536]  # SPI kernel is byte-identical


@pytest.mark.firmware
def test_expanded_runtime_view_has_identical_complete_original_physical_memory(boot_transport):
    from verify_atmosphere_candidate import record_physical_span, replay_physical
    original, encoded, _ = boot_transport
    before = list(loader.ldr_blocks(original))
    after = list(loader.ldr_blocks(storage.expand(encoded)))
    wanted = set()
    for record in before:
        span = record_physical_span(record)
        if span:
            wanted.update(range(*span))
    assert replay_physical(after, wanted) == replay_physical(before, wanted)
    # All retained writes keep their original sequence; the conservative alias
    # rejection makes moving the eight payload writes to reset equivalent.
    retained = [r for r in before if r[0] != 10]
    assert after[:len(retained)] == retained


@pytest.mark.firmware
def test_reset_final_init_and_source_payloads_are_pinned(boot_transport):
    original, _, _ = boot_transport
    words = list(struct.unpack(f'<{len(original)//4}I', original))
    _, _, tail, _ = storage._raw_parts(original)
    changed = bytearray(original)
    changed[-len(tail)+12+5*6] ^= 1
    with pytest.raises(ValueError, match='FINAL_INIT/reset'):
        storage.install(bytes(changed), 0x219000)
    changed = bytearray(original)
    changed[-len(tail)+12+8*6] ^= 1
    with pytest.raises(ValueError, match='FINAL_INIT/reset'):
        storage.install(bytes(changed), 0x219000)
    at = 384
    for tag, count, base, payload in loader.ldr_blocks(original):
        if tag == 10:
            words[at+3] ^= 1
            break
        at += 3+len(payload)
    changed = struct.pack(f'<{len(words)}I', *words)
    with pytest.raises(ValueError, match='payload layout/fingerprint'):
        storage.install(changed, 0x219000)


@pytest.mark.firmware
def test_late_alias_writer_is_rejected_instead_of_being_silently_reordered(boot_transport):
    original, encoded, _ = boot_transport
    for raw in (original, encoded):
        changed = kit.inject_sharc_ldr_blocks(raw, kit.pack_init_l32(0x300001, [0x12345678]))
        with pytest.raises(ValueError, match='aliases a compressed external destination'):
            if raw is original:
                storage.install(changed, 0x219000)
            else:
                storage.verify_transport(changed)


@pytest.mark.firmware
def test_loader_storage_claims_and_emitted_decoder_bytes_are_checked(boot_transport):
    original, encoded, report = boot_transport
    with pytest.raises(ValueError, match='already installed'):
        storage.install(encoded, 0x219000)
    # Existing registry data and native external program data are occupied.
    with pytest.raises(ValueError, match='outside the permanent'):
        storage.install(original, 0x200000)
    words = list(struct.unpack(f'<{len(encoded)//4}I', encoded))
    at = 384
    for tag, count, base, payload in loader.ldr_blocks(encoded):
        if tag == 4 and base == report['decoder_data_begin']:
            words[at+3] ^= 1
            break
        at += 3+len(payload)
    damaged = struct.pack(f'<{len(words)}I', *words)
    with pytest.raises(ValueError, match='decoder instructions differ'):
        storage.verify_transport(damaged)


@pytest.mark.firmware
def test_compressed_table_payload_corruption_cannot_be_expanded_as_valid_stock_code(boot_transport):
    _, encoded, _ = boot_transport
    words = list(struct.unpack(f'<{len(encoded)//4}I', encoded))
    at = 384
    for tag, count, base, payload in loader.ldr_blocks(encoded):
        if tag == 4 and base == storage.TABLE:
            # First literal after first record's header/token.
            words[at+3+storage.HEADER_WORDS+4] ^= 1
            break
        at += 3+len(payload)
    damaged = struct.pack(f'<{len(words)}I', *words)
    with pytest.raises(ValueError, match='fingerprint'):
        storage.expand(damaged)


@pytest.fixture(scope='module', params=(2, 3), ids=('NAM2-GR-click-Atmosphere', 'NAM3-click-Atmosphere'))
def combined_image(request, tmp_path_factory):
    import os
    import m4cache
    import patch_click
    import patch_comp
    import patch_glasshouse_build as build
    import patch_microlooper_build as atmosphere
    import patch_menu
    from sharc import nam_multi
    path = os.environ.get('HX_STOMP_HXF')
    if not path:
        pytest.skip('HX_STOMP_HXF is not set')
    base = m4cache.nam_base(path, str(tmp_path_factory.mktemp('glasshouse-combined')))
    image, _ = kit.load_l6ia_from_any(base)
    image, _ = build.prepare_metadata(image, dsp_cost=1000, mono_dsp_cost=900, log=lambda _: None)
    image, _ = atmosphere.prepare_metadata(image, dsp_cost=2000, mono_dsp_cost=1700, log=lambda _: None)
    entries, _ = patch_menu.menu_entries(lambda n: kit.get_entry_swapped(image, n),
        env={'HX_MICRO_LOOPER': '1', 'HX_LONG_PRESS': '1', 'HX_GR': '1', 'HX_CLICK': '1'})
    image, _, _ = kit.l6ia.rebuild_archive(image, entries)
    with nam_multi.flags(['--mid-sweep']):
        source, lay = nam_multi.build(request.param)
    image, _ = kit.patch_kernel(image, source, f'nam{request.param}.asm', relocate=False, log=lambda _: None)
    image, _ = patch_click.add_click(image, log=lambda _: None, lay=lay)
    if request.param == 2:
        image = patch_comp.patch_comp(image, log=lambda _: None)
        image = patch_comp.patch_dsp(image, log=lambda _: None, lay=lay)
    image, atmosphere_report = atmosphere.link_dsp(image, log=lambda _: None)
    before = image
    image, report = build.link_dsp(image, log=lambda _: None)
    return before, image, report, atmosphere_report


@pytest.mark.firmware
def test_combined_linker_fits_both_profiles_and_preserves_atmosphere(combined_image):
    import patch_glasshouse_build as build
    from glasshouse_definition import MODELS
    before, image, report, atmosphere_report = combined_image
    raw = kit.l6ia.swap32(kit.get_entry_swapped(image, 2))
    original_raw = kit.l6ia.swap32(kit.get_entry_swapped(before, 2))
    assert len(raw) <= 0x80000
    assert report['entry2_bytes'] == len(raw)
    assert report['entry2_remaining_bytes'] == 0x80000-len(raw)
    assert report['startup_verification']['decoded_memory_identical']
    for effect, row in zip(MODELS, report['models']):
        actual = [loader.ldr_word(raw, row['registry_address']+i) for i in range(8)]
        assert actual == [effect.primitive, row['init_entry'], 0, 0,
                          row['control_entry'], row['process_entry'], 512, 0]
        assert row['private_sdram_words'] == 0
    for row in atmosphere_report['models']:
        address = row['registry_address']
        assert [loader.ldr_word(raw, address+i) for i in range(8)] == [
            loader.ldr_word(original_raw, address+i) for i in range(8)]
    for index in range(len(kit.l6ia.parse(image))):
        if index != 2:
            assert kit.get_entry_swapped(before, index) == kit.get_entry_swapped(image, index)
    with pytest.raises(ValueError, match='already installed'):
        build.link_dsp(image, log=lambda _: None)


@pytest.mark.firmware
def test_final_combined_archive_passes_both_allocation_verifiers(combined_image):
    import hashlib
    import json
    import verify_atmosphere_candidate as atmosphere
    import verify_glasshouse_candidate as glasshouse
    _, image, report, atmosphere_report = combined_image
    atmosphere_report = dict(atmosphere_report, entry2_bytes=report['entry2_bytes'],
        entry2_remaining_bytes=report['entry2_remaining_bytes'],
        candidate_archive_sha256=hashlib.sha256(image).hexdigest())
    result = atmosphere.verify_archive(image, atmosphere_report, audio=False)
    assert result['allocation_verified_offline']
    assert result['boot_transport']['decoded_memory_identical']
    result = glasshouse.verify_archive(image, json.loads(json.dumps(report)), audio_check=False)
    assert result['allocation_verified_offline']
    assert result['boot_transport']['emitted_decoder_executed']


@pytest.mark.firmware
def test_modified_spi_boot_kernel_is_rejected_by_installer_and_runtime_verifiers(boot_transport):
    original, encoded, _ = boot_transport
    changed_original = bytearray(original)
    changed_original[47] ^= 1
    with pytest.raises(ValueError, match='SPI boot kernel fingerprint'):
        storage.install(bytes(changed_original), 0x219000)
    changed_encoded = bytearray(encoded)
    changed_encoded[47] ^= 1
    for verify in (storage.verify_transport, storage.expand):
        with pytest.raises(ValueError, match='SPI boot kernel fingerprint'):
            verify(bytes(changed_encoded))
