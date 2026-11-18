"""Checked LZ32 transport for the HX Stomp's existing external DSP boot data.

The stock SPI kernel is unchanged. Its normal INIT_LDATA records load an LZ32
stream in temporary Heap4 memory; a guarded reset-vector jump decodes the stock
INIT_EXT16 payloads before the original application entry. The startup routine
restores the original reset jump and every register it uses. The compressed
stream is dead before the native Heap4 allocator initializes that same memory.

This changes startup representation only. It does not free runtime memory or
prove hardware startup timing. Tests execute the emitted ISA48 decoder and
compare its complete destination memory with the original loader records.
"""
from functools import lru_cache
import hashlib
import struct

import sasm
import ssim
from sharc import microlooper_adapter as loader
from sharc import microlooper_placement as placement

MAGIC = 0x47484c5a  # GHLZ
VERSION = 1
SCRATCH = 0x330000
TABLE = 0x330100
STAGING_END = 0x350000
ORIGINAL_RESET = 0x063e0008ea4f
ORIGINAL_SPI_KERNEL_SHA256 = '8ff4b3ba0c203b14037d39811ab9ae9bad885b0a60551a3b17224899cbf47ef7'
ORIGINAL_ENTRY = 0x8ea4f
ORIGINAL_FINAL_SHA256 = '4bb0851eb17ea084f0ddb746ac6ba1d5a41a42cefe00b80674112ec6268d096e'
ORIGINAL_EXTERNAL_SHA256 = '2c948889954a6102d42ffd276c18ace5eb6233af1bc2ebdffce11b21477b395f'
ORIGINAL_EXTERNAL_RECORDS = ((0x300000, 6357), (0x3018d7, 685),
    (0x301b88, 94), (0x301bea, 249), (0x301ce6, 9951),
    (0x3043c8, 32007), (0x30c0d1, 78), (0x30c122, 3917))
RESET_PM = 0x8c005
RESET_NORMAL = 0x92007
MAX_OUTPUT_WORDS = 0x100000
IRPTEN = 1 << 12  # ADSP-2136x/2137x/214xx Programming Reference, MODE1
HEADER_WORDS = 6
SAVED = ('R0', 'R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7',
         'I0', 'I1', 'I2', 'M0', 'ASTATX', 'ASTATY', 'STKYX', 'STKYY')


def _uint(value, name):
    if type(value) is not int or not 0 <= value <= 0xffffffff:
        raise ValueError(f'{name} must be a uint32')


def encode(words):
    """Deterministic LZ over uint32 words, with 16-bit backward distances.

    Positive tokens are literal counts; bit31 tokens encode a length in bits
    16..30 and a distance in bits0..15. Matching may overlap its own output.
    """
    words = list(words)
    for value in words:
        _uint(value, 'LZ word')
    out, literals, history, at = [], [], {}, 0
    while at < len(words):
        key = tuple(words[at:at+3])
        best, match = 0, 0
        for previous in history.get(key, ())[-32:]:
            if at-previous > 0xffff:
                continue
            length = 0
            while length < min(0x7fff, len(words)-at) and words[previous+length] == words[at+length]:
                length += 1
            if length > best:
                best, match = length, previous
        if best >= 3:
            if literals:
                out.extend((len(literals), *literals))
                literals = []
            out.append(0x80000000 | best << 16 | at-match)
            count = best
        else:
            literals.append(words[at])
            count = 1
            if len(literals) == 0x7fff:
                out.extend((len(literals), *literals))
                literals = []
        for i in range(at, at+count):
            history.setdefault(tuple(words[i:i+3]), []).append(i)
        at += count
    if literals:
        out.extend((len(literals), *literals))
    return out


