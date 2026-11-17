"""Boot-memory equivalence for opt-in NAM zero-data encoding."""
import struct

import pytest

import ldr_compact as lc
import kit_patch_amp as pa
from firmware import stock


def decode(raw):
    words = struct.unpack(f'<{len(raw)//4}I', raw)
    memory, other, i = {}, [], 384
    while words[i] != 0:
        tag, count, address = words[i:i+3]
        size = lc.payload_words(tag, count)
        if tag == 4:
            memory.update((address+k, v) for k, v in enumerate(words[i+3:i+3+count]))
        elif tag == 1:
            memory.update((address+k, 0) for k in range(count))
        else:
            other.append(words[i:i+3+size])
        i += 3 + size
    return words[:384], memory, other, words[i:]


@pytest.mark.parametrize('data', [[0]*100, [1]+[0]*32+[2], [0]*16+[1]+[0]*16,
                                [1, 0]*40, [0]*15, [0]*16, [3]*50, []])
def test_zero_record_encoding_replays_identical_memory(data):
    original = pa.pack_init_l32(0xe4850, data)
    raw = struct.pack(f'<{384+len(original)+3}I', *([0]*384+original+[0, 0, 0]))
    encoded, saved = lc.compact(raw)
    assert decode(encoded) == decode(raw)
    assert saved >= 0
    assert len(encoded) <= len(raw)


def test_preserves_stock_regions_code_final_init_and_later_overwrites():
    init = pa.pack_init_l32(0xe4850, [0]*64)
    init += pa.pack_init_l32(0xe485a, [9,8])
    init += pa.pack_init_l32(0x90000, [0]*64)
    init += pa.pack_init_l48(0xe5000, [0]*20)
    words = list(range(384))+init+[0, 7, 8, 90, 91, 92]
    raw = struct.pack(f'<{len(words)}I', *words)
    out, saved = lc.compact(raw)
    assert saved == 64*4
    assert decode(out) == decode(raw)
    assert lc.compact(out) == (out, 0)


@pytest.mark.parametrize('raw', [b'', b'x', bytes(384*4)+struct.pack('<4I', 4,100,0xe4850,1),
                                 bytes(384*4)+struct.pack('<3I', 99,0,0)])
def test_malformed_or_unknown_stream_is_not_rewritten(raw):
    with pytest.raises(ValueError):
        lc.compact(raw)


@pytest.mark.firmware
def test_generated_nam_data_compresses_with_identical_boot_memory():
    import nam_multi
    original = stock()
    with nam_multi.flags(['--mid-sweep']):
        asm, _ = nam_multi.build(2)
    patched, _ = pa.patch_kernel(original, asm, 'nam.asm', relocate=False, log=lambda _: None)
    raw = pa.l6ia.swap32(pa.get_entry_swapped(patched, 2))
    out, saved = lc.compact(raw)
    assert decode(raw) == decode(out)
    assert saved >= 3184  # known all-zero NAM staging region; full profile fit is checked separately
