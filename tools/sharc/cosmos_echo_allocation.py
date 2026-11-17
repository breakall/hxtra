"""Replay native composite buffer construction from supplied parent arenas.

The header and four-word buffer declarations come from stock Cosmos Echo.
Pointers are relocated into explicit test storage. The parent arenas are the
constructor's supplied local copy; this probe does not emulate task boot or
pretend these addresses are physical runtime observations. The source image is
never modified; the native C caller's target is selected in the replay fixture.
"""
import hashlib

import microlooper_init as caller
import microlooper_visa as visa
import ssim

ENTRY, MEMBERS = 0x177e1a, 0x177f22
PARENT, HEADER, RECORDS, RESULT = 0xb4000, 0xb5000, 0xb5100, 0xb6000
STACK, FRAME = 0xc6d98, 0xc6e98
BASES = (0xb2000, 0xe1000, 0x400000, 0x500000, 0x510000,
         0x520000, 0x530000, 0x540000, 0x550000)
LENGTHS = (0x1000, 0x800, 0x80000, 0x1000, 0x1000,
           0x4000, 0x1000, 0x1000, 0x1000)


def _replay(e2, header, records, *, extension='sign-extend', capacities=None):
    """Run original constructor entry through buffers or its error epilogue.

    Both immediate-extension hypotheses are supported explicitly; success and
    allocation/write footprints must be compared rather than assuming one.
    Successful execution stops before member construction. Failure runs through
    the original return epilogue. Every failure is nonzero under both hypotheses.
    """
    if len(header) != 7 or len(records) != header[4]:
        raise ValueError('complete composite header/buffer declarations required')
    capacities = dict(capacities or {})
    sim, short = visa.load(e2, parcel_order='high-first', external_parcel_order='low-first')
    sim.strict_cbufen = True
    sim.u[ssim.U_MODE1] = ssim.CBUFEN | 0x10000
    for code, value in ((0x25, 0), (0x26, 1), (0x27, 0xffffffff),
                        (0x2d, 0), (0x2e, 1), (0x2f, 0xffffffff),
                        (0x37, 0), (0x16, FRAME), (0x17, STACK),
                        (4, RESULT), (8, HEADER), (12, 7)):
        sim.set(code, value)
    for pool, (base, length) in enumerate(zip(BASES, LENGTHS)):
        length = capacities.get(pool, length)
        if not isinstance(length, int) or length < 0:
            raise ValueError('arena capacities must be nonnegative integers')
        for j, value in enumerate((base, base+length, base)):
            sim.wr(PARENT+3*pool+j, value)
    sim.wr(STACK+1, PARENT)
    relocated = list(header)
    relocated[3], relocated[5] = 0xb5200, RECORDS
    for j, value in enumerate(relocated):
        sim.wr(HEADER+j, value)
    for i, record in enumerate(records):
        if len(record) != 4:
            raise ValueError('a graph buffer declaration has four words')
        for j, value in enumerate(record):
            sim.wr(RECORDS+4*i+j, value)
    guards = (PARENT-1, PARENT+27, RESULT-1, RESULT+16,
              BASES[0]-1, BASES[0]+capacities.get(0, LENGTHS[0]),
              BASES[2]-1, BASES[2]+capacities.get(2, LENGTHS[2]))
    for address in guards:
        sim.wr(address, 0xdeadbeef)
    read, write = sim.rd, sim.wr
    reads, writes, executed = [], [], []

    def rd(address):
        reads.append((sim.pc, address))
        return read(address)

    def wr(address, value):
        writes.append((sim.pc, address, value & ssim.M32))
        write(address, value)

    sim.rd, sim.wr = rd, wr
    pc = caller.CALLSITE
    instruction = visa.decode([short[pc+j] for j in range(3)])
    instruction = visa.Instruction(instruction.length,
                                   (instruction.isa & ~0xffffff) | ENTRY, instruction.form)
    sim.pc = pc
    visa.step(sim, instruction)
    for _ in range(4096):
        if sim.pc in (MEMBERS, caller.RETURN_SITE):
            break
        pc = sim.pc
        executed.append(pc)
        if pc in short:
            visa.step(sim, visa.decode([short[pc+j] for j in range(3)],
                                      immediate16_extension=extension))
        elif pc in sim.pm:
            sim.step()
        else:
            raise visa.UnsupportedVisa(f'code absent at {pc:#x}')
    else:
        raise ValueError('native buffer constructor exceeded bound')
    okay = sim.pc == MEMBERS
    bindings = []
    if okay:
        table = read(RESULT+5)
        for j in range(len(records)):
            at = table+6*j
            bindings.append(dict(address=at, cursor=read(at), dm_words=read(at+1),
                                 pm_base=read(at+2), pm_words=read(at+3),
                                 ring_base=read(at+4), ring_words=read(at+5)))
    report = dict(entry2_sha256=hashlib.sha256(e2).hexdigest(),
                synthetic_context=True, immediate16_extension_assumed=extension,
                complete_buffer_prefix=okay, complete_member_graph_executed=False,
                stop_address=sim.pc, return_word=None if okay else sim.get(0),
                bindings=bindings, executed_addresses=executed,
                parent_currents=[read(PARENT+3*j+2) for j in range(9)],
                result_metadata=[read(RESULT+j) for j in range(12)],
                ring_write_count=sum(BASES[2] <= address < BASES[2]+LENGTHS[2]
                                     for _, address, _ in writes),
                guards_intact=all(read(address) == 0xdeadbeef for address in guards),
                declaration_length_reads=[(pc, address) for pc, address in reads
                                          if address in {RECORDS+4*j+3 for j in range(len(records))}],
                writes=writes)
    sim.rd, sim.wr = read, write
    return report, sim, short


