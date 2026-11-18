"""Assemble checked Glasshouse init/control callbacks for the stock scalar C ABI."""
from pathlib import Path

from glasshouse_definition import EFFECT, PARAMETER_BASE, source_default
import sasm
import ssim
from microlooper_init import invoke_from_stock_c_caller, CALLSITE, RETURN_SITE

ASM = Path(__file__).resolve().parents[2] / 'src/sharc/glasshouse_init.asm'
STATE_WORDS = EFFECT.instance.dm_words
PM_WORDS = EFFECT.instance.pm_words
SDRAM_WORDS = EFFECT.instance.sdram_words
INIT_ENTRY = EFFECT.callbacks.init
CONTROL_ENTRY = EFFECT.callbacks.control


def default_words():
    """Source-normalized knob words followed by integer modes and action levels."""
    return tuple(ssim.f2b(source_default(i)) if i < 24 else int(source_default(i))
                 for i in range(39))


def assemble(base):
    if type(base) is not int or base < 0 or base % 2:
        raise ValueError('init/control PM base must be nonnegative and even')
    defaults = []
    previous = None
    for offset, word in enumerate(default_words(), PARAMETER_BASE):
        if word != previous:
            defaults.append(f'R0 = {word:#x};')
        defaults.append(f'DM({offset},I4) = R0;')
        previous = word
    source = ASM.read_text().replace('GLASSHOUSE_INIT_PM_BASE', hex(base))
    source = source.replace('GLASSHOUSE_DEFAULTS', '\n'.join(defaults))
    return sasm.assemble(source, ASM.name)


def registry(primitive, process, base, *, effect=EFFECT):
    if primitive != effect.primitive:
        raise ValueError('primitive ID does not match the Glasshouse declaration')
    _, symbols = assemble(base)
    return effect.registry({**symbols, effect.callbacks.process: process})


def instructions():
    sections, _ = assemble(0xe5000)
    return sum(len(section.words) for section in sections if section.kind == 'pm')
