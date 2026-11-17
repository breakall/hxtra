# Atmosphere compute optimization candidate

2026-11-17. This is an offline candidate, not a measured hardware DSP budget.
The baseline is the actual stereo core at commit `fb2d42c`, SHA-256
`e499522a87a4435e2c48da0c64e1b3ab28450c5a2f283d96849949c97162b0f2`.
No production source, NAM implementation, model metadata, allocation or hardware
was changed by this investigation.

## Changes supported by source behavior

**[verified offline]** The reference's read extent depends only on captured
history size, Mode and Length. The captured size and processed controls are
constant throughout a 16-frame callback. Tape reads its cropped length; Envelope
and Stretch read the full capture. Compute the selected read length, splice
width, splice period and ceiling once after capture/control handling, in the
existing private scratch words73/95/96/106. Remove repeated geometry calculations
from `ml_read`/`ml_at`, and reuse the same period for transport wraps. No new
state, initialization path or resource claim is introduced. Source:
[`Reference::Loop` and `LoopRead`](../../../tools/microlooper/reference.h),
[`CUSTOM_AMP_ENTRY`, `ml_sample`, `ml_read`, `ml_at`](../../../src/sharc/microlooper_kernel.asm).
Mode changes at callback boundaries, captures, shrinking Length and partial
recapture are included in the existing oracle tests. This does not establish
native delivery of controls partway through one audio callback.

**[verified offline]** Keep `ml_at`'s interpolation coordinates, adjacent indices
and stereo sample pairs in registers instead of repeatedly storing and loading
scratch words103..110/86. Keep precisely the original subtract/multiply/add
order and the same four SDRAM sample reads. R13/R14 are already saved/restored
by the audio core; the helper's callers do not retain live values in them.
The a/b wrap and ceiling rules remain unchanged. This saves static code as well
as executed instructions. Ten thousand randomized direct helper reads match the
baseline's two result words bit-for-bit, including fractional extents and
nonzero wrapped physical ring starts.

**[verified offline]** Add exact common paths to `ml_wrap`: return an already
in-range position; subtract one extent when a positive position is less than
twice the extent; add one extent for a negative position strictly greater than
minus the extent. Retain the existing bounded binary remainder otherwise.
Preserve signed zero, including the negative-exact-multiple fallback. The
existing bitwise float32-fmod regression covers the helper, and whole-engine
oracle tests exercise reverse reads, all clocks and splices. This adds15 static
instructions while reducing repeated executed work.

## Candidate and verification

Recommended local candidate:
`build/optimization-probes/compute/geometry-register-wrap.asm`, SHA-256
`c71346091806a1229f54dc8ecf4e5e3449f51854d2ae9f86d21fddbee9bfd0fb`.
It contains1047 ISA instructions, versus1091 in the baseline, with unchanged153
private core words and199 native DM words. Its regions are:

| Region | Baseline instructions | Candidate instructions |
| --- | ---: | ---: |
| `ml_sample..ml_invalid` | 524 | 488 |
| `ml_wrap..ml_read` | 32 | 47 |
| `ml_read..ml_at` | 73 | 63 |
| `ml_at..ml_return` | 82 | 41 |

**[verified offline]** The existing actual C++-oracle, allocation guards,
independent histories, register preservation and stereo bridge checks all pass:
153 tests in37.27 seconds. The test process overrides only
`microlooper_audio.ASM` to the candidate and clears its assembly cache. It does
not temporarily overwrite the shared production assembly.

```sh
PYTHONPATH=tools:tools/sharc .venv/bin/python - <<'PY'
from pathlib import Path
import microlooper_audio as audio
import pytest
audio.ASM = Path('build/optimization-probes/compute/geometry-register-wrap.asm').resolve()
audio.assemble.cache_clear()
raise SystemExit(pytest.main(['-q', 'tests/test_microlooper_audio.py',
                             'tests/test_microlooper_bridge.py']))
PY
```

**[verified offline]** The unchanged720-configuration instruction profiler
samples initial listening, capture and old-head/seam paths. The maxima below
are executed instructions per16 stereo frames, not hardware cycles or DSP
percentages. Results are stored locally in
`build/optimization-probes/compute/profile-final.json`.

| Path | Baseline peak | Candidate peak | Reduction |
| --- | ---: | ---: | ---: |
| Initial listening | 3186 | 3209 | -0.7% |
| Envelope | 9380 | 7595 | 19.0% |
| Tape | 7580 | 5782 | 23.7% |
| Stretch | 13247 | 9671 | 27.0% |

The small listening increase is the23-instruction geometry preparation once
per callback. The main anticipated hardware benefit remains unmeasured here:
fewer instruction fetches and scratch accesses, plus a smaller hot region for
internal placement. Preserve separate A/B measurements for compute changes and
code placement before combining their reported gains. The simulator does not
model external instruction-fetch latency, native cache conflicts or scheduling.

A rejected alternative caches geometry in a new private word114 across reads.
It also passes the153 tests, but adds state without demonstrated native
mid-callback control scheduling that would justify it. It is not recommended.

**[verified offline: additional bitwise differential]**
`build/optimization-probes/compute/differential.py` compares the frozen baseline
and the recommended candidate with initialized, nonzero synthetic histories,
120 mode/clock/Modify configurations, overdub, abrupt Mode/Length/Clock changes,
return to listening and recapture. All13,440 stereo frames, persistent state
words20..65/111..113, and every SDRAM ring write match bit-for-bit. Result:
`build/optimization-probes/compute/differential-result.json`.

The contiguous `ml_sample..ml_return` region shrinks from718 to646 instructions,
which leaves more room when combined with a separately verified internal-code
placement. The `ml_wrap..ml_return` helper region shrinks from187 to151.

## Production integration

The accepted source additionally extracts the36-instruction reconstruction and
mix-smoothing region into a37-instruction helper immediately before `ml_return`.
The call and return add2 static instructions and32 executed instructions per
16-frame callback. This places more repeated work inside the same NAM3 gap.
Flat and NAM3-split audio/bridge suites each pass153 tests;20,224 frames and1024
direct-region cases preserve complete memory, registers, status and output
bit-for-bit. The final source has1049 instructions and SHA-256
`a349ebf122f6849d5afa92ae7364a66a47d2589c491e125281af7d24aeebc253`.
Hardware results and the experimental budgets are recorded in the
[hardware log](microlooper-hardware-log.md#internal-hot-code-optimization).

The subsequent native mono/stereo implementation shares a 1085-instruction
planar core, removes the private interleave buffer and uses 163 native DM words.
The 1049-instruction source hash above identifies the preceding stereo-only
checkpoint. Current measurements and final identities are in the
[mono hardware continuation](microlooper-hardware-log.md#native-mono-implementation).
