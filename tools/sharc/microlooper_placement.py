"""Place Atmosphere's unchanged ISA48 code in an explicitly reserved DDR2 span.

ADSP-214xx HWR rev1.1 sections4-47..49 and4-95..96: an external ISA
address P fetches physical16 words3*P..3*P+2, least-significant parcel
first. A normal32 data address D occupies physical16 words2*D..2*D+1.
Thus an even number of ISA48 instructions can be initialized by one ordinary
INIT_LDATA record at D=3*P/2. This is permanent code, not a runtime overlay.

The caller must supply a proven disjoint reservation, not a guessed heap gap.
Encoding, native heap bounds and all recorded physical aliases are checked.
"""
from dataclasses import dataclass
import struct

NATIVE_HEAP6_BEGIN = 0x30d100
NATIVE_HEAP6_END = 0x324497


@dataclass(frozen=True)
class Placement:
    code_pm: int                   # logical48 ISA instruction address
    instructions: int              # includes explicit padding
    data_begin: int                # logical32 physical storage alias
    data_end: int                  # exclusive logical32 end

    @property
    def words32(self):
        return self.data_end - self.data_begin


def require_native_reservation(records):
    """Pin the actual moved Heap6 / unchanged Heap4 bounds in this image.

    Reads native setup instructions through their SW addresses, independent of
    file offsets and zero-data compaction. INIT16 parcels use the explicit
    high-first parcel order used by the native allocator checks. The guarded
    start/end/clear literals establish the native owners
    on either side; the caller must additionally preserve all linked claims.
    Returns (Heap6 exclusive end, Heap4 begin) in normal32 words.
    """
    short = {}
    for tag, count, base, payload in records:
        if tag == 3:
            if len(payload) * 2 < count:
                raise ValueError('truncated native INIT16 reservation setup')
            short.update((base + j, payload[j//2] >> (16 * (1-j % 2)) & 0xffff)
                         for j in range(count))
    # ISA17a immediate assignments, expressed as register/value facts rather
    # than depending on fixed raw boot-file offsets.
    sites = ((0x17884b, 0x20, 0x328000),   # Heap4 start, M0
             (0x178855, 0x14, 0xed7000),  # Heap4 end, I4
             (0x17885e, 0x04, 0x328000),  # Heap4 clear start, R4
             (0x1788b6, 0x23, NATIVE_HEAP6_BEGIN),  # moved Heap6 start, M3
             (0x1788c0, 0x13, NATIVE_HEAP6_END),    # moved Heap6 end, I3
             (0x1788c9, 0x04, NATIVE_HEAP6_BEGIN))  # moved Heap6 clear start, R4
    for pc, register, value in sites:
        actual = ((short.get(pc, -1) << 32) |
                  (short.get(pc+1, -1) << 16) | short.get(pc+2, -1))
        expected = (0x0f << 40) | (register << 32) | value
        if actual != expected:
            raise ValueError(f'native DDR2 reservation setup changed at {pc:#x}')
    return NATIVE_HEAP6_END, 0x328000


def physical_span(record):
    """External physical16 footprint, or None for an internal boot record.

    Unknown external record forms are rejected instead of assuming no alias.
    Addresses refer to the emitted loader records, not firmware-file offsets.
    """
    tag, count, base, _ = record
    if tag in (2, 5) and 0x200000 <= base < 0x600000:
        if base + count > 0x600000:
            raise ValueError('external ISA boot record exceeds ISA address range')
        return 3 * base, 3 * (base + count)
    if tag in (1, 4, 10) and 0x200000 <= base < 0x4000000:
        return 2 * base, 2 * (base + count)
    if tag == 3 and 0x600000 <= base < 0x1000000:
        return base, base + count
    if 0x200000 <= base < 0x4000000 and count:
        raise ValueError(f'unsupported external boot record tag {tag}')
    return None


def plan(instructions, records, *, data_begin, data_end, claims=()):
    """Plan within supplied normal32 DDR2 bounds, checking all physical aliases.

    ``claims`` are additional normal32 runtime reservations. The caller owns
    their completeness. Each is a (begin,end) pair with an exclusive end.
    ``records`` is the validated output of microlooper_adapter.ldr_blocks.
    """
    if type(instructions) is not int or instructions < 1:
        raise ValueError('positive integer instruction count required')
    if (type(data_begin) is not int or type(data_end) is not int or
            not 0x300000 <= data_begin < data_end <= 0x900000):
        raise ValueError('reservation must fit external ISA-addressable DDR2')
    begin = (data_begin + 2) // 3 * 3
    count = instructions + instructions % 2
    end = begin + count * 3 // 2
    # HWR4-48 reserves the last three ISA addresses to avoid fetching through
    # the ISA/VISA transition. Keep even alignment without reaching them.
    if end > data_end or 2 * end // 3 > 0x5ffffd:
        raise ValueError('Atmosphere code does not fit the supplied DDR2 reservation')
    physical = (2 * begin, 2 * end)
    for record in records:
        span = physical_span(record)
        if span and span[0] < physical[1] and physical[0] < span[1]:
            raise ValueError(f'Atmosphere code overlaps boot record at {record[2]:#x}')
    for low, high in claims:
        if not isinstance(low, int) or not isinstance(high, int) or low >= high:
            raise ValueError('runtime claims must be nonempty normal32 spans')
        if low < end and begin < high:
            raise ValueError(f'Atmosphere code overlaps runtime reservation at {low:#x}')
    return Placement(2 * begin // 3, count, begin, end)


def pack(placement, sections):
    """Encode already relocated contiguous PM sections as one INIT_LDATA record.

    Only a single alignment instruction may separate adjacent sections. All
    addresses and counts are checked before any boot record is produced.
    """
    if (placement.instructions < 2 or placement.instructions % 2 or
            not 0x200000 <= placement.code_pm < 0x5ffffd or
            placement.code_pm + placement.instructions > 0x5ffffd or
            placement.code_pm * 3 != placement.data_begin * 2 or
            placement.words32 * 2 != placement.instructions * 3):
        raise ValueError('inconsistent external code placement')
    words = []
    for section in sections:
        if section.kind != 'pm':
            raise ValueError('external code reservation accepts PM sections only')
        gap = section.addr - (placement.code_pm + len(words))
        if gap not in (0, 1):
            raise ValueError('PM sections are overlapping or noncontiguous')
        words.extend([0] * gap)
        if any(type(word) is not int or not 0 <= word < 1 << 48 for word in section.words):
            raise ValueError('invalid ISA48 instruction word')
        words.extend(section.words)
    if not words or len(words) + len(words) % 2 != placement.instructions:
        raise ValueError('assembled code does not match the planned instruction count')
    words.extend([0] * (len(words) % 2))
    raw = b''.join(word.to_bytes(6, 'little') for word in words)
    data = list(struct.unpack(f'<{len(raw)//4}I', raw))
    return [4, len(data), placement.data_begin, *data]
