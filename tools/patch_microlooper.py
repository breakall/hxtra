#!/usr/bin/env python3
"""Atmosphere metadata through the shared effect declaration compiler.

DSP placement and M4 input/lifecycle routing have separate build phases.
"""
from effect_model import register_model as register_effect
from microlooper_definition import EFFECT, MONO_EFFECT, MODELS

# Target-specific unused row, checked again before DSP linking.
REGISTRY_ADDRESS = 0x200058
REGISTRY_ADDRESSES = {EFFECT.name: REGISTRY_ADDRESS, MONO_EFFECT.name: 0x2000a0}
NAME, DISPLAY, PRESET_ID = EFFECT.name, EFFECT.display, EFFECT.preset_id
PRIM = (EFFECT.primitive, REGISTRY_ADDRESS)


def register_model(data, *, dsp_cost, log=print):
    return register_effect(data, EFFECT, dsp_cost=dsp_cost,
                           registry_address=REGISTRY_ADDRESS, log=log)


def register_models(data, *, dsp_costs, log=print):
    """Register both native widths with an explicit measured cost for each."""
    if set(dsp_costs) != {effect.name for effect in MODELS}:
        raise ValueError('Atmosphere DSP costs must name both mono and stereo models')
    # Validate the entire request before starting either registration.
    from effect_model import native_cost
    for cost in dsp_costs.values():
        native_cost(cost)
    results = []
    for effect in MODELS:
        data, result = register_effect(
            data, effect, dsp_cost=dsp_costs[effect.name],
            registry_address=REGISTRY_ADDRESSES[effect.name], log=log)
        results.append(result)
    return data, results
