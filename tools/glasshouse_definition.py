"""Glasshouse model identities and native controls for the v0.3.2 engine.

PIDs are private DM offsets:16+source index. The independent source's 24 knobs
and12 toggles retain row-major indices, then Aux36/Sag37/Enable38. The source
pedal's controller-only latch knob17 is deliberately absent from native UI.
Aux is a native level: live low-to-high writes, including snapshots, start the
source manual dip. First audio initialization suppresses a restored high edge.
"""
from dataclasses import replace

from effect_model import Callbacks, EffectModel, InstanceWords, Parameter

DM_WORDS = 512
PARAMETER_BASE = 16
SOURCE_KNOBS = (
    (.42, .25, .5, .48, .5, 0.),
    (.35, .5, .6, .5, .75, 0.),
    (.6, .5, 0., 0., 0., 0.),
    (0., 0., 0., 0., 0., 0.),
)
SOURCE_TOGGLES = ((1, 1, 1), (1, 1, 0), (0, 0, 0), (0, 0, 0))
FLOAT_BOOLS = frozenset((14, 15, 16))
OMITTED_SOURCE_INDEX = 17
AUX_INDEX, SAG_INDEX, ENABLE_INDEX = 36, 37, 38
AUX_PID, SAG_PID, ENABLE_PID = (PARAMETER_BASE + i for i in (AUX_INDEX, SAG_INDEX, ENABLE_INDEX))

# (display name, source index, optional enum labels). Native order controls
# paging; it is independent from source/PID order and persisted state order.
CONTROL_SPEC = (
    ('Sensitivity', 0, ()), ('Dynamics', 1, ()), ('Wet', 2, ()),
    ('Attack', 3, ()), ('EQ', 4, ()), ('Dry', 5, ()),
    ('Release', 24, ('Short', 'Custom', 'Long')),
    ('EQ Mode', 25, ('Dynamic', 'Fixed', 'Motion')),
    ('Physics', 26, ('Gentle', 'Stable', 'Lively')),
    ('Gate Thresh', 6, ()), ('Gate Release', 7, ()),
    ('Swell In', 8, ()), ('Swell Out', 9, ()),
    ('Release Time', 10, ()), ('Detector HPF', 11, ()),
    ('Envelope', 27, ('Fixed', 'Adaptive Rel', 'Adaptive Both')),
    ('Spread Route', 28, ('EQ', 'EQ + Volume', 'Volume')),
    ('Emphasis', 29, ('Off', '+3.5 dB', '+6 dB')),
    ('Spread', 12, ()), ('Auto Rate', 13, ()),
    ('Gate', 14, ()), ('Motion', 15, ()), ('Drive', 16, ()),
    ('Routing', 30, ('Mono', 'Stereo', 'External Key')),
    ('Swell Mode', 31, ('Aux Dynamic', 'Manual', 'Always Dynamic')),
    ('Stereo Mode', 32, ('Linked', 'Independent', 'Spread')),
    ('Sens Depth', 18, ()), ('Dyn Depth', 19, ()), ('Wet Depth', 20, ()),
    ('Attack Depth', 21, ()), ('EQ Depth', 22, ()), ('Dry Depth', 23, ()),
    ('Automation', 33, ('Off', 'One Shot', 'Bounce')),
    ('Auto Range', 34, ('Rise', 'Fall', 'Bipolar')),
    ('Auto Shape', 35, ('Linear', 'Cosine', 'Stepped')),
    ('Aux', AUX_INDEX, ()), ('Sag', SAG_INDEX, ()),
    ('Enable', ENABLE_INDEX, ()),
)


def source_default(index):
    if 0 <= index < 24:
        return SOURCE_KNOBS[index // 6][index % 6]
    if 24 <= index < 36:
        return SOURCE_TOGGLES[(index - 24) // 3][(index - 24) % 3]
    return int(index == ENABLE_INDEX)


def parameter(slot, name, index, labels):
    kind = 2 if labels else (1 if index in FLOAT_BOOLS or index >= AUX_INDEX else 3)
    default = source_default(index)
    return Parameter(
        name, slot, PARAMETER_BASE + index, kind, 0, 2 if labels else 1,
        int(default) if kind != 3 else default,
        name.replace(' ', '') + 'State', slot - 1,
        None if index == ENABLE_INDEX else slot - 1,
        restore='ignore' if index == ENABLE_INDEX else 'value', labels=labels,
        follow_enable=index == ENABLE_INDEX,
    )


PARAMETERS = tuple(parameter(slot, *spec) for slot, spec in enumerate(CONTROL_SPEC, 1))
PARAMETER_BY_PID = {p.pid: p for p in PARAMETERS}
SOURCE_INDEX_BY_NAME = {name: index for name, index, _ in CONTROL_SPEC}
ENABLE_SLOT = next(p.slot for p in PARAMETERS if p.pid == ENABLE_PID)

EFFECT = EffectModel(
    name='HD2_GlasshouseStereo', display='Glasshouse', preset_id=382,
    primitive=0x2392, source_model='HD2_CompressorDeluxeCompStereo',
    host_model='L6SPB_AcousGtrSimStereo', category=3, folder='Glasshouse', width=2,
    instance=InstanceWords(dm_words=DM_WORDS, pm_words=0, sdram_words=0),
    parameters=PARAMETERS,
    callbacks=Callbacks(init='GLASSHOUSE_INIT', control='GLASSHOUSE_CONTROL',
                        process='GLASSHOUSE_PROCESS'),
    self_bypass=True,
)
MONO_EFFECT = replace(
    EFFECT, name='HD2_GlasshouseMono', display='Glasshouse Mono', preset_id=383,
    primitive=0x0838, source_model='HD2_CompressorDeluxeCompMono',
    host_model='HD2_VolPanGainMono', width=1,
    callbacks=replace(EFFECT.callbacks, init='GLASSHOUSE_INIT_MONO'),
)
MODELS = (EFFECT, MONO_EFFECT)
