"""Glasshouse build admission is explicit and leaves the NAM profile unchanged."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('glasshouse_build', Path(__file__).parents[1] / 'build.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_feature_off_does_not_require_costs(monkeypatch):
    monkeypatch.delenv('HX_GLASSHOUSE', raising=False)
    assert build.glasshouse_cost('HX_Stomp') is None


def test_glasshouse_charges_are_explicit_and_preserve_nam(monkeypatch):
    monkeypatch.setenv('HX_GLASSHOUSE', '1')
    monkeypatch.delenv('HX_GLASSHOUSE_DSP_COST', raising=False)
    monkeypatch.delenv('HX_GLASSHOUSE_MONO_DSP_COST', raising=False)
    with pytest.raises(SystemExit, match='explicit integer'):
        build.glasshouse_cost('HX_Stomp')
    monkeypatch.setenv('HX_GLASSHOUSE_DSP_COST', '2000')
    assert build.glasshouse_cost('HX_Stomp') == build.glasshouse_cost('HX_Stomp', mono=True) == 2000
    monkeypatch.setenv('HX_GLASSHOUSE_MONO_DSP_COST', '1700')
    assert build.glasshouse_cost('HX_Stomp', mono=True) == 1700
    assert build.kernel('HX_Stomp', gr=True) == build.KERNEL['HX_Stomp'] + build.GR_SLOTS
    assert build.kernel('HX_Stomp', gr=False) == build.KERNEL['HX_Stomp']
    with pytest.raises(SystemExit, match='Stomp only'):
        build.glasshouse_cost('HX_Stomp_XL')


@pytest.mark.parametrize('cost', ['0', '7501', 'nan', '1.1', ''])
def test_invalid_glasshouse_charge_fails_before_build(monkeypatch, cost):
    monkeypatch.setenv('HX_GLASSHOUSE', '1')
    monkeypatch.setenv('HX_GLASSHOUSE_DSP_COST', cost)
    with pytest.raises(SystemExit, match='explicit integer'):
        build.glasshouse_cost('HX_Stomp')
