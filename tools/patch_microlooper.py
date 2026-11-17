#!/usr/bin/env python3
"""Atmosphere metadata through the shared effect declaration compiler.

DSP placement and M4 input/lifecycle routing have separate build phases.
"""
from effect_model import register_model as register_effect
from microlooper_definition import EFFECT

# Target-specific unused row, checked again before DSP linking.
REGISTRY_ADDRESS = 0x200058
NAME, DISPLAY, PRESET_ID = EFFECT.name, EFFECT.display, EFFECT.preset_id
PRIM = (EFFECT.primitive, REGISTRY_ADDRESS)


def register_model(data, *, dsp_cost, log=print):
    return register_effect(data, EFFECT, dsp_cost=dsp_cost,
                           registry_address=REGISTRY_ADDRESS, log=log)
