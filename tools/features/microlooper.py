"""Development Atmosphere input/lifecycle wiring; enabled by build.py only.

The device experiment is deliberately absent from browser/release selection
until hardware validation and native DSP-cost measurement are complete.
"""
import kit_patch_amp as kit
import microlooper_native

FLAG = 'HX_MICRO_LOOPER'
ORDER = 110
WEB = False
MENU = False


def apply(p):
    import patch_microlooper
    if p.load is None:
        raise SystemExit('Atmosphere needs the complete registered image from build.py')
    models = kit.parse_entry3_full(p.load(3))['models']
    if not any(model['name'] == patch_microlooper.NAME for model in models):
        raise SystemExit('Atmosphere needs its metadata before the M4 build phase')
    microlooper_native.install(p, shared_input_hook=getattr(p, 'microlooper_input_hook', None))
