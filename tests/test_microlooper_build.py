"""Experimental memory profiles preserve defaults and fit the actual audio code."""
import importlib.util
from pathlib import Path

import pytest

import microlooper as layout
import microlooper_audio as audio
import hxf_ram

spec = importlib.util.spec_from_file_location('hxtra_build', Path(__file__).parents[1] / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_default_nam_selection_is_unchanged(monkeypatch):
    monkeypatch.delenv('HX_MICRO_LOOPER', raising=False)
    assert build.kernel('HX_Stomp', gr=False) == build.KERNEL['HX_Stomp']
    assert build.kernel('HX_Stomp', gr=True) == build.KERNEL['HX_Stomp'] + ['--slots', '2']


def test_independent_environment_override_cannot_create_unchecked_nam1_build(monkeypatch):
    monkeypatch.delenv('HX_MICRO_LOOPER', raising=False)
    monkeypatch.setenv('HX_NAM_SLOTS', '1')  # Former unsafe documented build command.
    assert build.kernel('HX_Stomp', gr=False) == build.KERNEL['HX_Stomp']
    assert build.kernel('HX_Stomp', gr=True) == build.KERNEL['HX_Stomp'] + build.GR_SLOTS


def test_actual_full_audio_kernel_fits_with_gr_and_metronome():
    profile = layout.profile(1, metronome=True, gr=True)
    sections, _ = audio.assemble(0xe0000)
    count = sum(len(s.words) for s in sections if s.kind == 'pm')
    base = profile.place(count)
    placed, _ = audio.assemble(base)
    assert count > 1000, 'must check the full audio engine, not a diagnostic stub'
    assert layout.normal_word(base) >= profile.block3_begin
    assert max(s.addr + len(s.words) for s in placed if s.kind == 'pm') <= profile.block3_end_pm
    with pytest.raises(ValueError, match='does not fit'):
        layout.profile(2, metronome=True, gr=True).place(count)


def test_boot_stream_guard_excludes_the_partition_subheader():
    room = (hxf_ram.PART_END[2] - hxf_ram.PAYLOAD[2]) * hxf_ram.SECTOR
    assert layout.ENTRY2_INJECTION_LIMIT == room == 0x80000


def test_audio_and_bridge_account_for_both_odd_section_padding_and_headers():
    import microlooper_bridge as bridge
    import kit_patch_amp as kit
    counts = [audio.instructions(), bridge.instructions()]
    encoded = sum(count + count % 2 for count in counts)
    profile = layout.profile(1, metronome=True, gr=True)
    base = profile.place(encoded)
    core, symbols = audio.assemble(base)
    shim, _ = bridge.assemble(base + counts[0] + counts[0] % 2, symbols[audio.ENTRY])
    sections = [s for s in core + shim if s.kind == 'pm']
    assert len(sections) == 2
    assert sections[1].addr == sections[0].addr + counts[0] + counts[0] % 2
    assert sections[1].addr + counts[1] + counts[1] % 2 <= profile.block3_end_pm
    growth = sum(4 * len(kit.pack_init_l48(s.addr, s.words)) for s in sections)
    report = layout.image_budget(516804, sum(counts), section_instructions=counts)
    assert report['code_ldr_growth_bytes'] == growth
    assert report['encoded_instructions'] == encoded
    assert bridge.STATE_WORDS <= kit.FX_BUDGET[2]['dm']
    assert report['remaining_bytes'] - 44 >= 0, 'include the complete primitive registry record'


def test_micro_support_preserves_baseline_nam_and_requires_explicit_cost(monkeypatch):
    monkeypatch.setenv('HX_MICRO_LOOPER', '1')
    monkeypatch.delenv('HX_MICRO_LOOPER_DSP_COST', raising=False)
    assert build.kernel('HX_Stomp', gr=True) == build.KERNEL['HX_Stomp'] + build.GR_SLOTS
    assert build.kernel('HX_Stomp', gr=False) == build.KERNEL['HX_Stomp']
    with pytest.raises(SystemExit, match='explicit integer'):
        build.microlooper_cost('HX_Stomp')
    monkeypatch.setenv('HX_MICRO_LOOPER_DSP_COST', '1000')
    assert build.microlooper_cost('HX_Stomp') == 1000
    with pytest.raises(SystemExit, match='Stomp only'):
        build.microlooper_cost('HX_Stomp_XL')


@pytest.mark.parametrize('cost', ['', '0', '-1', '7501', '1.5', 'unmeasured'])
def test_experimental_cost_has_no_invented_default(monkeypatch, cost):
    monkeypatch.setenv('HX_MICRO_LOOPER', '1')
    monkeypatch.setenv('HX_MICRO_LOOPER_DSP_COST', cost)
    with pytest.raises(SystemExit, match='explicit integer'):
        build.microlooper_cost('HX_Stomp')


@pytest.mark.parametrize('unit', ['HX_Stomp_XL', 'HX_Effects'])
def test_microlooper_profile_does_not_change_other_devices(monkeypatch, unit):
    monkeypatch.setenv('HX_MICRO_LOOPER', '1')
    assert build.kernel(unit, gr=True) == build.KERNEL[unit]


@pytest.mark.parametrize('counts', [[], [0], [1], [2, -1]])
def test_image_budget_rejects_inconsistent_section_counts(counts):
    with pytest.raises(ValueError, match='section instruction counts'):
        layout.image_budget(0, 2, section_instructions=counts)
