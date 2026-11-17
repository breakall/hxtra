#!/usr/bin/env python3
"""Minimal per-instance native C init/control callbacks for the micro-looper.

These callbacks use descriptor word0 supplied by the native allocator. They
do not allocate memory, qualify hardware, or retain stock Acoustic/IR state.
The synchronous constructor's transport controls are ignored while marker20
is zero; first audio processing sees Listen and arms the first live capture.
"""
from pathlib import Path

import sasm
import microlooper_visa as visa
from microlooper_definition import EFFECT

CALLSITE = 0x615287
RETURN_SITE = 0x61528e

ASM = Path(__file__).resolve().parents[2] / 'src/sharc/microlooper_init.asm'
STATE_WORDS = EFFECT.instance.dm_words
PM_WORDS = EFFECT.instance.pm_words
SDRAM_WORDS = EFFECT.instance.sdram_words
INIT_ENTRY = EFFECT.callbacks.init
CONTROL_ENTRY = EFFECT.callbacks.control


def assemble(base):
    if base < 0 or base % 2:
        raise ValueError('init/control PM base must be nonnegative and even')
    source = ASM.read_text().replace('MICROLOOPER_INIT_PM_BASE', hex(base))
    return sasm.assemble(source, ASM.name)


def registry(primitive, process, base):
    """Descriptor fields; graph allocation sizes must independently agree."""
    if primitive != EFFECT.primitive:
        raise ValueError('primitive ID does not match the Atmosphere declaration')
    _, symbols = assemble(base)
    return EFFECT.registry({**symbols, EFFECT.callbacks.process: process})


def instructions():
    sections, _ = assemble(0xe5000)
    return sum(len(section.words) for section in sections if section.kind == 'pm')


def invoke_from_stock_c_caller(sim, short_code, entry, *, limit=100):
    """Test fixture: execute an actual stock CJUMP and its two delay instructions.

    Only that call's destination is replaced. The caller supplies its native C
    frame, arguments and modifiers. This proves callback linkage, not that this
    particular callsite is the registry dispatcher or an allocator.
    """
    instruction = visa.decode([short_code[CALLSITE + j] for j in range(3)])
    if instruction.isa >> 40 != 0x18:
        raise ValueError('stock native C callsite differs')
    instruction = visa.Instruction(instruction.length,
                                  (instruction.isa & ~0xffffff) | entry,
                                  instruction.form)
    sim.pc = CALLSITE
    visa.step(sim, instruction)
    for _ in range(limit):
        if sim.pc == RETURN_SITE:
            return
        pc = sim.pc
        if pc in short_code:
            visa.step(sim, visa.decode([short_code[pc + j] for j in range(3)]))
        else:
            sim.step()
    raise ValueError('native callback exceeded instruction bound')
