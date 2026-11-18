"""Checked native Glasshouse metadata registration, separate from DSP loading."""
from effect_model import native_cost, register_model as register_effect, verify_model
from glasshouse_definition import EFFECT, MONO_EFFECT, MODELS

REGISTRY_ADDRESSES = {EFFECT.name: 0x200120, MONO_EFFECT.name: 0x2000b0}
# Unused rows checked on stock3.80.0 and the complete Atmosphere/NAM/click/GR
# candidate. A different owner or changed firmware must fail DSP installation.
UNUSED_REGISTRIES = {
    EFFECT.name: [0x2392, 6342091, 0, 6341871, 6341885, 578003, 5, 5],
    MONO_EFFECT.name: [0x0838, 6339649, 0, 0, 6339451, 577556, 8, 4],
}


def register_models(data, *, dsp_costs, log=print):
    """Register each native width with an explicitly selected admission charge."""
    if set(dsp_costs) != {effect.name for effect in MODELS}:
        raise ValueError('Glasshouse DSP costs must name both mono and stereo models')
    for cost in dsp_costs.values():
        native_cost(cost)
    results = []
    for effect in MODELS:
        data, result = register_effect(
            data, effect, dsp_cost=dsp_costs[effect.name],
            registry_address=REGISTRY_ADDRESSES[effect.name], log=log)
        results.append(result)
    return data, results


def verify_metadata(data):
    return {effect.name: verify_model(data, effect) for effect in MODELS}
