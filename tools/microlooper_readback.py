"""Explicit diagnostic readback ABI; no feature discovery or runtime install."""
import struct

import usb_commands

MODULE = 'src/m4/microlooper_readback.s'
CMD = usb_commands.DIAGNOSTIC_CONTEXT
TAG, CONTEXT_MAGIC, WORDS, REPLY_BYTES = 0x4d4c0001, 0x6d6c6131, 16, 96
RX_LITERAL, RX_STOCK = 0x28da6134, 0x10001095
REGISTER_CALL, REGISTER_ALL = 0x28d96adc, 0x28e1661c
CALLED = (
    (0x28e165f0, '7b28 0dd8'),
    (0x28e19204, '0020 7047'),
    (0x28e157c8, '0228 07d0 054b a3f1 0802'),
    (0x28e157ec, '0228 07d0 054b a3f1 0c02'),
    (0x28e15810, '0228 07d0 054b a3f1 6402'),
    (0x28e15834, '0228 0c4b 4ff0 0002'),
    (0x28e15878, '70b5 82b0 8323'),
    (0x28e24c00, '5ff8 00f0 bd34 0010'),
    (0x28e24bb0, '5ff8 00f0 d134 0010'),
    (0x28da6458, '0120 fdf7 a7b9'),
)


def asm_include():
    return (f'.equ MLR_CMD, {CMD:#x}\n.equ MLR_TAG, {TAG:#x}\n'
            f'.equ MLR_CONTEXT_MAGIC, {CONTEXT_MAGIC:#x}\n')


def install(p, *, rx_target=None, register_target=None):
    """Stage the explicit diagnostic in a Patch, preserving supplied prior chains.

    A finalized earlier build can have a different RX literal and registration
    call. Both default to the actual existing targets. The caller finishes chains
    and serializes the result, just as for the other Patch users.
    """
    if MODULE in p.modules:
        raise SystemExit('microlooper readback diagnostic is already staged')
    for address, stock in CALLED:
        p.expect(address, bytes.fromhex(stock), 'diagnostic editor/clock native ABI')
    prior_rx = p.u32(RX_LITERAL) if rx_target is None else rx_target
    if not prior_rx & 1:
        raise SystemExit('diagnostic RX callback must be a Thumb function pointer')
    h1, h2 = struct.unpack('<2H', p.read(REGISTER_CALL, 4))
    if h1 & 0xf800 != 0xf000 or h2 & 0xd000 != 0xd000:
        raise SystemExit('diagnostic registration site must contain a Thumb BL')
    sign, j1, j2 = (h1 >> 10) & 1, (h2 >> 13) & 1, (h2 >> 11) & 1
    displacement = ((sign << 24) | ((1 ^ j1 ^ sign) << 23) | ((1 ^ j2 ^ sign) << 22)
                    | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1))
    current_register = REGISTER_CALL + 4 + displacement - (sign << 25)
    prior_register = current_register if register_target is None else register_target
    # Any existing RAM chain must point into this image, not an invented address.
    if prior_rx != RX_STOCK:
        p.read(prior_rx & ~1, 2)
    p.read(prior_register, 2)
    m = p.module(MODULE, inc={'microlooper_readback.inc': asm_include()})
    p.chain_ptr(RX_LITERAL, prior_rx, before=m['mlr_frame'])
    p.chain_bl(REGISTER_CALL, prior_register, after=m['mlr_register'])
    return dict(module_va=m.va, prior_rx=prior_rx, prior_register=prior_register,
                **{symbol: m[symbol] for symbol in m.symbols})