def decode(tokens, count):
    """Bounded independent host decoder; reject truncated or noncanonical data."""
    if type(count) is not int or not 0 < count <= MAX_OUTPUT_WORDS:
        raise ValueError('invalid LZ output count')
    tokens, out, at = list(tokens), [], 0
    for value in tokens:
        _uint(value, 'LZ token')
    while at < len(tokens):
        token = tokens[at]
        at += 1
        if token & 0x80000000:
            length, distance = token >> 16 & 0x7fff, token & 0xffff
            if length < 3 or not 0 < distance <= len(out) or length > count-len(out):
                raise ValueError('invalid LZ backreference')
            for _ in range(length):
                out.append(out[-distance])
        else:
            length = token
            if not 0 < length <= 0x7fff or length > count-len(out) or at+length > len(tokens):
                raise ValueError('invalid LZ literal')
            out.extend(tokens[at:at+length])
            at += length
    if len(out) != count:
        raise ValueError('LZ output count differs')
    return out


def _raw_parts(raw):
    if hashlib.sha256(raw[:384*4]).hexdigest() != ORIGINAL_SPI_KERNEL_SHA256:
        raise ValueError('stock DSP SPI boot kernel fingerprint differs')
    records = list(loader.ldr_blocks(raw))
    words = list(struct.unpack(f'<{len(raw)//4}I', raw))
    final = 384 + sum(3+len(record[3]) for record in records)
    if words[final] != 0 or len(words)-final != 387:
        raise ValueError('unsupported FINAL_INIT shape')
    tail = struct.pack(f'<{len(words)-final}I', *words[final:])
    reset = int.from_bytes(tail[12+5*6:12+6*6], 'little')
    return records, words[:384], tail, reset


def _flat_record(record):
    tag, count, address, payload = record
    return [tag, count, address, *payload]


def _table_record(raw):
    found = [record for record in loader.ldr_blocks(raw)
             if record[0] == 4 and record[2] == TABLE and record[3][:2] == (MAGIC, VERSION)]
    if len(found) != 1:
        raise ValueError('one Glasshouse LZ transport table required')
    return found[0]


def has_transport(raw):
    return any(t == 4 and a == TABLE and p[:2] == (MAGIC, VERSION)
               for t, _, a, p in loader.ldr_blocks(raw))


def table_records(raw):
    """Validated original EXT16 records recovered from the emitted transport."""
    _, count, _, payload = _table_record(raw)
    if count != len(payload) or len(payload) < HEADER_WORDS+1:
        raise ValueError('truncated Glasshouse LZ transport header')
    magic, version, total, record_count, decoder_pm, decoder_count = payload[:HEADER_WORDS]
    if total != count or not record_count or not decoder_count or decoder_pm % 2:
        raise ValueError('invalid Glasshouse LZ transport header')
    if TABLE+count > STAGING_END:
        raise ValueError('Glasshouse LZ transport exceeds staging memory')
    at, records, previous_end = HEADER_WORDS, [], 0
    for _ in range(record_count):
        if at+3 > count:
            raise ValueError('truncated Glasshouse LZ record')
        address, output_count, encoded_count = payload[at:at+3]
        at += 3
        if not 0x300000 <= address < address+output_count <= placement.NATIVE_HEAP6_BEGIN:
            raise ValueError('LZ destination is outside stock external program memory')
        if address < previous_end or encoded_count > count-at:
            raise ValueError('overlapping or truncated Glasshouse LZ record')
        data = decode(payload[at:at+encoded_count], output_count)
        at += encoded_count
        records.append((10, output_count, address, tuple(data)))
        previous_end = address+output_count
    if at != count-1 or payload[at] != 0:
        raise ValueError('Glasshouse LZ transport has trailing data')
    if tuple((r[2], r[1]) for r in records) != ORIGINAL_EXTERNAL_RECORDS:
        raise ValueError('stock external DSP record layout differs')
    fingerprint = hashlib.sha256(b''.join(struct.pack(f'<{len(r[3])}I', *r[3]) for r in records)).hexdigest()
    if fingerprint != ORIGINAL_EXTERNAL_SHA256:
        raise ValueError('stock external DSP payload fingerprint differs')
    return records


