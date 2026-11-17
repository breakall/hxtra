"""The Atmosphere's model, state, storage and callback contract."""
from dataclasses import replace

from effect_model import Callbacks, EffectModel, InstanceWords, Parameter


EFFECT = EffectModel(
    name='HD2_AtmosphereStereo', display='Atmosphere', preset_id=380,
    primitive=0x012e, source_model='HD2_DelaySimpleDelayStereo',
    host_model='L6SPB_AcousGtrSimStereo', category=6, folder='Atmosphere', width=2,
    instance=InstanceWords(dm_words=163, pm_words=0, sdram_words=24000*2),
    parameters=(
        Parameter('Mode', 1, 5, 2, 0, 2, 1, 'ModeState', 0, 0,
                  labels=('Envelope', 'Tape', 'Stretch')),
        Parameter('Length', 2, 6, 3, 0, 1, .5, 'LengthState', 1, 1),
        Parameter('Modify', 3, 7, 3, 0, 1, .75, 'ModifyState', 2, 2),
        Parameter('Clock', 4, 8, 3, 0, 1, 1, 'ClockState', 3, 3),
        Parameter('Mix', 5, 9, 3, 0, 1, .5, 'MixState', 4, 4),
        Parameter('Play', 6, 10, 1, 0, 1, 0, 'PlayState', 5, None, restore='ignore'),
        Parameter('Overdub', 7, 11, 1, 0, 1, 0, 'OverdubState', 6, None, restore='ignore'),
    ),
    callbacks=Callbacks(init='MICROLOOPER_INIT', control='MICROLOOPER_CONTROL',
                        process='MICROLOOPER_BRIDGE_ENTRY'),
)


# The native framework owns each variant's mono/stereo graph routing.
MONO_EFFECT = replace(
    EFFECT, name='HD2_AtmosphereMono', display='Atmosphere Mono', preset_id=381,
    primitive=0x0100, source_model='HD2_DelaySimpleDelayMono',
    host_model='HD2_VolPanGainMono', width=1,
    instance=InstanceWords(dm_words=163, pm_words=0, sdram_words=24000),
    callbacks=replace(EFFECT.callbacks, init='MICROLOOPER_INIT_MONO'),
)
MODELS = (EFFECT, MONO_EFFECT)
