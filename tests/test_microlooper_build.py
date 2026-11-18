"""Atmosphere build selection preserves the existing NAM and device profiles."""
import importlib.util
from pathlib import Path

import pytest

import microlooper as layout
import hxf_ram

spec = importlib.util.spec_from_file_location('hxtra_build', Path(__file__).parents[1] / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_boot_stream_guard_excludes_the_partition_subheader():
    room = (hxf_ram.PART_END[2] - hxf_ram.PAYLOAD[2]) * hxf_ram.SECTOR
    assert layout.ENTRY2_INJECTION_LIMIT == room == 0x80000


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


@pytest.mark.parametrize('cost', ['', '0', '7501', '1.5'])
def test_cost_requires_an_explicit_valid_integer(monkeypatch, cost):
    monkeypatch.setenv('HX_MICRO_LOOPER', '1')
    monkeypatch.setenv('HX_MICRO_LOOPER_DSP_COST', cost)
    with pytest.raises(SystemExit, match='explicit integer'):
        build.microlooper_cost('HX_Stomp')


def test_mono_cost_can_use_shared_charge_or_separate_measurement(monkeypatch):
    monkeypatch.setenv('HX_MICRO_LOOPER', '1')
    monkeypatch.setenv('HX_MICRO_LOOPER_DSP_COST', '2000')
    monkeypatch.delenv('HX_MICRO_LOOPER_MONO_DSP_COST', raising=False)
    assert build.microlooper_cost('HX_Stomp', mono=True) == 2000
    monkeypatch.setenv('HX_MICRO_LOOPER_MONO_DSP_COST', '1600')
    assert build.microlooper_cost('HX_Stomp', mono=True) == 1600
    monkeypatch.setenv('HX_MICRO_LOOPER_MONO_DSP_COST', '0')
    with pytest.raises(SystemExit, match='HX_MICRO_LOOPER_MONO_DSP_COST'):
        build.microlooper_cost('HX_Stomp', mono=True)