def _require_disjoint_external_owners(records, originals):
    """Moving EXT16 writes to reset must not change any retained last writer."""
    spans = [(2*r[2], 2*(r[2]+r[1])) for r in originals]
    for record in records:
        if record in originals:
            continue
        span = placement.physical_span(record)
        if span and any(span[0] < hi and lo < span[1] for lo, hi in spans):
            raise ValueError('retained boot writer aliases a compressed external destination')


def expand(raw):
    """Return a replay-only boot stream including data produced at reset.

    The returned stream can exceed the on-device partition. It is a verifier
    view, never an output firmware payload. Integrity checks use the actual raw
    stream; simulators use this view to see original code after startup.
    """
    if not has_transport(raw):
        return raw
    records, kernel, tail, _ = _raw_parts(raw)
    original = table_records(raw)
    _require_disjoint_external_owners(records, original)
    out = list(kernel)
    for record in records:
        out.extend(_flat_record(record))
    for record in original:
        out.extend(_flat_record(record))
    restored_tail = bytearray(tail)
    restored_tail[12+5*6:12+6*6] = ORIGINAL_RESET.to_bytes(6, 'little')
    return struct.pack(f'<{len(out)}I', *out)+bytes(restored_tail)


def decoder_source(base):
    """A stack-free startup decoder; no dependency on the native C runtime."""
    save = '\n'.join(f'DM({SCRATCH+2+i:#x}) = {name};' for i, name in enumerate(SAVED))
    # MODE1 is restored last so all data and address-generator restoration is
    # scalar, irrespective of the power-on/SPI-kernel mode.
    restore = '\n'.join(f'{name} = DM({SCRATCH+2+i:#x});' for i, name in enumerate(SAVED))
    return f'''
.section pm {base:#x}
GLASSHOUSE_UNPACK:
DM({SCRATCH:#x}) = MODE1;
BIT CLR MODE1 {ssim.PEYEN | ssim.BDCST1 | ssim.BDCST9 | ssim.CBUFEN | IRPTEN:#x};
NOP;
{save}
M0 = 1;
I0 = {TABLE+HEADER_WORDS:#x};
gh_record:
R6 = DM(I0,M0);
R6 = PASS R6;
IF EQ JUMP gh_done;
I1 = R6;
R1 = DM(I0,M0);
R7 = DM(I0,M0);
R0 = I0;
R7 = R0 + R7;
gh_token:
R1 = PASS R1;
IF EQ JUMP gh_record_end;
R0 = I0;
COMPU(R0,R7);
IF GE JUMP gh_bad;
R0 = DM(I0,M0);
R0 = PASS R0;
IF LT JUMP gh_match;
R3 = R0;
R3 = PASS R3;
IF EQ JUMP gh_bad;
COMPU(R3,R1);
IF GT JUMP gh_bad;
R4 = I0;
R4 = R4 + R3;
COMPU(R4,R7);
IF GT JUMP gh_bad;
gh_literal:
R4 = DM(I0,M0);
DM(I1,M0) = R4;
R1 = R1 - 1;
R3 = R3 - 1;
IF GT JUMP gh_literal;
JUMP gh_token;
gh_match:
R3 = FEXT R0 BY 16:15;
R2 = FEXT R0 BY 0:16;
R4 = 3;
COMPU(R3,R4);
IF LT JUMP gh_bad;
COMPU(R3,R1);
IF GT JUMP gh_bad;
R2 = PASS R2;
IF EQ JUMP gh_bad;
R4 = I1;
R4 = R4 - R6;
COMPU(R2,R4);
IF GT JUMP gh_bad;
R4 = I1;
R4 = R4 - R2;
I2 = R4;
gh_copy:
R4 = DM(I2,M0);
DM(I1,M0) = R4;
R1 = R1 - 1;
R3 = R3 - 1;
IF GT JUMP gh_copy;
JUMP gh_token;
gh_record_end:
R0 = I0;
COMPU(R0,R7);
IF NE JUMP gh_bad;
JUMP gh_record;
gh_done:
// Restore the native reset vector through its normal32 physical alias.
// The low half of the first word belongs to the preceding instruction.
R0 = DM({RESET_NORMAL:#x});
R1 = 0xffff;
R0 = R0 AND R1;
R1 = {(ORIGINAL_RESET & 0xffff) << 16:#x};
R0 = R0 OR R1;
DM({RESET_NORMAL:#x}) = R0;
R0 = {ORIGINAL_RESET >> 16:#x};
DM({RESET_NORMAL+1:#x}) = R0;
FLUSH CACHE;
{restore}
MODE1 = DM({SCRATCH:#x});
NOP;
JUMP {ORIGINAL_ENTRY:#x};
gh_bad:
JUMP gh_bad;
'''


