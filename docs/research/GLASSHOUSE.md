# Glasshouse on HXtra with Atmosphere

Research date: 2026-11-18. HXtra baseline: `afdf284a1dba0d082258b3f4623518adfb3110d7`
(`atmosphere-upstream`). Status tags follow [conventions.md](conventions.md).
This is an implementation investigation; no Glasshouse HX Stomp audio kernel,
firmware candidate, or on-unit result is established here.

## Conclusion and scope

**[hypothesis]** Add **Glasshouse** as its own Dynamics effect, preserving the
existing Atmosphere mono/stereo models, NAM, Metronome and GR implementation.
The source algorithm has no delay buffer or hardware dependency in its audio
engine, so private state is relatively small. **The first milestone must be
recovering DSP boot-partition space:** the existing Atmosphere candidate has
only **200 bytes** left, and rerunning the current zero-run compactor saves
nothing. A full SHARC port should follow a proven storage plan. Further work is
translating the algorithm and measuring its worst-case execution time. An
additional model declaration alone cannot make it run. Evidence: the candidate
verification below, [Glasshouse engine][glass-dsp],
[HXtra architecture](../architecture.md),
[native effect declarations](../../tools/effect_model.py).

**[verified offline]** The reference is the user's existing **Glasshouse** in
`/Users/neo/Documents/ChatGPT/clean compressor pedal`, whose README identifies
v0.3.2 as the latest installed candidate and records the sag-pop listening retest.
That directory has no Git repository, so there is no source commit to cite. The
README's Hothouse results do not establish behavior on an HX Stomp. Preserve the
Glasshouse name; the source describes original digital approximations and does
not claim exact Chase Bliss Clean equivalence. Sources: [README][glass-readme],
[engine][glass-dsp], [settings][glass-settings].

## What has to be ported

**[verified offline]** `Engine` and `Settings` are C++14 code independent of
libDaisy. The surrounding `main.cpp` and `controller.h` provide Hothouse controls,
USB MIDI, preset storage and maintenance, not the audio algorithm. `Settings`
contains 24 normalized knobs and 12 three-position switches; its 108-byte
serialized format is specific to the source pedal. `Engine::Init()` starts
bypassed. Sources: [engine][glass-dsp], [settings][glass-settings],
[controller][glass-controller], [firmware entry][glass-main],
[Makefile][glass-make].

**[verified offline]** Host C++ sizing gives `Settings=108`, `Channel=72` and
`Engine=424` bytes. This supports the small-state assessment, but is not a SHARC
allocation: native word layout, channel variants and callback spills still need
an explicit map. Evidence: a C++14 host probe against [engine][glass-dsp].

### Sound and numerical behavior

**[verified offline]** The following is a source-level contract, not a new
measurement. In the formulas, `mix(a,b,t)=a+t(b-a)`,
`L(u,a,b)=a*(b/a)^clamp(u,0,1)`, and
`pole(t)=exp(-1/(48000*t))`. The existing audio rate is 48 kHz; knob remapping and
some coefficient updates occur every 16 samples, while envelopes and gains run
per sample. Source: [engine][glass-dsp], [math helpers][glass-settings].