def replay(e2, header, records, **context):
    """Return derived allocation facts; native machine state stays private."""
    return _replay(e2, header, records, **context)[0]


def inspect(e2, header, records):
    """Check exact fits and independent cursor/ring/metadata exhaustion."""
    requirements = {0: sum(record[1] for record in records),
                    1: sum(record[2] for record in records),
                    2: sum(record[3] for record in records)}
    results = []
    for extension in ('sign-extend', 'zero-extend'):
        success = replay(e2, header, records, extension=extension, capacities=requirements)
        assert success['complete_buffer_prefix'] and success['guards_intact']
        assert len(success['bindings']) == len(records)
        assert success['ring_write_count'] == 0
        dm_offset = sdr_offset = 0
        for binding, record in zip(success['bindings'], records):
            assert binding['cursor'] == BASES[0]+dm_offset
            assert binding['ring_base'] == BASES[2]+sdr_offset
            assert binding['dm_words'] == record[1] and binding['ring_words'] == record[3]
            dm_offset += record[1]
            sdr_offset += record[3]
        results.append(dict(case='exact_fit', **success))
        if extension == 'zero-extend':
            continue
        for pool in (0, 2, 6):
            capacity = (requirements[pool] if pool in requirements else 6*len(records))-1
            sizes = requirements.copy()
            sizes[pool] = capacity
            failure = replay(e2, header, records, extension=extension, capacities=sizes)
            assert not failure['complete_buffer_prefix'] and failure['return_word'] != 0
            assert failure['guards_intact'] and failure['ring_write_count'] == 0
            results.append(dict(case=f'exhaust_pool_{pool}', **failure))
    assert results[0]['bindings'] == results[-1]['bindings']
    assert results[0]['parent_currents'] == results[-1]['parent_currents']
    return dict(cases=results, graph_buffer_record_fields_verified=True,
                successful_allocation_identical_under_both_extensions=True,
                error_propagation_requires_signed_immediate_hypothesis=True,
                initialization_zeroes_ring=False, hardware_verified=False)
