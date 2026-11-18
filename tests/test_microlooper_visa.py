"""Native instruction decoding and execution used by allocation checks."""
import pytest

import microlooper_visa as visa
import sasm
import ssim


def isa(source):
    sections, _ = sasm.assemble('.section pm 0x170000;\n' + source)
    return sections[0].words[0]


def parcels(word):
    return [word >> shift & 0xffff for shift in (32, 16, 0)]


def test_documented_pass_and_move_without_compute_forms():
    decoded = visa.decode([0xc000 | (2 << 8) | (5 << 4) | 4])
    assert decoded.length == 1
    assert decoded.isa == isa('R5 = PASS R4;')
    original = isa('R4 = I1;')
    decoded = visa.decode(parcels(original | 0x3f0000)[:2])
    assert decoded.length == 2 and decoded.isa == original
    assert visa.decode([0xc000 | (15 << 8) | (2 << 4) | 13]).isa == isa('F2 = F2 * F13;')


def test_documented_offset7_and_postmodify_forms():
    p = 0x9000 | (4 << 9) | (1 << 8) | 8
    q = (2 << 7) | ((-7) & 127)
    decoded = visa.decode([p, q])
    assert decoded.length == 2
    assert decoded.isa == isa('DM(-7,I4) = R2;')
    p = 0x9000 | (1 << 9) | (6 << 6) | 0x10 | 3
    decoded = visa.decode([p])
    assert decoded.length == 1
    assert decoded.isa == isa('R3 = DM(I1,M6);')


@pytest.mark.parametrize('index', range(8, 16))
@pytest.mark.parametrize('store', [False, True])
def test_offset7_dag2_selector_matches_traditional_form_and_uses_dag2(index, store):
    p = 0x9028 | ((index - 8) << 9) | (store << 8)
    decoded = visa.decode([p, (sasm.UREG_CODE['I0'] << 7) | 121])
    source = f'PM(-7,I{index}) = I0;' if store else f'I0 = PM(-7,I{index});'
    assert decoded.isa == isa(source)
    assert decoded.form == '15b:PM-offset7'
    sim = ssim.Sim()
    sim.pc = 0x170000
    sim.set(0x10 + index, 0xb8007)
    sim.set(0x10 + index - 8, 0xb9007)
    sim.wr(0xb8000, 0x12345678)
    if store:
        sim.set(0x10, 0x87654321)
    visa.step(sim, decoded)
    assert sim.rd(0xb9000) == 0
    assert (sim.rd(0xb8000) if store else sim.get(0x10)) == (0x87654321 if store else 0x12345678)


def test_offset7_rejects_nonzero_unresolved_l_and_reserved_fields():
    for p, q in [(0x9048, 0), (0x9088, 0), (0x9029, 0), (0x9028, 0x4000)]:
        with pytest.raises(visa.UnsupportedVisa):
            visa.decode([p, q])


def test_unknown_compact_forms_and_truncated_inputs_stop():
    for raw in ([], [0x3020, 0x003f, 0], [0xc704],
                [0x1804], [0x1804, 0], [0x0f82, 0x8000], [0x9fc4, 0xffff]):
        with pytest.raises(visa.UnsupportedVisa):
            visa.decode(raw)


def test_compact_dual_load_matches_independently_assembled_memory_moves():
    original = isa('R4 = DM(I4,M6), R2 = PM(I13,M14);')
    decoded = visa.decode(parcels(original | 0x3f0000)[:2])
    assert decoded.length == 2 and decoded.form == '1b:dual-load'
    assert decoded.isa == original


@pytest.mark.parametrize('hypothesis,value', [('sign-extend', -4), ('zero-extend', 65532)])
def test_negative_immediate_extension_requires_an_explicit_hypothesis(hypothesis, value):
    encoded = [0x0f80 | sasm.UREG_CODE['M13'], 0xfffc]
    with pytest.raises(visa.UnsupportedVisa, match='not established'):
        visa.decode(encoded)
    decoded = visa.decode(encoded, immediate16_extension=hypothesis)
    assert decoded.isa == isa(f'M13 = {value};')
    assert decoded.form == '17b:assumed-' + hypothesis
    with pytest.raises(ValueError, match='hypothesis'):
        visa.decode(encoded, immediate16_extension='native')


def test_known_modify_with_compute_and_memory_immediate_match_own_assembly():
    original = isa('MODIFY(I7,M7), R12 = PASS R5;')
    decoded = visa.decode(parcels(original))
    assert decoded.length == 3 and decoded.isa == original
    p = 0x9000 | (7 << 9) | (7 << 6) | 4
    decoded = visa.decode([p, 3])
    assert decoded.length == 2 and decoded.isa == isa('DM(I7,M7) = 3;')
    original = isa('JUMP (M14,I12) (DB);')
    decoded = visa.decode(parcels(original | 0x3f0000)[:2])
    assert decoded.length == 2 and decoded.isa == original


