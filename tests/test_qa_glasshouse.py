"""Glasshouse uses native Dynamics preset shapes, including hidden Enable."""
import pytest

import hx_ctl
from glasshouse_definition import MODELS


@pytest.mark.parametrize('effect', MODELS, ids=lambda effect: effect.name)
def test_glasshouse_native_preset_defaults_round_trip(effect, monkeypatch):
    monkeypatch.setattr(hx_ctl, 'find_kind_and_params', lambda *_: (None, None))
    sec = {7: {}, 0: {22: [{19: 8, 20: None} for _ in range(20)]},
           1: {}, 3: {}, 4: {}, 2: {}, 5: {}, 6: {}, 10: {}}
    hx_ctl.set_model(sec, 0, 0, effect.preset_id)
    _, restored = hx_ctl.decode_preset(hx_ctl.encode_preset('l6-helix', sec))
    body = hx_ctl.blocks(restored)[1][20]
    assert body[9] == 24  # Native Feedbacker policy keeps the self-bypassed DSP running.
    assert body[24] == {23: False, 25: effect.preset_id, 26: -1}
    values = body[11][4]
    assert body[11][2] == body[11][3] == len(effect.parameters)
    assert values[-1] is True
    for value, parameter in zip(values, effect.parameters):
        assert type(value) is {1: bool, 2: int, 3: float}[parameter.type]
        assert value == pytest.approx(parameter.default)
