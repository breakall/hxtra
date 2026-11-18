# Glasshouse source reference

`reference.h` and `settings.h` are unchanged copies of the original Glasshouse
v0.3.2 working source from the user's `clean compressor pedal/firmware`
directory, imported on 2026-11-18. Both retain their GPL-3.0-or-later SPDX notice;
the repository LICENSE supplies the license text. The source directory has no
Git repository. Its Hothouse controller, device drivers and vendor tree are
not needed by this independent audio reference.

| Imported file | Original file | SHA-256 |
| --- | --- | --- |
| `reference.h` | `firmware/dsp.h` | `dae96bbe2a5fe30f668ba0e6304795bcb720a75fb3e81103d6351b650e089c47` |
| `settings.h` | `firmware/settings.h` | `f9b94f83a5c08c3e43e78eee66b9bc92ceec3d6c2130f3bc27bace87229ef891` |

Keep this reference independent of the SHARC implementation. Its libc math is
the comparison target for the port's numerical approximations.

`tests/glasshouse_source_tests.cpp` retains the original audio assertions from
the same project's `tests/test.cpp`, with its include redirected to this
reference and its Hothouse controller tests omitted. It checks the source's
compression stability, sag transitions, EQ, drive, routing, swell, gate and
automation independently of the SHARC implementation.
