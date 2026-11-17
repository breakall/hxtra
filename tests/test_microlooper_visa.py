"""Conditional offline decoding, never hardware stereo ABI certification."""
import os

import pytest

import microlooper_adapter as adapter
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


@pytest.mark.firmware
@pytest.mark.parametrize('count,outer,offset', [(2, 16, 0), (2, 16, 7), (16, 2, 0)])
def test_actual_first_input_loop_is_conditional_on_order_and_explicit_fields(count, outer, offset):
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    image, _ = adapter.kit.load_l6ia_from_any(stock)
    entry = adapter.kit.l6ia.parse(image)[2]
    raw = image[entry['payload_off']:entry['payload_off'] + entry['payload_len']]
    fields = {0: count, 2: outer, 12: offset, 122: 0xbd000}
    report = visa.inspect_first_input_loop(raw, parcel_order='high-first', private_fields=fields)
    assert report['first_input_loop_complete'], report['stop_reason']
    assert report['stop_address'] == 0x13ae70
    assert report['input_offsets'] == list(range(count))
    assert report['copy_index_r13'] == 0
    assert report['input_stride'] == 1
    assert report['private_fields_assumed'] == fields
    assert report['init16_parcel_order_assumed'] == 'high-first'
    assert not report['constructor_executed']
    assert not report['outer_loop_verified'] and not report['output_loop_verified']
    assert not report['native_stereo_abi_verified']
    geometry = visa.inspect_buffer_geometry(raw, parcel_order='high-first')
    assert all(geometry['decoded_checks'].values())
    assert geometry['row_width_field'] == 0 and geometry['row_count_field'] == 2
    assert not geometry['field_meanings_verified'] and not geometry['input_words_proven_float']
    with pytest.raises(visa.UnsupportedVisa):
        visa.inspect_buffer_geometry(raw, parcel_order='low-first')


@pytest.mark.firmware
@pytest.mark.parametrize('init_r12', [8, 16, 32])
def test_original_initializer_sets_fixed_sixteen_word_rows_independent_of_arguments(init_r12):
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    image, _ = adapter.kit.load_l6ia_from_any(stock)
    entry = adapter.kit.l6ia.parse(image)[2]
    raw = image[entry['payload_off']:entry['payload_off'] + entry['payload_len']]
    report = visa.inspect_initializer_fields(raw, parcel_order='high-first',
                                            external_parcel_order='low-first',
                                            init_r12=init_r12, init_r8=0x44556677)
    assert report['initializer_prefix_complete'], report['stop_reason']
    assert report['private_prefix'] == [16, 0x39aec33e, 2]
    assert [(event['pc'], event['field']) for event in report['nonzero_prefix_writes']] == [
        (0x6010ef, 0), (0x6010f3, 1), (0x601113, 2)]
    assert not report['native_init_caller_verified']
    assert not report['native_stereo_abi_verified']
    _, short = visa.load(raw, parcel_order='high-first', external_parcel_order='low-first')
    literal = visa.decode([short[0x615279 + j] for j in range(3)])
    assert literal.isa == isa('I12 = 16;')
    literal = visa.decode([short[0x6152a6 + j] for j in range(3)])
    assert literal.isa == isa('I14 = 2;')


def test_reader_requires_explicit_order_and_state_fields():
    with pytest.raises(ValueError, match='select'):
        visa.load(bytes(384 * 4 + 12), parcel_order='native')
    with pytest.raises(ValueError, match='fields'):
        visa.inspect_first_input_loop(b'', parcel_order='high-first', private_fields={})


@pytest.mark.firmware
@pytest.mark.parametrize('sample,coefficient', [(.25, .75), (-.5, -1.25), (1., .001), (.00001, 8192.)])
def test_copied_input_word_is_a_float_operand_under_both_extension_hypotheses(
        sample, coefficient, monkeypatch):
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    image, _ = adapter.kit.load_l6ia_from_any(stock)
    entry = adapter.kit.l6ia.parse(image)[2]
    raw = image[entry['payload_off']:entry['payload_off'] + entry['payload_len']]
    sample_word, coefficient_word = ssim.f2b(sample), ssim.f2b(coefficient)
    # Independently reject using either raw float value as a memory pointer.
    read = ssim.Sim.rd
    def reject_float_as_pointer(sim, address):
        assert address not in (sample_word, coefficient_word)
        return read(sim, address)
    monkeypatch.setattr(ssim.Sim, 'rd', reject_float_as_pointer)
    words = [sample_word] + [0x3e800000 + j for j in range(1, 32)]
    report = visa.inspect_input_word_float_use(raw, parcel_order='high-first', input_words=words,
                                             coefficient_word=coefficient_word)
    assert report['copied_word_float_use_invariant']
    assert not report['negative_immediate16_extension_resolved']
    assert not report['native_stereo_abi_verified']
    use = report['conditional_float_use']
    assert (use['input_read_pc'], use['staging_write_pc'], use['staging_read_pc'], use['compute_pc']) == (
        0x13ae6a, 0x13ae6d, 0x1828a9, 0x1828ab)
    assert use['input_address'] == 0xb8000 and use['staging_address'] == 0xbd000
    assert use['word'] == sample_word and use['coefficient_word'] == coefficient_word
    assert use['sample_register'] == 4 and use['coefficient_register'] == 2
    assert use['result_word'] == ssim.f2b(ssim.b2f(sample_word) * ssim.b2f(coefficient_word))
    assert [run['negative_immediate16_sites'] for run in report['runs']] == [
        [{'pc': 0x1828a0, 'register': sasm.UREG_CODE['M13'], 'value': 0xfffffffc}],
        [{'pc': 0x1828a0, 'register': sasm.UREG_CODE['M13'], 'value': 0x0000fffc}]]
    assert all(run['stop_address'] == 0x1828ae and run['steps'] == 207 for run in report['runs'])
    assert all(not run['input_word_as_address_reads'] for run in report['runs'])
    _, short = visa.load(raw, parcel_order='high-first')
    multiply = visa.decode([short[0x1828ab + j] for j in range(3)])
    assert multiply.isa & 0x7fffff == isa('F12 = F2 * F4;') & 0x7fffff
    bounded = visa.inspect_input_word_float_use(raw, parcel_order='high-first', input_words=words,
                                              coefficient_word=coefficient_word, limit=100)
    assert not bounded['copied_word_float_use_invariant']


@pytest.mark.firmware
def test_continuation_keeps_default_negative_immediate_hard_stop():
    stock = os.environ.get('HX_STOMP_HXF')
    if not stock:
        pytest.skip('HX_STOMP_HXF is not set')
    image, _ = adapter.kit.load_l6ia_from_any(stock)
    entry = adapter.kit.l6ia.parse(image)[2]
    raw = image[entry['payload_off']:entry['payload_off'] + entry['payload_len']]
    report = visa.inspect_first_input_loop(raw, parcel_order='high-first',
        private_fields={0: 16, 2: 2, 12: 0, 122: 0xbd000, 124: 0xbd100}, stop_after_input_loop=False)
    assert report['stop_address'] == 0x1828a0
    assert 'negative immediate16' in report['stop_reason']
    assert report['conditional_float_use'] is None
