"""Native preset shapes after adding Atmosphere Mono."""
import pytest

import hx_ctl
from microlooper_definition import MODELS


def empty_sections():
    return {7: {}, 0: {22: [{19: 8, 20: None} for _ in range(20)]},
            1: {}, 3: {}, 4: {}, 2: {}, 5: {}, 6: {}, 10: {}}


@pytest.mark.parametrize('model', [effect.preset_id for effect in MODELS])
def test_atmosphere_defaults_round_trip_as_native_delay_with_eight_direct_controls(monkeypatch, model):
    # New effects are absent from the factory presets. The helper must know
    # their shape without deriving it from an unrelated stock delay's knobs.
    monkeypatch.setattr(hx_ctl, 'find_kind_and_params', lambda *_: (None, None))
    sec = empty_sections()
    hx_ctl.set_model(sec, 0, 0, model)
    _, restored = hx_ctl.decode_preset(hx_ctl.encode_preset('l6-helix', sec))
    block = hx_ctl.blocks(restored)[1][20]
    assert block[24] == {23: False, 25: model, 26: -1}
    assert block[9] == 8 and block[10] is True
    assert block[11][2] == 9 and block[11][3] == 8
    assert block[11][4] == [1, .5, .75, 1., .5, False, False, False, False]
    assert [type(value) for value in block[11][4]] == [int, float, float, float, float, bool, bool, bool, bool]


@pytest.mark.parametrize('model', [effect.preset_id for effect in MODELS])
def test_atmosphere_explicit_native_values_are_preserved(monkeypatch, model):
    monkeypatch.setattr(hx_ctl, 'find_kind_and_params', lambda *_: (None, None))
    values = [2, .2, .3, .4, .6, True, False, False, False]
    sec = empty_sections()
    hx_ctl.set_model(sec, 0, 0, model, params=values)
    block = hx_ctl.blocks(sec)[1][20]
    assert block[9] == 8
    assert block[11] == {2: 9, 3: 8, 4: values}



def test_atmosphere_does_not_reuse_the_legacy_nam_model_identity():
    assert {effect.preset_id for effect in MODELS} == {380, 381}
    assert hx_ctl.KNOWN_KIND[147] == 17
    assert 147 not in hx_ctl.KNOWN_PARAMS
