#!/usr/bin/env python3
"""Read the explicitly instrumented Acoustic Sim context; never modify a preset.

Requires the diagnostic-only image produced by patch_microlooper_probe, with
telemetry enabled. This is context telemetry, not a runnable Atmosphere.
Use --reply FILE to decode a saved binary result without connecting to USB.
"""
import argparse
import json
from pathlib import Path
import struct

from sharc.microlooper_adapter import decode_snapshot
import usb_commands

MAGIC = 0x4d4c0001
REPLY_BYTES = 96
DEFAULT_MAX_AGE_US = 1_000_000


def decode_reply(blob, *, max_age_us=DEFAULT_MAX_AGE_US):
    """Validate one complete binary reply and label its receive-time freshness.

    Time and age are the unit's uint32 microsecond clock. Age cannot distinguish
    a delay of a whole clock period (about 71 minutes); it is not a graph epoch.
    A repeated DSP source sequence must retain its original receive timestamp.
    """
    if type(max_age_us) is not int or not 0 <= max_age_us < 0x80000000:
        raise ValueError('maximum age must be an integer in 0..2147483647 microseconds')
    if not isinstance(blob, (bytes, bytearray)) or len(blob) != REPLY_BYTES:
        raise ValueError('diagnostic reply must contain exactly 96 bytes')
    magic, size, valid, sequence, received, now, age, reserved, *payload = struct.unpack('<24I', blob)
    if magic != MAGIC or size != REPLY_BYTES or reserved or valid not in (0, 1):
        raise ValueError('unsupported diagnostic reply header')
    result = dict(format_version=1, valid=bool(valid), source_sequence=sequence,
                  received_us=received, now_us=now, age_us=age,
                  native_stereo_abi_verified=False)
    if not valid:
        if sequence or received or age or any(payload):
            raise ValueError('no-data diagnostic reply contains a payload')
        return dict(result, status='no_data', context=None)
    if sequence & 1:
        raise ValueError('diagnostic reply contains an unpublished source sequence')
    if age != ((now - received) & 0xffffffff):
        raise ValueError('diagnostic reply age disagrees with its timestamps')
    return dict(result, status='fresh' if age <= max_age_us else 'stale',
                context=decode_snapshot(payload))


def read_context(ctl, *, max_age_us=DEFAULT_MAX_AGE_US, timeout=3.0):
    """Issue just the no-parameter diagnostic request on an existing session."""
    reply = ctl.ed.request(usb_commands.DIAGNOSTIC_CONTEXT, timeout=timeout)
    return decode_reply(reply, max_age_us=max_age_us)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reply', type=Path, help='decode a saved 96-byte result instead of using USB')
    parser.add_argument('--max-age-ms', type=int, default=1000,
                        help='receive-age threshold for stale data (default: 1000 ms)')
    args = parser.parse_args(argv)
    age = args.max_age_ms * 1000
    if not 0 <= age < 0x80000000:
        parser.error('--max-age-ms must be in 0..2147483')
    if args.reply:
        result = decode_reply(args.reply.read_bytes(), max_age_us=age)
    else:
        from hx_ctl import HxCtl
        with HxCtl() as ctl:
            result = read_context(ctl, max_age_us=age)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