| Area | Exact source behavior to retain |
| --- | --- |
| Sensitivity | Threshold `T=10^((-6-48*S)/20)` for normalized Sensitivity `S`. |
| Dynamics | Smoothed sag override blends Dynamics `D` toward 1. Ratio is `L(2*D,1,20)` below 0.5; otherwise `L(4*(D-0.5),20,100)`. The clamp means ratio already reaches 100:1 at `D=0.75`. Sag depth is `clamp(4*(D-0.75),0,1)`. |
| Detection/compression | Absolute-value detector with 1 ms rise/30 ms fall and a separate 200 ms slow envelope. Target reduction in dB is `clamp(max(0,20*log10(env/T))*(1-1/ratio),0,72)`, then Attack/Release smoothing. Detection is feedforward. |
| Timing | Attack `L(A,0.0005,0.3)` seconds. Release switch selects 0.05 s, custom `L(R,0.05,1.5)`, or 1.5 s. Adaptive modes shorten release, or attack and release, using the fast/slow transient ratio. |
| Sag | Raw gain `1/(1+6*sag_depth*(env/T)^2)`. Both the override and resulting nonlinear gain use independent 50 ms smoothing. Omitting either smoothing path risks the previously fixed switching pop. |
| Physics | Optional second-order spring changes reduction: gentle 3 Hz/damping 0.38 or wild 11 Hz/damping 0.12. Stable mode omits this term; final reduction is clamped to 0..72 dB. |
| Parallel levels | Wet and Dry independently use `4*k*k`; 0.5 is unity, 1 is approximately +12.04 dB. No automatic makeup gain. Dry is a DSP branch; swell, gate and the final limiter can affect it. |
| EQ | Trapezoidal one-pole filters. Performance EQ has a central deadband; negative values blend low-pass, positive values high-pass. Cutoffs map 220..18000 Hz and 25..2200 Hz. Fixed, activity-responsive and modulated modes differ. |
| Emphasis | Optional 950 Hz pre-emphasis and complementary de-emphasis; factor 0, 0.5 or 1. Post-filter coefficient changes with emphasis. Preserve the complementary pair. |
| Drive/limiter | Drive uses first-order antiderivative antialiasing for `x/(1+abs(x))`, primitive `abs(x)-log1p(abs(x))`; small sample deltas use a midpoint fallback. Otherwise hard clipping uses ceiling `0.98-0.23*D`. |
| Smoothing | Six performance controls and effect bypass use 8 ms poles. Gate rise is 2 ms; gate closing and swell timing are separately configurable. |

**[verified offline]** Stereo linked mode uses the maximum left/right detector;
independent/spread modes can separate detector response. Mono duplicates the left
program signal. External-key mode uses left program audio and right detector
audio, producing processed left audio on both outputs. Spread has separate EQ,
volume and panning behavior. A stereo graph is required to receive a distinct
right-channel key; this is not an extra hardware sidechain input.
Sources: [engine][glass-dsp], [routing documentation][glass-readme].

**[verified offline]** The source also implements gate, manual/automatic swells,
compression motion and six performance-control automation depths, with one-shot
or repeating bounce, rise/fall/bipolar range, and linear/cosine/step shapes.
One-shot automation restarts on effect enable. Manual Aux uses a rising edge to
start a complete dip, even for a brief tap. Motion frequency is derived from the
unsmoothed Attack setting; a port that simply recalculates everything from the
automated Attack value changes behavior. Sources: [engine][glass-dsp],
[settings pages][glass-readme].

### Native controls

**[hypothesis]** Use the native block editor and Controller Assign. Start the
visible parameter order with **Sensitivity, Dynamics, Wet, Attack, EQ, Dry**;
continue on native pages with Release, EQ mode, Physics and advanced settings.
Expose **Aux** and **Sag** as native assignable booleans. Native bypass should
remain independent. Treat complete control coverage as part of the finished
effect; a six-control prototype with fixed advanced defaults is only a milestone.
Evidence for the source controls: [README][glass-readme]. Evidence for native
parameter/state generation: [effect_model.py](../../tools/effect_model.py).

**[hypothesis]** Translate the source's options to native types: gate, motion and
drive become booleans; modes become labeled integers; continuous controls remain
floats. Hothouse page navigation, knob pickup, LED signals, its MIDI CC numbers,
127-slot flash bank, USB protocol and DFU gesture belong to that device and do
not need new HX Stomp counterparts. Its latch option is implemented by the
Hothouse controller, not the engine; use native assignment semantics. Native
snapshot/preset restore should restore configuration without accidentally
starting a manual Aux dip. Decide and test whether restoring Sag high is an
intentional sustained setting. Sources: [controller][glass-controller],
[settings][glass-settings], [Atmosphere controls](../atmosphere.md).

