# Glasshouse implementation plan

Port the existing Glasshouse v0.3.2 audio behavior to native mono and stereo
Dynamics blocks on `breakall/hxtra`, branch `glasshouse`, based on Atmosphere
commit `afdf284`. Keep the Glasshouse name and preserve Atmosphere, NAM,
Metronome and GR. [Research and source fingerprints](research/GLASSHOUSE.md)
define the starting behavior.

## Delivery and verification

The deliverable is buildable native firmware with an independent C++ reference,
encoded SHARC audio tests, checked model registration and allocation, a combined
image verifier, and player/build documentation. Source defaults, feedforward
compression, both sag smoothing stages, EQ, Physics, gate, swell, stereo/key
routing and automation belong to the finished effect. Native controls replace
the Hothouse hardware UI and storage. A partial kernel is an integration
milestone, not completion.

No hardware validation is claimed from host tests. DSP costs must be explicit
until measured on the HX Stomp. Build the candidate at
`build/HX_Stomp_v3.80.0_HXtra.hxf`; record its hash and resource report. Keep the
existing stock-byte, archive-integrity and partition guards. Do not distribute
Line 6 firmware in Git.

## Parallel work and ownership

| Workstream | Owned files | Deliverable |
| --- | --- | --- |
| DSP kernel | `src/sharc/glasshouse*.asm`, `tools/sharc/glasshouse_audio.py`, `tools/sharc/glasshouse_state.py`, `tests/test_glasshouse_audio.py` | Complete per-instance mono/stereo processing, explicit state layout, bounded math, simulator harness and differential checks |
| Native model and callbacks | `tools/glasshouse_definition.py`, `tools/patch_glasshouse.py`, `tools/sharc/glasshouse_init.py`, `src/sharc/glasshouse_init.asm`, `tests/test_glasshouse_model.py`, `tests/test_glasshouse_init.py` | Native Dynamics declarations, distinct checked identities, parameter/state mapping, C init/control callbacks and serialized-control checks |
| Storage and linking | `tools/sharc/glasshouse_storage.py`, `tools/patch_glasshouse_build.py`, `tests/test_glasshouse_storage.py`, any specifically coordinated loader changes | A proven storage strategy, disjoint executable placement alongside Atmosphere, native registry installation and resource report |
| Orchestration and integration | This plan, `build.py`, portable reference under `tools/glasshouse/`, reference vectors, final-image verifier, player docs and research/index updates | Pinned source oracle, shared interface decisions, combined build, review, integration tests and push |

Agents work in the same checkout, without switching branches or committing.
Each agent owns only the files above; changes to shared existing modules are
coordinated with the orchestrator first. Communicate interface decisions before
dependent code, and report executable instruction counts early.

## Interfaces and dependency order

1. Pin the hardware-free C++ engine and settings with their original SPDX
   notices and source hashes. Keep the oracle independent from SHARC math.
2. Agree the DSP state map and parameter map immediately. The kernel owns the
   private word layout; model/callback code consumes it. Visible parameters
   start Sensitivity, Dynamics, Wet, Attack, EQ, Dry. Reserve distinct identities
   from the actual image; Atmosphere IDs and registry rows remain owned.
3. In parallel, implement storage, the DSP kernel, and native metadata/callbacks.
   The kernel exports relocatable sections and symbols via `assemble(base)`;
   the linker places them and patches only checked unused registry rows.
   Native audio uses the established 16-frame planar ABI. The state and all
   history belong to each instance.
4. Prove the storage path before accepting a combined candidate. The existing
   observed Atmosphere image has 200 bytes left in Entry 2; that constrains the
   current loader representation rather than all possible loading designs.
   Compare final decoded boot memory and record ordering for any compaction;
   if a different loading path is required, implement and test its complete
   startup chain rather than bypassing the partition guard.
5. Register all models before GR metadata changes, and compose the DSP additions
   without overlapping Atmosphere, NAM, native heaps or shared hooks. Explicit
   feature flags and per-width costs select Glasshouse. Preserve feature-off
   output and existing supported NAM profiles.
6. Run the independent source suite and encoded-kernel comparisons for normal,
   extreme and changing settings. Cover silence, steady tones, transients,
   sag/Aux edges, automation, all modes, in-place buffers, multiple instances,
   native callback/register preservation and bounded memory access.
7. Build and verify the final configured archive. Check model identities,
   callbacks, preset serialization, allocations, executable ownership,
   partition sizes and every archive checksum. Run Atmosphere verification on
   the same final image and report the image hash.
8. Review changes, update this plan with evidence and remaining hardware checks,
   commit and push the implementation to the existing `glasshouse` branch.

## Completion record

- Planning: complete; workstreams dispatched after this file is saved.
- Source oracle: complete; original engine/settings pinned by SHA-256. The
  imported source audio regressions pass with address/undefined-behavior
  sanitizers, and the binary vector oracle drives independent comparisons.
- Native models and controls: complete; presets 382/383, 37 visible controls
  and one hidden enable follower. Native kind 24 keeps processing active while
  bypassed; tests execute the original enable/bypass dispatcher. Live Aux
  snapshot/controller edges use native level semantics; construction-high Aux
  does not trigger a startup dip. Native metadata lookup and Edit-page navigation
  reach all 37 controls across 13 pages, including the last Sag control.
