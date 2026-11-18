"""Validated SHARC loader records and native internal-DM address ranges."""
import struct

INTERNAL_DM_RANGES = ((0x92000, 0x9e000), (0xb2000, 0xbe000),
                      (0xc0000, 0xc8000), (0xe0000, 0xe8000))


def ldr_blocks(e2):
    """Yield validated raw boot records, without inferring a short-word lane order."""
    if len(e2) % 4 or len(e2) < 384 * 4:
        raise ValueError('truncated or unaligned LDR')
    words = struct.unpack('<%dI' % (len(e2) // 4), e2)
    sizes = {1: lambda n: 0, 2: lambda n: 0, 7: lambda n: 0, 8: lambda n: 0,
             5: lambda n: ((n + 1) & ~1) * 3 // 2, 4: lambda n: n,
             3: lambda n: (n + 1) // 2, 6: lambda n: n * 2,
             10: lambda n: n, 9: lambda n: n,
             **{tag: (lambda n: 0) for tag in (1, 2, 7, 8, 11, 12)}}
    i = 384
    while i + 3 <= len(words):
        tag, count, base = words[i:i + 3]
        if tag == 0:
            return
        if tag not in sizes:
            raise ValueError(f'unsupported LDR tag {tag}')
        size = sizes[tag](count)
        if i + 3 + size > len(words):
            raise ValueError('truncated LDR block')
        yield tag, count, base, words[i + 3:i + 3 + size]
        i += 3 + size
    raise ValueError('LDR has no FINAL_INIT')


def ldr_word(e2, address):
    """Read a normal-word INIT32 location; later boot blocks override earlier ones."""
    found = None
    for tag, count, base, payload in ldr_blocks(e2):
        if tag == 4 and base <= address < base + count:
            found = payload[address - base]
        elif tag == 1 and base <= address < base + count:
            found = 0
    return found