**[hypothesis]** Preserve the source's 8 ms enable fade and one-shot reset only
after checking how native bypass dispatches the new graph. Atmosphere's native
bypass behavior does not prove that Glasshouse will receive the enable edge it
needs. Avoid assuming a callback's `reset` entry means “bypass enabled”: establish
the actual lifecycle before wiring it. Sources: [source bypass][glass-dsp],
[callback declarations](../../tools/effect_model.py),
[Atmosphere native routing](../../tools/microlooper_native.py).

## Native registration and execution

**[verified offline]** HXtra runs audio on the ADSP-21469 SHARC; clang assembles
the separate Cortex-M4 UI patches. The shipped SHARC tool is a 48-bit ISA
assembler, not a C++ compiler; there is no ADI toolchain in the project. A Daisy
ARM binary cannot serve as the native audio callback. Sources:
[architecture](../architecture.md), [sasm.py](../../tools/sharc/sasm.py),
[source Makefile][glass-make].

**[hypothesis]** Keep the existing C++ engine as an independent host reference
and write a SHARC implementation using the established assembler/simulator.
Coefficient work can move to control updates where doing so preserves behavior;
audio-rate compression, sag, ADAA and smoothing need equivalent math.
`exp`, `log`, `log1p`, `pow`, `tan`, `sin`, `cos` and divisions require explicit
SHARC implementations or bounded approximations. Specify error tolerances and
check transition/silence behavior before optimizing. Replacing the source with
a stock compressor would not preserve the sag, Physics, EQ or modulation law.
Sources: [engine][glass-dsp], [simulator](../../tools/sharc/ssim.py),
[stock compressor research](sharc/cores/compressors.md).

**[verified offline]** `EffectModel` already generates matching Entry 0 browser
records, Entry 3 metadata/state and Entry 4 graph/parameter maps. It checks native
types, finite defaults, dense state indices, unique parameter identities, a
visible slot-ordered prefix and a valid mono/stereo host budget. Category **3**
is Dynamics; Atmosphere's **6** is Delay. The mono single-primitive host is
`HD2_VolPanGainMono`; the stereo host is `L6SPB_AcousGtrSimStereo`. A Dynamics
source model must independently pass category/width checks; copying Atmosphere's
Delay source does not. Sources: [effect_model.py](../../tools/effect_model.py),
[FX host contracts](../../tools/kit_patch_amp.py),
[Atmosphere declarations](../../tools/microlooper_definition.py).

**[hypothesis]** Use internal names such as `HD2_GlasshouseMono` and
`HD2_GlasshouseStereo`, folder Glasshouse under Dynamics, and display names
Glasshouse Mono / Glasshouse. A mono milestone and stereo milestone can share
one audio implementation with explicit channel width. Reserve new preset IDs,
primitive IDs and registry rows only after inspecting the complete configured
image; no IDs are allocated by this note.

**[verified offline]** Atmosphere already owns preset IDs **380/381**, primitive
IDs **0x012e/0x0100**, and registry rows **0x200058/0x2000a0**. Their callbacks and
code must remain installed. Preset IDs are limited to 1..832, and the writer
rejects occupied values. Older capacity notes describe a historical build,
including obsolete NAM identities; the current build replaces preset ID **555**
for NAM. Recount free IDs on the final build. Sources:
[Atmosphere declarations](../../tools/microlooper_definition.py),
[registry ownership](../../tools/patch_microlooper.py),
[checked writers](../../tools/kit_patch_amp.py), [current build](../../build.py),
[dated capacity notes](../resource-limits.md).