- DSP engine: complete; per-instance 512-word DM, no PM data or audio history.
  Full source options run as 2,593 emitted SHARC instructions (2,594 padded). Independent
  review regressions cover high-gain ADAA precision and control pulses entirely
  between audio blocks, including parameter/event ordering. Native callbacks
  occupy 152 instructions. The reference uses its original libc math.
- Storage and combined linking: complete; LZ32 startup transport restores all
  eight pinned external boot payloads before original startup, preserves the
  stock SPI kernel and enforces the original partition limit. Both NAM2/GR/click
  and NAM3/click configurations preserve Atmosphere in integration tests.
- Final image and offline verification: complete. The combined image uses
  495,664 / 524,288 bytes in Entry 2, leaving **28,624 bytes**. Both final-image
  verifiers execute emitted instructions successfully. Integration and native
  editor and performance checks pass **223 tests**; default firmware/web regression checks pass **12 tests**
  with two unavailable-device skips. The default HX Stomp firmware checksum
  remains unchanged.
- HX Stomp timing and listening: requires a verified candidate and device run.

## Reproducing the verified candidate

The verified configuration includes Atmosphere and all standard command-line
features. Glasshouse's **40% stereo / 30% mono** admission charges are provisional
development settings, not measured hardware costs.

```sh
HX_GLASSHOUSE=1 HX_GLASSHOUSE_DSP_COST=4000 HX_GLASSHOUSE_MONO_DSP_COST=3000 \
HX_MICRO_LOOPER=1 HX_MICRO_LOOPER_DSP_COST=2000 HX_MICRO_LOOPER_MONO_DSP_COST=1700 \
HX_TUNER=1 HX_BPM=1 HX_DSP_METER=1 HX_BREATHING_LINE=1 HX_LONG_PRESS=1 \
HX_MORE_SNAPSHOTS=1 HX_CLICK=1 HX_GR=1 HX_TAP_COLOR=1 HX_REAL_NAMES=1 \
  python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf
```

The final build reused the previously passed NAM kernel check with `--no-check`.
The command above runs that check as well. Verification commands are in
[Glasshouse](glasshouse.md#build).

Output: `build/HX_Stomp_v3.80.0_HXtra.hxf`.

- HXF MD5: `b0b7ff3f3577d64d76d53a79a8898fae`.
- HXF SHA-256: `3b330ea717cb56b92c9f3a754305eaa8f4a3fabca9bb324a33d02e1bb2ad6455`.
- Runtime startup proof: all 53,338 words across eight external boot records
  reconstruct exactly; the original SPI kernel and reset vector are preserved.
- Reports: `build/glasshouse-build.json`, `build/microlooper-build.json`,
  `build/glasshouse/optimization-glasshouse-verification.json` and
  `build/glasshouse/optimization-atmosphere-verification.json`.

These artifacts are local and gitignored. The fork contains source, tests and
build instructions, without a redistributed Line 6 firmware image. Hardware
startup, DDR2 execution cost, audio listening and HX Edit interaction are not
established by these offline checks.

## DSP execution optimization

Compared with the initial port at `f91e3c12a1f2d79c0ecaf9fdc521b262c03700fc`,
the optimized callback executes **24.5–30.1% fewer instructions** across eight
mono/stereo default, compression, Drive and demanding-mode profiles. Counts
below are the maximum of eight warm 16-frame callbacks with deterministic input
and the hardware reciprocal seed model. They exclude physical DDR2/cache stalls
and are not measured DSP percentages.

| Configuration | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Default mono | 20,860 | 14,579 | 30.1% |
| Default stereo | 33,622 | 23,921 | 28.9% |
| Demanding mono | 32,019 | 24,012 | 25.0% |
| Demanding stereo | 52,396 | 39,541 | 24.5% |

Active-callback DM reads fall 25–29% and writes 32–40%. Cold initialization and
changed-setting blocks also execute fewer instructions. Admission charges remain
the explicit provisional 30% mono / 40% stereo values until device timing is
available.

The implementation retains smoothed controls in caller-preserved registers,
reuses filter/threshold/ratio inverses, and recalculates settings-derived
coefficients only when their ten raw inputs change. Trigonometric work is
omitted when no active mode uses it; phases keep advancing. Mono avoids the
duplicate detector. Drive caches the previous antiderivative while preserving
the small-delta path and invalidating its cache when required. Gate, swell and
filter histories still advance with their output options disabled.

The 223-test suite covers native control updates, off/on histories, graph
reinitialization, register/memory bounds and instruction budgets. Another 64
seeded scenarios cover 7,520 frames and isolated instances at unchanged source
tolerances. Both final-image verifiers pass; only DSP Entry 2 differs from the
previous all-features firmware. No device commands were used for optimization.

To compare with the initial source snapshot:

```sh
mkdir -p /tmp/glasshouse-before
git archive f91e3c12a1f2d79c0ecaf9fdc521b262c03700fc \
  tools/sharc/glasshouse_audio.py tools/sharc/glasshouse_state.py \
  src/sharc/glasshouse_math.asm | tar -x -C /tmp/glasshouse-before
python3 tools/profile_glasshouse.py --baseline /tmp/glasshouse-before \
  --json build/glasshouse/optimization-profile.json
```
