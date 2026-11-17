"""Production hot-code placement consumes proven gaps without changing audio."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sharc import microlooper as layout
from sharc import microlooper_audio as audio
from sharc import microlooper_split as split
from sharc import nam_multi


def baseline(slots):
    return nam_multi.layout(['--mid-sweep', '--slots', str(slots)])


@pytest.mark.parametrize('slots,region', [(2, 'sample-loop'), (3, 'read-helpers')])
def test_largest_supported_region_fits_and_retains_all_core_instructions(slots, region):
    lay = baseline(slots)
    plan = split.plan(lay, [])
    cold, hot, symbols = plan.assemble(0x21889a)
    original, original_symbols = audio.assemble(0x21889a)
    assert plan.region == region
    assert symbols[audio.ENTRY] == cold.addr
    assert cold.addr <= symbols['ML_RETURN'] < cold.addr+len(cold.words)
    assert symbols['ML_WRAP'] >= hot.addr
    assert len(cold.words)+len(hot.words) == len(original[0].words)+(region == 'sample-loop')
    start = 'ML_SAMPLE' if region == 'sample-loop' else 'ML_WRAP'
    assert len(hot.words) == original_symbols['ML_RETURN']-original_symbols[start]
    gap = layout.profile(slots, True, slots == 2)
    assert gap.block3_begin <= layout.normal_word(hot.addr)
    assert hot.addr+len(hot.words)+len(hot.words) % 2 <= gap.block3_end_pm
    assert plan.external_instructions == len(cold.words)
    assert plan.internal_instructions == len(hot.words)


@pytest.mark.parametrize('tag', [1, 2, 3, 4, 5])
def test_all_internal_boot_address_spaces_refuse_an_existing_occupant(tag):
    lay = baseline(2)
    plan = split.plan(lay, [])
    address = (plan.internal_pm if tag in (2, 5)
               else layout.normal_word(plan.internal_pm)*(2 if tag == 3 else 1))
    with pytest.raises(ValueError, match='overlaps boot record'):
        split.plan(lay, [(tag, 2, address, ())])


def test_runtime_claim_collision_is_rejected_before_packing():
    lay = baseline(2)
    plan = split.plan(lay, [])
    begin = layout.normal_word(plan.internal_pm)
    changed = SimpleNamespace(slots=2, claims=lambda: lay.claims()+[(begin, begin+1)])
    with pytest.raises(ValueError, match='NAM runtime storage'):
        split.plan(changed, [])


def test_source_size_is_measured_again_after_kernel_changes(tmp_path, monkeypatch):
    original = split.plan(baseline(3), [])
    path = tmp_path/'kernel.asm'
    path.write_text(audio.ASM.read_text().replace('ml_return:\n', 'NOP;\nml_return:\n'))
    monkeypatch.setattr(audio, 'ASM', path)
    changed = split.plan(baseline(3), [])
    assert changed.internal_instructions == original.internal_instructions+1
    assert changed.external_instructions == original.external_instructions


def test_source_labels_cannot_silently_change_the_split_boundary(tmp_path, monkeypatch):
    path = tmp_path/'kernel.asm'
    path.write_text(audio.ASM.read_text().replace('ml_sample:\n', 'ml_sample_changed:\n')
                    .replace('JUMP ml_sample;', 'JUMP ml_sample_changed;'))
    monkeypatch.setattr(audio, 'ASM', path)
    with pytest.raises(ValueError, match='requires one ml_sample'):
        split.plan(baseline(2), [])


def test_unknown_nam_profile_is_not_a_new_capacity_policy():
    with pytest.raises(ValueError, match='unchanged NAM2 or NAM3'):
        split.plan(SimpleNamespace(slots=1), [])


def test_missing_internal_room_refuses_instead_of_borrowing_other_memory(monkeypatch):
    profile = layout.profile(3, True, False)
    monkeypatch.setattr(split.layout, 'profile', lambda *a, **k:
                        replace(profile, block3_begin=layout.normal_word(profile.block3_end_pm)))
    with pytest.raises(ValueError, match='does not fit'):
        split.plan(baseline(3), [])