**[verified offline]** The process ABI uses private DM at `I0`, input/output
buffers at `I1/I2`, and 16-frame planar mono or stereo buffers. Native init/control
callbacks follow a different C ABI: init receives an instance descriptor in
`R4`; control receives PID in `R4`, a value-word pointer in `R8`, and instance
descriptor in `R12`. Register/mode/stack preservation and in-place buffer handling
must follow the actual native call, not the portable C++ calling convention.
Sources: [process bridge](../../src/sharc/microlooper_bridge.asm),
[C callbacks](../../src/sharc/microlooper_init.asm),
[ABI tests](../../tests/test_microlooper_init.py),
[bridge tests](../../tests/test_microlooper_bridge.py).

**[hypothesis]** Give each Glasshouse instance its own explicit DM state map,
including both channel states, smoothed controls, phases, envelope history and
callback spills. Start with zero SDRAM and zero PM data if the finished map
allows it; no source algorithm needs an audio history buffer. Initialize all
required fields deterministically. Do not copy Atmosphere's 163-word allocation
or 24,000-frame history: those belong to its algorithm. The host budgets are
per-primitive payload ceilings, not proof that several effects fit in a real
preset. Sources: [engine][glass-dsp],
[InstanceWords contract](../../tools/effect_model.py),
[native allocation replay](../../tools/sharc/microlooper_allocation.py).

## Storage and time: what fits is still open

**[verified offline]** The existing ignored candidate
`build/HX_Stomp_v3.80.0_HXtra.hxf` and `build/microlooper-build.json` pass:

```sh
python3 tools/verify_atmosphere_candidate.py \
  build/HX_Stomp_v3.80.0_HXtra.hxf \
  --report build/microlooper-build.json --allocation-only
```

Its Entry 2 is **524,088 / 524,288 bytes**, leaving **200 bytes**, with NAM2,
Atmosphere mono cost 1700 and stereo cost 2000. Outer HXF SHA-256:
`924f23d219e5f1b40a2a359920c9ad6d9602a7d2485b91ae9f3cd5f9122534c5`.
This checks the observed candidate's allocation/layout/control contract; it does
not establish a fresh build from `afdf284`, audio-equivalence verification or a
Glasshouse result. Reapplying `ldr_compact.compact()` to its Entry 2 saves
**zero bytes**. Sources: the named local candidate/report,
[verifier](../../tools/verify_atmosphere_candidate.py),
[current compactor](../../tools/sharc/ldr_compact.py).

**[hypothesis]** Prove a concrete boot-stream reduction or new checked encoding
before starting the complete audio port. Count bytes on the final image after
preserving NAM and Atmosphere. A larger DDR2 runtime reservation does not enlarge
Entry 2. Removing actually redundant loader payloads, reducing existing/new
emitted code, or introducing another validated storage representation are
candidates to investigate; none has been shown sufficient. The existing
NAM-scoped compaction has already been applied, so running it again is not a
solution. A scan applying its existing `pack_data()` encoder to every current
tag-4 data record also finds no net byte saving; merely broadening that encoder's
allowed ranges is therefore insufficient. Other record types and compression
schemes remain unresearched. Sources: the observed candidate and
[compactor](../../tools/sharc/ldr_compact.py),
[partition check](../../tools/patch_microlooper_build.py).

**[verified offline]** Source-only layout calculations for this baseline give
the following. These are generated plans with no boot records supplied, **not**
proof that a final image fits. Reproduce with `PYTHONPATH=tools:tools/sharc`,
`nam_multi.layout(['--mid-sweep','--slots',str(n)])`,
`microlooper.profile(n,metronome=True,gr=n==2)`, and
`microlooper_split.plan(layout, [])`. Atmosphere assembles to 1,085 core
instructions, 66 bridge instructions and 41 init/control instructions.
Sources: [layout](../../tools/sharc/microlooper.py),
[split planner](../../tools/sharc/microlooper_split.py),
[core assembler](../../tools/sharc/microlooper_audio.py),
[bridge assembler](../../tools/sharc/microlooper_bridge.py),
[callback assembler](../../tools/sharc/microlooper_init.py).