@pytest.mark.parametrize('hypothesis', ['sign-extend', 'zero-extend'])
@pytest.mark.parametrize('dag2', [False, True])
@pytest.mark.parametrize('literal', [0x8000, 0xffff])
def test_memory_immediate16_requires_hypothesis_and_writes_selected_dag(hypothesis, dag2, literal):
    # ADI Programming Reference rev2.4 Type16b, with extension deliberately
    # explicit. Compare with independently assembled traditional Type16a.
    first = 0x9004 | (5 << 9) | (6 << 6) | (int(dag2) << 5)
    with pytest.raises(visa.UnsupportedVisa, match='not established'):
        visa.decode([first, literal])
    decoded = visa.decode([first, literal], immediate16_extension=hypothesis)
    value = ssim.sx(literal, 16) if hypothesis == 'sign-extend' else literal
    index, modifier = 5 + 8 * dag2, 6 + 8 * dag2
    memory = 'PM' if dag2 else 'DM'
    assert decoded.isa == isa(f'{memory}(I{index},M{modifier}) = {value};')
    sim = ssim.Sim()
    sim.pc = 0x170000
    sim.set(0x10 + index, 0xb8000)
    sim.set(0x20 + modifier, 1)
    visa.step(sim, decoded)
    assert sim.rd(0xb8000) == value & ssim.M32
    assert sim.get(0x10 + index) == 0xb8001
    assert sim.pc == 0x170002


@pytest.mark.parametrize('source', ['MODIFY(I7,M7);', 'I4 = MODIFY(I1,M5);',
                                  'I12 = MODIFY(I9,M13);'])
def test_documented_compact_modify_matches_own_assembly(source):
    original = isa(source)
    decoded = visa.decode(parcels(original | 0x3f0000)[:2])
    assert decoded.length == 2
    assert decoded.form == '7b:modify-without-compute'
    assert decoded.isa == original


def test_cjump_delays_count_instructions_with_mixed_short_word_lengths():
    sim = ssim.Sim()
    sim.pc = 0x170000
    sim.set(4, 23)
    sim.set(0x16, 0xc1000)
    sim.set(0x17, 0xc2000)
    jump = visa.decode(parcels(isa('CJUMP 0x170100 (DB);')))
    visa.step(sim, jump)
    assert sim.pc == 0x170003
    assert sim.get(2) == 0xc1000 and sim.get(0x16) == 0xc2000
    visa.step(sim, visa.decode([0xc000 | (2 << 8) | (3 << 4) | 4]))
    assert sim.pc == 0x170004
    visa.step(sim, visa.decode([0x0f80 | 5, 31]))
    assert sim.pc == 0x170100
    assert sim.get(3) == 23 and sim.get(5) == 31


@pytest.mark.parametrize('compact', [False, True])
def test_taken_delayed_jump_still_advances_over_its_full_instruction(compact):
    sim = ssim.Sim()
    sim.pc = 0x170000
    if compact:
        sim.set(0x1c, 0x1700ff)
        sim.set(0x2e, 1)
        word = isa('JUMP (M14,I12) (DB);')
        instruction = visa.decode(parcels(word | 0x3f0000)[:2])
    else:
        instruction = visa.decode(parcels(isa('JUMP 0x170100 (DB);')))
    visa.step(sim, instruction)
    assert sim.pc == 0x170000 + instruction.length
    visa.step(sim, visa.decode([1]))
    visa.step(sim, visa.decode([0x0f85, 31]))
    assert sim.pc == 0x170100 and sim.get(5) == 31


def test_do_uses_next_instruction_short_word_address_and_repeats_mixed_width_body():
    sim = ssim.Sim()
    sim.pc = 0x170000
    sim.set(3, 3)
    sim.set(0x10, 0xb8000)
    sim.set(0x14, 0xb9000)
    sim.set(0x26, 1)
    for j in range(3):
        sim.wr(0xb8000 + j, 100 + j)
    loop = visa.decode(parcels(isa('LCNTR = R3, DO 0x170004 UNTIL LCE;')))
    load = visa.decode([0x9000 | (6 << 6) | 0x10 | 2])
    store = visa.decode([0x9000 | (4 << 9) | (1 << 8) | 8, 2 << 7])
    visa.step(sim, loop)
    assert sim.pc == 0x170003 and sim.loops[-1][:2] == [0x170003, 0x170004]
    for j in range(3):
        visa.step(sim, load)
        assert sim.pc == 0x170004
        visa.step(sim, store)
        assert sim.rd(0xb9000) == 100 + j
    assert sim.pc == 0x170006 and not sim.loops




def test_reader_requires_explicit_parcel_order():
    with pytest.raises(ValueError, match='explicitly'):
        visa.load(b'', parcel_order='unknown')
    with pytest.raises(ValueError, match='external VISA'):
        visa.load(b'', parcel_order='high-first', external_parcel_order='unknown')
