"""Compact injected internal NAM data using documented ZERO_LDATA LDR records.

ADI CCES Loader/Utilities Manual 2.9.0, Table10-10 and ZERO_INIT Blocks
(pp154-155): tag1 zeroes logical data words; tag4 supplies32-bit words.
Only the existing NAM internal tails are eligible. Stock records, instructions,
boot kernel and FINAL_INIT remain byte-identical. This is opt-in tooling, not a
change to default builds. Hardware boot equivalence remains a release gate.
"""
import struct

RANGES = ((0xc7674, 0xc8000), (0xe4850, 0xe8000))


def payload_words(tag, count):
    if tag in (1, 2, 7, 8):
        return 0
    if tag in (4, 9, 10):
        return count
    if tag == 3:
        return (count + 1) // 2
    if tag == 5:
        return ((count + 1) & ~1) * 3 // 2
    if tag == 6:
        return count * 2
    raise ValueError(f'unsupported LDR tag {tag}')


def pack_data(address, data):
    """Encode zero runs of at least 8 words, retaining smaller runs as data."""
    data = list(data)
    out, start, i = [], 0, 0
    while i < len(data):
        if data[i] != 0:
            i += 1
            continue
        end = i + 1
        while end < len(data) and data[end] == 0:
            end += 1
        if end - i >= 8:
            if start < i:
                out += [4, i - start, address + start, *data[start:i]]
            out += [1, end - i, address + i]
            start = end
        i = end
    if start < len(data):
        out += [4, len(data) - start, address + start, *data[start:]]
    # Header overhead must never make compaction larger than a plain record.
    plain = [4, len(data), address, *data]
    return out if len(out) < len(plain) else plain


def compact(e2_raw):
    """(raw Entry2 bytes, saved bytes); refuses unknown/truncated boot streams."""
    if len(e2_raw) % 4 or len(e2_raw) < (384 + 3) * 4:
        raise ValueError('truncated or unaligned DSP boot stream')
    words = list(struct.unpack(f'<{len(e2_raw)//4}I', e2_raw))
    i, out = 384, words[:384]
    while i + 3 <= len(words):
        tag, count, address = words[i:i+3]
        if tag == 0:
            out += words[i:]  # FINAL_INIT, executable payload and all trailing bytes.
            packed = struct.pack(f'<{len(out)}I', *out)
            return packed, len(e2_raw) - len(packed)
        size = payload_words(tag, count)
        end = i + 3 + size
        if end > len(words):
            raise ValueError('truncated LDR block')
        eligible = tag == 4 and any(low <= address and address + count <= high for low, high in RANGES)
        out += pack_data(address, words[i+3:end]) if eligible else words[i:end]
        i = end
    raise ValueError('DSP boot stream has no FINAL_INIT')