| Static calculation, normal 32-bit words unless stated | NAM2 profile | NAM3 profile |
| --- | ---: | ---: |
| Internal gap reserved between NAM and existing neighbors | 1,086 | 299 |
| Atmosphere internal ISA48 instructions | 677 | 191 |
| Physical words consumed, including even instruction padding | 1,017 | 288 |
| Nominal internal words left in that gap | 69 | 11 |
| NAM DDR2 reservation tail before Atmosphere | 13,082 | 13,082 |
| Atmosphere external code words, including bridge/callback padding | 777 | 1,503 |
| Nominal DDR2 tail after Atmosphere | 12,305 | 11,579 |

**[hypothesis]** There is no demonstrated internal space for a complete
Glasshouse hot loop alongside the current Atmosphere split. DDR2 execution is
the first candidate to measure. Atomically plan the executable sections for
both effects, retaining their current owners; running two independent copies
of Atmosphere's “use this gap/tail” planner will collide. The existing external
planner checks ISA48/normal32 physical aliases, native heaps and runtime claims;
reuse those checks with the complete set of owners. External RAM capacity alone
does not establish fetch speed. Sources:
[Atmosphere DSP linker](../../tools/patch_microlooper_build.py),
[physical placement checks](../../tools/sharc/microlooper_placement.py).

**[verified offline]** Entry 2 is capped at `0x80000` bytes. Padding and loader
records count, even when runtime DDR2 is available. Entry 3 has previously hit
an on-unit operational limit before its nominal partition limit; many new
controls multiply metadata growth. The historical figures in resource notes
are not current Atmosphere-build headroom. The final image/report is required
to state available bytes. Sources:
[linker partition checks](../../tools/patch_microlooper_build.py),
[resource limits](../resource-limits.md).

**[hypothesis]** No defensible Glasshouse DSP percentage exists yet. Measure
mono and stereo separately, including drive, adaptive modes, spread, automation,
rapid parameter changes and multiple instances, then set explicit native costs.
The existing 17%/20% Atmosphere charges cannot be reused for Glasshouse. Simulator
instruction counts do not include all real DDR2/cache costs. Sources:
[Atmosphere build/cost contract](../atmosphere.md),
[native cost validator](../../tools/effect_model.py),
[DSP cost research](m4/dsp-cost.md).

## Implementation sequence and acceptance evidence

All proposed work below is **[hypothesis]** until implemented and checked.

1. Prove enough Entry 2 space for a measured Glasshouse code budget while
   retaining Atmosphere. Freeze the supplied Glasshouse source/reference and
   its defaults, importing a licensed source snapshot when implementation starts
   so the fork does not depend on another local directory. Retain its
   feedforward Dynamics fix and both 50 ms sag smoothing paths. Generate vectors
   for silence, tones, transients, normalized control boundaries and switch edges.
2. Build one native mono Glasshouse block with the six performance parameters,
   source defaults for advanced options and deterministic init/control/process
   callbacks. Keep Atmosphere enabled throughout. This is the first working
   milestone, not the finished full-feature effect.
3. Add stereo and advanced native parameters, Aux/Sag, and automation. Verify
   multi-page UI counts, snapshots, preset serialization, block duplication,
   reorder/removal, graph recreation and bypass/one-shot behavior. Test restored
   action levels explicitly. Add full external-key routing only on stereo.
4. Link all metadata **before** the GR knob pass, as the current build requires;
   complete DSP placement after NAM/click/GR and bind a report to the final
   firmware hash. Re-run Atmosphere's verifier against that final combined image.
   Reject overlap, missing callbacks, changed Atmosphere declarations, partition
   overflow or inconsistent costs before producing a candidate.
5. Differential-test encoded Glasshouse instructions against the independent
   C++ engine. Include in-place/out-of-place mono/stereo buffers, exact native
   callback ABI, register canaries, bounded writes, two simultaneous instances,
   and lifecycle resets. Retain source regressions for sustained-note wobble,
   sag engagement/release pops, complementary emphasis, stereo balance, sidechain,
   ADAA, gate, swell, bounce and randomized finite/bounded output.
