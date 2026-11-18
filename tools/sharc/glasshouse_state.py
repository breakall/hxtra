"""Glasshouse private word map shared by metadata, callbacks and audio.

All addresses are offsets into each primitive's independently allocated DM.
The native graph owns words0..3. No PM data, audio history or global state.
"""
STATE_WORDS = 512
INITIALIZED, CHANNELS = 4, 5
PENDING_AUX, PENDING_ENABLE = 6, 7
PARAM_BASE = 16
KNOB_DEFAULTS = ((.42,.25,.5,.48,.5,0.),(.35,.5,.6,.5,.75,0.),(.6,.5,0.,0.,0.,0.),(0.,0.,0.,0.,0.,0.))
TOGGLE_DEFAULTS = ((1,1,1),(1,1,0),(0,0,0),(0,0,0))
AUX, SAG, ENABLE = 52, 53, 54
RUNTIME_BEGIN, RUNTIME_END = 64, 400
CHANNEL_BASE, CHANNEL_STRIDE = 128, 32
SPILL_BEGIN = 400

def knob(page, index):
    return PARAM_BASE + page*6 + index

def toggle(page, index):
    return PARAM_BASE + 24 + page*3 + index