@lru_cache(None)
def assemble_decoder(base):
    if type(base) is not int or base < 0 or base % 2:
        raise ValueError('decoder base must be a nonnegative even PM address')
    return sasm.assemble(decoder_source(base), 'glasshouse_unpack.asm')


def decoder_instructions():
    return len(assemble_decoder(0x219000)[0][0].words)


def install(raw, decoder_pm):
    """Compress original EXT16 payloads, install decoder, and guard reset entry.

    Caller reserves the decoder's external ISA48 span. This routine independently
    rejects alias overlap with all existing loader records and the staging table.
    """
    if has_transport(raw):
        raise ValueError('Glasshouse boot transport is already installed')
    records, kernel, tail, reset = _raw_parts(raw)
    if reset != ORIGINAL_RESET or hashlib.sha256(tail).hexdigest() != ORIGINAL_FINAL_SHA256:
        raise ValueError('stock DSP FINAL_INIT/reset branch differs')
    native_end, heap4 = placement.require_native_reservation(records)
    if not heap4 <= SCRATCH < TABLE < STAGING_END < 0xed7000:
        raise ValueError('temporary transport is outside the native Heap4 reservation')
    originals = [r for r in records if r[0] == 10]
    if (tuple((r[2], r[1]) for r in originals) != ORIGINAL_EXTERNAL_RECORDS or
            hashlib.sha256(b''.join(struct.pack(f'<{len(r[3])}I', *r[3]) for r in originals)).hexdigest()
            != ORIGINAL_EXTERNAL_SHA256):
        raise ValueError('stock external DSP payload layout/fingerprint differs')
    _require_disjoint_external_owners(records, originals)
    body = []
    for tag, count, address, payload in originals:
        encoded = encode(payload)
        if decode(encoded, count) != list(payload):
            raise ValueError('LZ encoder roundtrip differs')
        body.extend((address, count, len(encoded), *encoded))
    sections, symbols = assemble_decoder(decoder_pm)
    section = sections[0]
    n = len(section.words) + len(section.words) % 2
    begin, end = decoder_pm*3//2, (decoder_pm+n)*3//2
    if decoder_pm < 0x200000 or end > heap4 or begin < native_end:
        raise ValueError('decoder is outside the permanent external code reservation')
    header = [MAGIC, VERSION, HEADER_WORDS+len(body)+1, len(originals), decoder_pm, n]
    table = [*header, *body, 0]
    if TABLE+len(table) > STAGING_END:
        raise ValueError('compressed DSP table exceeds temporary staging reservation')
    claimed = ((2*begin, 2*end), (2*SCRATCH, 2*STAGING_END))
    for record in records:
        span = placement.physical_span(record)
        if span and any(span[0] < hi and lo < span[1] for lo, hi in claimed):
            raise ValueError('decoder or temporary staging overlaps a boot record')
    out = list(kernel)
    for record in records:
        if record[0] != 10:
            out.extend(_flat_record(record))
    out.extend(placement.pack(placement.Placement(decoder_pm, n, begin, end), sections))
    out.extend((4, len(table), TABLE, *table))
    patched_tail = bytearray(tail)
    jump_sections, _ = sasm.assemble(f'.section pm {RESET_PM:#x}\nJUMP {decoder_pm:#x};', 'glasshouse_reset.asm')
    patched_tail[12+5*6:12+6*6] = jump_sections[0].words[0].to_bytes(6, 'little')
    packed = struct.pack(f'<{len(out)}I', *out)+bytes(patched_tail)
    if len(packed) >= len(raw):
        raise ValueError('Glasshouse boot transport does not recover storage')
    # The emitted table must independently recover exactly the original records.
    if table_records(packed) != originals:
        raise ValueError('emitted boot transport differs from original DSP data')
    return packed, dict(scheme='lz32-v1', spi_kernel_sha256=ORIGINAL_SPI_KERNEL_SHA256,
                        input_bytes=len(raw), output_bytes=len(packed),
                        saved_bytes=len(raw)-len(packed), stock_external_records=len(originals),
                        original_external_sha256=hashlib.sha256(b''.join(
                            struct.pack(f'<{len(r[3])}I', *r[3]) for r in originals)).hexdigest(),
                        table_begin=TABLE, table_words=len(table), scratch_begin=SCRATCH,
                        staging_end=STAGING_END, decoder_pm=decoder_pm,
                        decoder_instructions=n, decoder_data_begin=begin, decoder_data_end=end,
                        original_reset=ORIGINAL_RESET, original_entry=ORIGINAL_ENTRY,
                        original_final_init_sha256=hashlib.sha256(tail).hexdigest(),
                        hardware_boot_verified=False)