6. Build using the supplied stock HX Stomp 3.80.0 file and existing build
   conventions. Report final Entry 0/2/3/4 growth, executable ownership, per-instance
   words and image MD5. Measure execution on the HX Stomp using a RAM run; test
   representative full presets with Atmosphere, Glasshouse, NAM and other effects.
   Confirm listening behavior and admission charges before considering a release.

Evidence supporting this sequence: [current build ordering](../../build.py),
[Atmosphere final-image verifier](../../tools/verify_atmosphere_candidate.py),
[source regression suite][glass-tests],
[HXtra build/verification workflow](../building.md),
[RAM run](../../RAM_RUN.md). This research did not run hardware commands or
produce a Glasshouse firmware image.

## Checks performed and source provenance

**[verified offline]** The original Glasshouse host suite passes **2,736,124
checks** when compiled with `c++ -std=c++14 -O2 -Wall -Wextra -Werror -Ifirmware
tests/test.cpp`. The existing HXtra tests `test_effect_model.py`,
`test_microlooper_model.py` and `test_microlooper_build.py` pass **68 tests** with
the supplied stock firmware. These establish a usable source/baseline, not a
Glasshouse SHARC port. Sources: [source tests][glass-tests],
[effect declaration tests](../../tests/test_effect_model.py),
[Atmosphere model tests](../../tests/test_microlooper_model.py),
[Atmosphere build tests](../../tests/test_microlooper_build.py).

**[verified offline]** SHA-256 hashes identify the local source snapshot; no Git
commit is available for it:

| Source | SHA-256 |
| --- | --- |
| `firmware/dsp.h` | `dae96bbe2a5fe30f668ba0e6304795bcb720a75fb3e81103d6351b650e089c47` |
| `firmware/settings.h` | `f9b94f83a5c08c3e43e78eee66b9bc92ceec3d6c2130f3bc27bace87229ef891` |
| `firmware/controller.h` | `d680f99def90a36cf07f0b4468e89ac8270e8e510efee876751428057cc2d8b4` |
| `firmware/main.cpp` | `471b0f9187a6fd8026825f2acfa4ee9da885b0f986a7593b98317aad65052b1a` |
| `release/glasshouse-v0.3.2-candidate.bin` | `d2df8832c751a2231b05fc2a522a26a0306c3a03ec546c89b6122195ed3ab1b7` |

## Source ownership

**[verified offline]** Both source projects declare GPL-3.0-or-later. Preserve
the Glasshouse source SPDX/license provenance if importing reference code, and
retain HXtra's existing third-party notices. The audio core can be ported without
copying the source pedal's libDaisy/vendor tree. This is a source declaration
comparison, not a new legal conclusion. Sources: [HXtra license](../../LICENSE),
[HXtra license declaration](../../README.md#license),
[Glasshouse engine SPDX][glass-dsp], [Glasshouse license][glass-license],
[Glasshouse attribution][glass-readme].

[glass-readme]: </Users/neo/Documents/ChatGPT/clean compressor pedal/README.md>
[glass-dsp]: </Users/neo/Documents/ChatGPT/clean compressor pedal/firmware/dsp.h>
[glass-settings]: </Users/neo/Documents/ChatGPT/clean compressor pedal/firmware/settings.h>
[glass-controller]: </Users/neo/Documents/ChatGPT/clean compressor pedal/firmware/controller.h>
[glass-main]: </Users/neo/Documents/ChatGPT/clean compressor pedal/firmware/main.cpp>
[glass-make]: </Users/neo/Documents/ChatGPT/clean compressor pedal/Makefile>
[glass-tests]: </Users/neo/Documents/ChatGPT/clean compressor pedal/tests/test.cpp>
[glass-license]: </Users/neo/Documents/ChatGPT/clean compressor pedal/LICENSE>