def verify_transport(raw):
    """Execute the emitted startup routine and prove its complete decode contract.

    No source-assembled instruction is injected into the machine. The candidate
    must contain the audited routine, then its own emitted words are executed.
    This proves the startup algorithm, memory writes and entry contract offline;
    it does not model physical SPI transfer latency or hardware instruction cache.
    """
    records, _, tail, reset = _raw_parts(raw)
    originals = table_records(raw)
    _require_disjoint_external_owners(records, originals)
    _, _, _, table = _table_record(raw)
    decoder_pm, count = table[4:6]
    if not 0x200000 <= decoder_pm < 0x600000:
        raise ValueError('Glasshouse decoder address differs')
    canonical, symbols = assemble_decoder(decoder_pm)
    words = canonical[0].words
    expected = list(words)+[0]*(count-len(words))
    if count != len(words)+len(words) % 2 or decoder_pm < 0x200000:
        raise ValueError('Glasshouse decoder size/address differs')
    begin, end = decoder_pm*3//2, (decoder_pm+count)*3//2
    heap6, heap4 = placement.require_native_reservation(records)
    if not heap6 <= begin < end <= heap4:
        raise ValueError('Glasshouse decoder reservation differs')
    expected_reset = 0x063e00000000 | decoder_pm
    restored = bytearray(tail)
    restored[12+5*6:12+6*6] = ORIGINAL_RESET.to_bytes(6, 'little')
    if reset != expected_reset or hashlib.sha256(restored).hexdigest() != ORIGINAL_FINAL_SHA256:
        raise ValueError('Glasshouse startup branch/FINAL_INIT differs')
    code_records = [r for r in records if r[0] == 4 and r[2] == begin and r[1] == end-begin]
    if len(code_records) != 1:
        raise ValueError('Glasshouse decoder boot record is missing or ambiguous')
    data = struct.pack(f'<{len(code_records[0][3])}I', *code_records[0][3])
    emitted = [int.from_bytes(data[6*i:6*i+6], 'little') for i in range(count)]
    if emitted != expected:
        raise ValueError('Glasshouse decoder instructions differ')
    owned = ((2*begin, 2*end), (2*SCRATCH, 2*STAGING_END))
    for r in records:
        if r == code_records[0] or r == _table_record(raw):
            continue
        span = placement.physical_span(r)
        if span and any(span[0] < hi and lo < span[1] for lo, hi in owned):
            raise ValueError('Glasshouse boot storage has an aliased writer')
    sim = ssim.Sim()
    sim.strict_cbufen = True
    sim.pm.update((decoder_pm+i, word) for i, word in enumerate(emitted))
    sim.dm.update((TABLE+i, value) for i, value in enumerate(table))
    # FINAL_INIT self-modifies instruction4 to PM(0,I8)=PX before it
    # reaches instruction5 (ADI Loader/Utilities2.9, pp158-160). Its upper
    # parcel shares this normal32 word; preserve that runtime0xb16b value.
    vector = tail[12:]
    vector_first = (int.from_bytes(vector[28:32], 'little') & 0xffff0000) | 0xb16b
    sim.wr(RESET_NORMAL, vector_first)
    sim.wr(RESET_NORMAL+1, int.from_bytes(vector[32:36], 'little'))
    for i in range(len(sim.u)):
        sim.u[i] = 0x100000+i
    sim.set(ssim.U_MODE1, ssim.CBUFEN | ssim.PEYEN | ssim.BDCST1 | ssim.BDCST9 | IRPTEN)
    sim.set(ssim.U_ASTATX, 0x12340001)
    saved = {name: sim.get(sasm.UREG_CODE[name]) for name in SAVED+('MODE1',)}
    destinations = [(r[2], r[2]+r[1]) for r in originals]
    writes = destinations+[(SCRATCH, SCRATCH+2+len(SAVED)), (RESET_NORMAL, RESET_NORMAL+2)]
    reads = writes+[(TABLE, TABLE+len(table))]
    rd, wr = sim.rd, sim.wr
    def checked_read(address):
        if not any(lo <= address < hi for lo, hi in reads):
            raise ValueError(f'Glasshouse startup read outside owned memory at {address:#x}')
        return rd(address)
    def checked_write(address, value):
        if any(lo <= address < hi for lo, hi in destinations) and sim.u[ssim.U_MODE1] & IRPTEN:
            raise ValueError('Glasshouse startup writes external code with interrupts enabled')
        if not any(lo <= address < hi for lo, hi in writes):
            raise ValueError(f'Glasshouse startup write outside owned memory at {address:#x}')
        wr(address, value)
    sim.rd, sim.wr = checked_read, checked_write
    sim.pc = decoder_pm
    # Bound all literal/match loops by the known original output word count.
    limit = 20*sum(r[1] for r in originals)+1000
    for _ in range(limit):
        if sim.pc == ORIGINAL_ENTRY:
            break
        if sim.pc == symbols['GH_BAD']:
            raise ValueError('Glasshouse startup decoder rejected its emitted table')
        if sim.pc not in sim.pm:
            raise ValueError('Glasshouse startup left its verified instruction span')
        sim.step()
    else:
        raise ValueError('Glasshouse startup exceeded its bounded instruction count')
    for _, n, address, payload in originals:
        if [rd(address+i) for i in range(n)] != list(payload):
            raise ValueError('Glasshouse startup reconstructed incorrect external DSP data')
    for name, value in saved.items():
        if sim.get(sasm.UREG_CODE[name]) != value:
            raise ValueError(f'Glasshouse startup changed register {name}')
    original_vector = bytes(restored)[12:]
    expected_vector = [(int.from_bytes(original_vector[28:32], 'little') & 0xffff0000) | 0xb16b,
                       int.from_bytes(original_vector[32:36], 'little')]
    if [rd(RESET_NORMAL+i) for i in range(2)] != expected_vector:
        raise ValueError('Glasshouse startup did not restore the original reset vector')
    return dict(scheme='lz32-v1', spi_kernel_sha256=ORIGINAL_SPI_KERNEL_SHA256,
                original_external_records=len(originals),
                decoded_words=sum(r[1] for r in originals), decoder_pm=decoder_pm,
                decoder_instructions=count, executed_instructions=sim.cycles,
                emitted_decoder_executed=True, decoded_memory_identical=True,
                startup_registers_preserved=True, reset_vector_restored=True,
                original_entry=ORIGINAL_ENTRY, hardware_boot_verified=False)
