# Atmosphere hardware test log

2026-11-17. Device: the user's HX Stomp, confirmed running installed firmware
3.80. Tests use the existing RAM loader with `--writes ram`. No permanent
firmware update, preset save, IR import or factory reset has been performed.

The effect was renamed Atmosphere after the capture checkpoint. Older ignored
firmware artifacts and raw diagnostic captures retain their original names.
Numeric model ID 380 and primitive 0x012e are unchanged.

## First boot failure

**[verified on unit]** Candidate HXF MD5
`5698d12ba91646e21bd382d90ec920c8` reaches the preset display, then freezes:
front-panel controls do not respond, and the native editor/updater services do
not complete USB handshakes. The user supplied a photograph of preset
`04B FX:Soft Filter` and reported the controls unresponsive. Power-cycling
restores the installed firmware and normal USB status queries.

The RAM-loader SDRAM test and transfer CRC checks pass. Its eMMC initialization
can report status `0x10b`, as in historical successful RAM runs; the installed
version was independently confirmed by the user. No eMMC comparison bypass
option or persistent-write mode was enabled.

## Controlled comparisons

**[verified on unit]** A local sequenced harness in
`build/ram-probes/probe.py` enters update mode, uploads the RAM-only loader,
waits for its USB identity, loads the selected image and checks the normal
editor service with `tools/hx_ctl.py status`. It writes per-image logs and
reports in the same ignored directory. The HX Stomp is selected by its observed
USB path to exclude the PreSonus AudioBox's separate DFU interface.

| RAM image | Isolated change | Result |
| --- | --- | --- |
| Stock 3.80 | Unmodified stock application through the same RAM loader | Normal USB status succeeds. |
| Complete Atmosphere candidate | Exact original HXF, repeated through the sequenced harness | USB message-header timeout; reproducible freeze. |
| No Atmosphere tick | Restore only the original periodic callback pointer | Same failure. Background polling is not the sole trigger. |
| No Atmosphere M4 hooks | Restore the nine lifecycle entries, parameter/bypass filters and tick; route input through the existing long-press handler | Normal USB status succeeds. All non-application entries remain byte-identical to the failing candidate. |
| No object-init hook | Restore only the block-initialization entry | Same failure. Removing this entry alone is insufficient. |
| No lifecycle hooks | Restore all nine lifecycle entries | Same failure. This group is not the sole trigger. |
| No parameter filter | Restore only the parameter setter entry | Same failure. This filter is not the sole trigger. |

**[inference from the paired images]** The failing behavior depends on Atmosphere's
M4 control integration. The identical DSP, graph/model data and other archive
entries can boot and serve the existing preset when that integration is
disabled. This does not establish which remaining hook is faulty or prove
Atmosphere audio execution, native stereo lanes, timing or lifecycle correctness.
The passing diagnostic lacks required Atmosphere controls and is not a release.

No production fix has been applied from these observations, and the original
candidate must not be permanently installed while this failure remains unresolved.

## Incremental restoration from a working image

The clean upstream checkout at `8004c8e8d032046306374b006a4693bec3bb4cab`,
with the standard browser features and Atmosphere disabled, builds HXF MD5
`e6461b4ff45be2742bce088a3cfffab8` and passes the same on-unit RAM/USB check.
A separate pristine source extraction reproduces that hash.

Starting from the passing no-Atmosphere-M4-hooks diagnostic, restore one control
entry at a time. Each stage preserves all other archive entries byte-for-byte;
the final prepared stage exactly reproduces the complete failing candidate.

| Stage | Newly enabled control | On-unit RAM/USB result |
| --- | --- | --- |
| 00 | None; Atmosphere DSP/model data only | Pass. |
| 01 | Selective bypass filter at `0x28dd11aa` | Pass. |
| 02 | Parameter filter at `0x28e04864` | Pass. |
| 03 | Shared footswitch input veneer routes through Atmosphere | Message-header timeout; failure returns. |

Background polling and all lifecycle hooks are disabled in stage 03. The
input-only comparison also fails without either filter, ruling out their
interaction as a necessary condition. The user confirmed the controls froze
at stage 03 before power-cycling.

Further isolated input-path comparisons:

| Diagnostic | Enabled behavior | Result |
| --- | --- | --- |
| Input only | Atmosphere input routing, no other Atmosphere hooks | USB message-header timeout. |
| Forward only | Atmosphere wrapper saves/restores registers and forwards every event to the existing handler | Pass. |
| Locks only | Graph and assignment locking plus the pressed-state read; discovery and transport writes removed | USB message-header timeout. |
| Graph lock only | Graph acquisition/release, no discovery, pressed-state read or transport writes | Pass. |
| Graph lock and pressed-state read | Add the pressed-state read to the preceding diagnostic | Pass. |
| Correct manager locks | Resolve the real native manager for assignment lock/unlock; no discovery or transport writes | Pass. |
| Correct manager full input | Restore discovery/routing, resolving the real manager for assignment traversal too | Pass. |

### Root cause isolated in the input controller

**[verified on unit and against native code]** The callback context is the UI
listener object; it is not the bypass-assignment manager. Atmosphere passed that
context to `microlooper_controller_input_lock/unlock` as though its `+4` field
were an assignment mutex, and passed it into the assignment-list accessor.
Native code obtains the separate manager through getter `0x28d96084`, whose
literal at `0x28d96088` is `0x28128b4c`. Native accessors `0x28dd71c4` and
`0x28dd71e4` lock that manager at `+4`. The UI listener constructor
`0x28dd27fc` instead populates listener callback/context fields in its object.

The paired failing and passing RAM images establish that correcting this object
selection removes the input-path freeze. They do not establish whether the
wrong mutex address caused a blocked wait or a fault inside the native mutex
implementation. Native static evidence is retained in ignored
`build/ram-probes/assignment-manager-analysis.snapshot`, including REA records
`ev_ce5e6f144324517b42f56117abe0c2fbb6843804a0d4128c55d148c360229159`,
`ev_7bef8704ec744e162a1f03ed601f50afefd4e28173d0344a34bee7f79e3af8ed`,
and `ev_c6dc01a0b6041e2558d69ab70d53e177375c30a3b1d91bc4f96a677b87c4b80f`.
The failed `0x28dd10c0` decompiler lookup in the second record is not used
as evidence; the observed key handler, constructor, getter and accessors suffice.

The controller fixture previously used one address for both roles. Separating
its UI context and manager makes the new input regression fail at the incorrect
lock address before the fix. Resolving the native getter in lock, unlock and
refresh makes the regression and all 82 M4/lifecycle tests pass. The installed
controller manifest is now version 2; NAM and DSP data are unchanged.

The rebuilt HXF is `build/ram-probes/micro-manager-fixed.hxf`, MD5
`6c37466f5f5519a58785260ecd97950c`. Its input plus both filters passes on unit.
Polling and all nine lifecycle additions pass when restored one at a time.
The adjacent-forward-move stage first encountered a RAM-loader reconnect
failure before its application image was uploaded. After physical recovery,
the same stage and all remaining stages pass. That first report records a
setup failure, not an observed failure of the hook. The final incremental
archive equals the complete rebuilt candidate byte-for-byte. A subsequent
normal USB status query also succeeds.

At this checkpoint, the complete manager-corrected image ran from RAM on preset
`04B FX:Soft Filter`. The canonical local HXF at
`build/HX_Stomp_v3.80.0_HXtra.hxf` then had MD5
`6c37466f5f5519a58785260ecd97950c`; the old failing HXF remains preserved
in the diagnostic directory. No permanent firmware write has occurred.
The user confirmed that the knobs and buttons respond normally with the
complete corrected build running. Atmosphere audio/gesture/resource acceptance
remains separate from these successful boot, USB and front-panel checks.

The expanded offline run passes **783 tests, 2 skipped in 129.02 seconds**; the
skips are missing Stomp XL and HX Effects fixtures. All thirteen recorded NAM
file fingerprints match, and only archive Entry 0 differs from the previous
candidate. No DSP/model/archive data change was needed for this fix.

A passing boot/USB check does not establish complete gesture or audio correctness.
Prepared images and their exact enabled controls are recorded in ignored
`build/ram-probes/incremental-images.json` (original) and
`build/ram-probes/fixed-incremental-images.json` (corrected).

## Local artifacts and recovery

The failing HXF and report are preserved under `build/ram-probes/`. The current
edit buffer was backed up before testing. The updater supplied by the user was
moved to `build/vendor/Line 6 Updater 1.28.dmg`; it has not flashed the device.
The preflight record is `build/atmosphere-flash-preflight-2026-11-17.json`.

For implementation and the previous offline checks, see
[the placement note](microlooper-code-placement.md),
[M4 routing evidence](microlooper-switch.md) and
[integration history](microlooper-integration.md).

## First actual Atmosphere block loaded

**[verified on unit, 2026-11-17]** Backed up the current edit buffer to
`build/pre-micro-audio-test-edit-buffer-2026-11-17.json` and `.bin`, then
loaded a temporary one-block preset into the edit buffer without saving.
It contains enabled model 380, native kind 8, on path A slot 0. Parameters
read back as Tape, Length 0.5, Modify 0.75, Clock 1.0, Mix 0.5, Play false
and Overdub false. FS1 (left) has the sole bypass assignment, targeting
block ID 1 with the label Atmosphere. Normal editor USB queries continue
to succeed after construction. Stored preset 04B is not overwritten.

The unit normalizes the primary parameter record to count 8 / direct count 7,
appending an extra false value after the seven declared controls. The initial
host equality check flagged this shape difference; explicit readback verified
that model, enabled state, all seven defaults and the FS1 assignment match.
The native readback is preserved as the reloadable test-preset artifact in
`build/ram-probes/micro-audio-test.bin` and `.json`. The additional value's
semantics are not established by this observation.

Audible output, tap capture and held overdub await the user's listening test.
No flash, preset save or persistent write was performed.

## Tap reaches the controller but native writes reject the descriptor

The user reported no audible capture while live guitar remains audible. A
RAM-only M4 diagnostic on reserved editor command `0x51` observes mode 0,
FS1 function 2, a kind-1 assignment to block 1, native model 380, and one
active controller route. A controlled tap changes desired Play to 1, but
both transport dirty bits remain set and the native writer returns **-3**.
Thus eligibility and gesture detection are established for this test; the
first transport failure is downstream of them.

**[verified native trace and on-unit one-variable comparison]** Descriptor
byte +8 was 1. Native `0x28e07f80` inverts it before graph getter `0x28dfbb0c`.
Flag 1 selects special fields bounded by node +0x60; flag 0 selects effect
controls bounded by +0x64. Transport indices 5/6 are ordinary controls. A
diagnostic that omits only the flag-1 store makes writes return 0 and clears
the dirty bits. The source writer now retains the already-zero flag, keeps
packed bool type 1, and advances the controller manifest to version 3.

A regression executes the actual outer setter, ordinary dispatcher, native
preflight and graph getter against an effect with one special field and seven
controls. Both transport cases fail with -3 before the correction and pass
afterward. All 84 M4/lifecycle tests pass. Native evidence is retained in
`build/ram-probes/transport-parameter-space-analysis.snapshot`, including
`ev_fbe25efa7fddef77e6f0f7d47561aeaa7f303e954d1e60024d125d27dd29d00a`
and `ev_5a5403317aed197f26ab0c2fbc1712bbb4bc3b86f6120657ac5f1b9d660f1869`.

With the corrected flag, a switch/transport timeline records taps toggling
Play without dirty writes; native preset readback also shows Play true.
The user still hears only live guitar. Audible capture remains unresolved;
control acceptance alone does not qualify the DSP audio path. The clean rebuilt
transport-fix HXF has MD5 `03d0f6d4c71f11b95a5290ad60934c12`.

The next ignored diagnostic temporarily replaces only Atmosphere's core with a dry
context sampler and reuses the existing GR frame sender. It preserves native
stereo bridge code, model allocations and NAM bytes. Encoded simulation checks
dry stereo output and frame payload/guards before hardware use. This probe is
not a runnable looper and must not be installed as production firmware.

## Native DSP instance descriptor is in DDR2

**[verified on unit through guarded SPI/USB telemetry]** The dry context probe
receives private I0 `0x96fb9`, native input/output `0x967de`, call record I3
`0xb2e10`, and instance descriptor candidate `0x31122f`. The latter is in the
pinned native Heap6 DDR2 reservation, outside the bridge's former internal-only
instance guard. The production bridge consequently supplies ring begin/end 0
and the audio core takes its dry error path. This is a second defect independent
of the M4 transport descriptor flag.

A one-variable diagnostic permits the complete eight-word descriptor within
Heap6 `[0x30d100,0x324497)` while retaining internal call-record/descriptor checks.
Its telemetry then reports ring `[0x328c00,0x334780)`: exactly 48,000 words.
The original native call record and stereo bridge remain in use. Raw telemetry
is preserved in `build/ram-probes/dsp-context-first.json` and
`dsp-context-external-descriptor.json`. Probe initialization/error samples are
not evidence of the original audio core's state; this is explicitly a dry probe.

The encoded bridge regression reproduces ring 0 before the correction for
Heap6 start, the observed descriptor and the last complete eight-word descriptor.
The bridge now derives its bounded Heap6 check from the same constants as the
linker's native-heap byte guards. Before-start and crossing-end pointers remain
rejected before dereference. A two-instruction scalar-reset reduction offsets
the larger bridge, preserving the full NAM2 + GR + metronome build.

The complete corrected audio HXF is
`build/ram-probes/micro-capture-fixed.hxf`, MD5
`80fae2525aacd4b9e46ae0f09930f1b1`. Core/bridge/callback instruction counts
are 1091/106/33; Entry 2 is 524,284 bytes, leaving 4 bytes. Every archive
integrity check passes and all thirteen NAM fingerprints remain unchanged.
The full audio core replaces the dry probe for the next listening test.

## Audible capture confirmed after both tap fixes

**[verified on unit]** The clean complete build
`80fae2525aacd4b9e46ae0f09930f1b1`, with the actual audio core restored and
no temporary telemetry probes, passes RAM boot and USB checks. The same
unsaved Atmosphere-only preset loads and reads back correctly. The user confirms:
**a left-switch tap captures audio and the loop repeats after playing stops.**
This establishes Tape tap capture for the tested mono-guitar input; it does
not qualify held overdub, other modes, stereo separation or resource/timing
limits. The canonical `build/HX_Stomp_v3.80.0_HXtra.hxf` now contains this
image; older failing checkpoints remain under `build/ram-probes/`.

Final regression run: **791 passed, 2 skipped in 131.89 seconds**. The two
skips are absent Stomp XL and HX Effects fixtures. Documentation checks pass,
all thirteen recorded NAM fingerprints match, and no permanent flash or
preset save has occurred. Temporary M4/DSP probes remain only in explicitly
ignored diagnostic artifacts; the running clean build contains neither.

## Atmosphere naming checkpoint

Renamed the display/block name, browser folder and footswitch label to
**Atmosphere**, and the internal model text name to `HD2_AtmosphereStereo`.
Numeric model ID **380**, primitive **0x012e**, parameter/state identities and
controls remain unchanged. Current source documentation and build messages use
the new name; module filenames and technical micro-looper identifiers remain
descriptive implementation names. Historical raw firmware/diagnostic artifacts
retain the names originally recorded.

The renamed HXF MD5 is `3213fe0d81e632d80bf4fe7e4bf36373`. Only Entries 0
and 3 differ from the capture-verified checkpoint; Entry 2 DSP bytes are
identical. Existing model/declaration/linker/docs checks: **72 passed in 13.81
seconds**. All thirteen NAM fingerprints remain unchanged. The renamed image
passes RAM boot/USB checks. Native readback confirms model 380 and FS1 label
Atmosphere, with the user's Length/Modify/Clock/Mix settings restored. Transport
starts low after reload, so the previous RAM capture is intentionally empty.
The canonical local HXF now contains this image; no permanent flash occurred.

## Fork publication checkpoint

The Atmosphere checkpoint is published on the `atmosphere` branch of
`breakall/hxtra`, retaining tested baseline commit
`8004c8e8d032046306374b006a4693bec3bb4cab`. Later upstream changes are not
silently mixed into this hardware-tested checkpoint. Browser source packaging
includes the shared declaration and placement modules, and fork CI includes
the Atmosphere branch. Firmware images, updater assets, raw device captures
and preset backups remain excluded from Git.

Full default repository suite with the Stomp fixture and pinned RAM-loader
toolchain: **2,067 passed, 73 skipped in 394.80 seconds**. The skipped cases
are the separately selected upstream NAM suite and unavailable XL/Effects
fixtures. Hardware qualification remains as recorded above.

## Hardware DSP budget measurement

**[verified on unit, 2026-11-17]** The upstream merge through `2c1685f`, local
commit `fb2d42c`, passes RAM boot and native USB readback. In the clean merged
image `80fdde920530867e7ec4e43412231bc6`, the user confirms Tape capture/repeat,
held overdub and release without stopping, return to listening and replacement
capture, Mix endpoints and blend, and the requested Stretch/Modify/return-mode
check. These are listening checks, not stereo-isolation or timing certification.

The 7500 cost displayed as 75 and filled the native admission allowance even
with Atmosphere alone. It was a deliberate isolation value, not measured CPU use.
The DSP meter displays the declared model-table charge; it is not a profiler.

**[verified offline and on unit]** A temporary diagnostic replaces the existing
GR program in its existing 594-instruction PM allocation and uses its existing
336-word DM allocation for a timer and frame export. The Atmosphere process
registry points to that timer, which calls the exact linked production planar
bridge/core in DDR2. All external Atmosphere instructions, native instance
allocations, model graphs and NAM bytes remain unchanged. Other GR-wrapped cores
forward directly to native routines in this diagnostic. It is not a GR-meter
qualification. Encoded execution checks validate the timer, original bridge/core,
muted output and coherent telemetry before RAM loading.

`EMUCLK` is sampled immediately before and after the bridge call. The delta
includes call/timestamp overhead and interruptions during the call; no optimistic
overhead subtraction is made. The start-to-start interval is a median 150,000
cycles per 16-frame block. An automatic 320-case schedule varies all modes,
eight Modify zones, four Length values including a very short splice, Overdub,
and five clock settings, with alternating stereo test input and silence.
The first 256 cases exercise the fastest clock; 64 additional cases exercise
the four slower clocks. The timer retains each case's and the entire run's
maximum across all calls, including calls between USB readbacks. The original
controller is not used to drive this synthetic transport test.

| Mode | Largest observed call, cycles | Fraction of 150,000-cycle interval |
| --- | ---: | ---: |
| Envelope | 66,021 | 44.0% |
| Tape | 60,824 | 40.5% |
| Stretch | 104,689 | 69.8% |

The run reached 329,824 calls and produced 1,845 coherent host snapshots.
Sampled start-to-start intervals ranged from 148,506 to 152,370 cycles; no
stretched callback interval was observed in those snapshots. This is not an
audio dropout test. A matched baseline calls only a return stub, outside which
all diagnostics/graph operations remain present: 206 snapshots show 78.48%
median native idle (21.52% total load), and the timed stub's median is 11 cycles.
Audio-state fields are undefined in that baseline because the audio core does
not initialize them; they are excluded from its validation.

**[verified on unit: candidate coexistence]** A 7200-unit candidate admitted
Parametric EQ Stereo (model135, 252 units) and Volume Mono (model261, 35 units):
7487 declared block units in total, below the native 7500 allowance. The same
automatic sweep reached 329,823 calls, exported 1,842 coherent snapshots, and
measured a maximum 104,680-cycle Atmosphere call. Sampled intervals were
148,034..152,012 cycles, median 150,000. The unit remained responsive. No
permanent preset or firmware write occurred.

**[experimental budget decision]** Use 7200 units (72%) for this implementation,
rounding the 69.8% observed maximum upward with approximately 2.2 percentage
points of additional per-effect allowance, alongside the native admission
margin. Only 300 units remain for other blocks. This is deliberately based on
the most demanding mode, not Tape's typical or reduced-clock load. It does not
admit a simultaneous NAM block. Substantially lower charges need performance
work and new hardware measurements, not just a cheaper model-table number.

Limitations: this schedule is not an exhaustive upper bound, it does not test
every arbitrary neighboring effect or external-memory contention pattern, and
muted synthetic output does not establish audio cleanliness at the admission
boundary. Long soak, stereo qualification and the remaining native lifecycle
acceptance checks still apply. Generic build reports do not attach this local
timing evidence automatically.

Ignored local artifacts are `build/ram-probes/atmosphere_timing.py` and
`collect_atmosphere_timing.py`, the generated diagnostic images/assembly,
`atmosphere-chip-timing.json`, `atmosphere-chip-baseline.json`,
`atmosphere-chip-neighbors.json`, and `atmosphere-timing-summary.json`.
The pre-profiling edit buffer is backed up as `pre-atmosphere-timing.bin/.json`.
The clean 7200-unit HXF is `4a9e9ea3d787c765f9c0d48c683b77b8`; only Entry0
differs from the 7500-unit clean merged image. The full DSP program and all
model/graph entries are byte-identical; DSP partition headroom remains 40 bytes.

**[verified on unit: clean restore]** The first restore attempt failed to
enumerate the temporary RAM loader, before the clean image was uploaded. The
user power-cycled to the normal installed firmware. The retry boots the clean
7200-unit image successfully, normal editor USB responds, and native readback
confirms the original Atmosphere-only edit buffer, all controls and footswitch
assignments restored. The generated profiling code is absent. The loop is empty
after restart. Targeted model/admission/layout/docs checks: **38 passed in
0.99 seconds**. No permanent firmware or preset write, commit or push was made
for this timing task.

## Internal hot-code optimization

**[verified offline and on unit, 2026-11-17]** Delegated work established a
fast final-image verifier, traced the stock loopers and official ADI cache
documentation, and produced exact compute candidates. The orchestrator built
and verified each candidate before serialized RAM-only hardware comparisons.
The [stock-looper research](atmosphere-stock-looper-optimization.md) shows
internal native processing and a 32-entry external instruction cache. Live
`MODE2=0x42000020` has CADIS, EXTCADIS and CAFRZ clear: external caching was
enabled, not frozen or accidentally disabled. Cache capacity and repeated
external fetches, rather than a disabled-cache setting, motivated relocation.

The production [split planner](../../../tools/sharc/microlooper_split.py)
derives the existing free interval after unchanged NAM/GR and before the
reserved metronome/cold-code region. It reserves those neighbors conservatively
even when optional features are absent. NAM2 has room for the sample loop and
helpers; NAM3 has room for wrap/read/interpolation/reconstruction helpers.
It checks existing loader aliases and NAM runtime claims before using either
region. No NAM code, slot state or capacity is moved or reduced.

The [compute changes](atmosphere-compute-optimization.md) calculate invariant
geometry once per callback, keep interpolation values in registers, and take
exact common-case wrap paths. A final helper extraction moves the repeated
reconstruction/mix-smoothing work into the same internal region without changing
operation order. The final core SHA-256 is
`a349ebf122f6849d5afa92ae7364a66a47d2589c491e125281af7d24aeebc253`:
1049 instructions, versus1091 originally. NAM2 splits into402 external +648
internal core instructions; NAM3 into861 external +188 internal. Private
allocation remains199DM, zeroPM and48,000 SDRAM words per instance.

**[verified offline: candidate gates]**
[`verify_atmosphere_candidate.py`](../../../tools/verify_atmosphere_candidate.py)
checks actual image/container integrity, all partition bounds, model/resource
and callback binding, emitted executable sections, final physical16 aliases,
unchanged NAM and present GR/metronome neighbors, native heap setup, and bounded
original native initialization/allocation execution. Its full gate executes
the actual final code against an independent compiled C++ oracle, with writes
restricted to the declared instance and buffers. Allocation-only checks take
about0.7 seconds; full checks about2.7 seconds locally. Hardware timing and audio
qualification remain separate. An independent review demonstrated an initially
missed write through a different address-space alias into NAM cold code; final
physical replay and a regression now reject it. The32 gate regressions also
exercise graph corruption, callbacks writing beyond private state, bad
reservation reports, heap/GR/click aliases and changed output instructions.

**[verified on unit: controlled comparisons]** All timings below use the same
320-case automatic schedule, 16 stereo frames/call and150,000-cycle median
start interval. The diagnostics are muted and keep per-case and whole-run
maxima between USB samples; these are sampled measurements, not exhaustive
upper bounds or listening tests.

| Candidate | Largest call, cycles | Fraction of audio-block interval |
| --- | ---: | ---: |
| Original all-external implementation | 104,689 | 69.8% |
| Original algorithm, internal sample loop | 27,856 | 18.6% |
| Original algorithm, internal wrap/read helpers | 50,231 | 33.5% |
| Exact compute changes + internal sample loop | 20,915 | 13.9% |
| Exact compute changes + internal helpers | 43,272 | 28.8% |
| Final reconstruction refinement, helper layout | 42,135 | 28.1% |
| Final source, sample-loop layout with stock neighbors | 21,013 | 14.0% |

The last test adds Atmosphere in the free A7 position of the user's backed-up
Microcosmos edit buffer. Ordinary stock blocks declare4104 units; its specialized
kind22 looper (model505) adds528 even while bypassed. Atmosphere2000 brings the
total to6632 of7500 block units. Clean-firmware native readback confirms8132
including the fixed1500 base, and retains every block. The run reaches the end of
the schedule with1911 coherent snapshots, no core error flag, normal callback
cadence and responsive USB. The maximum Atmosphere call is21,013 cycles. This
is shared-load timing evidence, not an audio dropout or full NAM-capture test.

**[experimental budget decision]** Charge2000 units (20%) for the GR/NAM2
sample-loop build, leaving55% of the block allowance for actual neighboring
effects. Charge3200 (32%) for the smaller helper layout, leaving43%. The final
NAM3 image's executable bytes and addresses are identical to the measured
helper-layout candidate; complete NAM3 hardware acceptance remains pending.
The budgets include headroom above the largest observed call and cover all
modes. They supersede the72% charge for the former all-external implementation.
They do not change stored captures or the baseline NAM3/NAM2 slot capacities.

The clean full-feature GR HXF is `c5f45d341bf2a04e47f2cd0d98e691e6`, with280
Entry2 bytes free. The clean NAM3 HXF is `3f8635abe255d00f7c3ac80b0ff65195`,
with3964 bytes free. Both actual built images pass the independent emitted-byte
gate with zero oracle error. Canonical output selects the GR/2000-unit image.
Final full repository regression: **2122 passed,73 skipped in420.66 seconds**;
the usual skips are the separately selected upstream NAM suite and absent
XL/Effects fixtures. Additional candidate checks include153 audio/bridge tests,
the flat and split reconstruction tests, and20,224 bit-identical frames plus
1024 direct reconstruction cases comparing complete memory/register/status
state. All timing images, raw records and preset backups remain ignored local
artifacts under `build/optimization-probes/`; no firmware image is published.

**[verified on unit: clean optimized restore]** The canonical GR/2000-unit image
boots successfully from RAM and normal editor USB responds. A clean-image mixed
preset insertion/removal confirms the native cost above. The original selected
preset8, `FX:Microcosmos`, is then restored from the pre-test backup; block
settings and footswitch assignments read back unchanged. No save or permanent
firmware write is sent. The clean image contains no profiling code. Changes
remain local for review; this optimization task does not create a commit or push.

## Native mono implementation

2026-11-17. This continuation adds a true mono effect alongside the existing
stereo identity. Earlier images and the 199-word bridge above are historical.

**[verified offline: model identity and allocation]** Stereo remains preset 380,
primitive `0x012e`, registry `0x200058`, internal name `HD2_AtmosphereStereo`.
Mono uses unused preset 381, primitive `0x0100`, registry `0x2000a0`, name
`HD2_AtmosphereMono`, displayed as **Atmosphere Mono**. Both use 163 private DM
words and zero private PM words. Mono allocates 24,000 SDRAM words; stereo
allocates 48,000. Both retain 24,000 frames, so duration and clock behavior match.
Native constructor replay and final-image verification check both allocations,
the distinct initializers, and shared processing/control entries. NAM stays 555;
no NAM code, slot layout or runtime limit changes.

**[verified offline: persisted identity correction]** The timing prototype used
ID 147, which stock firmware leaves unregistered. Repository history and
`README.md` show that earlier NAM releases persisted that ID with an amp-shaped
record. The final mono model instead uses 381, also unregistered in stock, so
those records cannot resolve to an unrelated delay. Old 147/148 NAM support is
not changed. This registration-only correction leaves all measured DSP code
and history allocation unchanged.

**[verified offline: one audio channel]** The common core consumes native planar
buffers directly. Private word 14 is initialized to 1 for mono or 2 for stereo;
only native initialization owns it. Mono reads/writes 16 audio words and advances
one history word per frame. It skips the right-channel capture, interpolation,
crossfade and overdub arithmetic. Both widths share control/timing calculations.
The conversion buffer is removed; bridge spills occupy 153..162. The core is 1085
instructions, bridge 66 and init/control 37: 1188 total, unchanged from the preceding
stereo-only implementation. Native model metadata provides mono routing; no
custom input summing is added.

**[verified offline: emitted image and independent reference]** The final gate
executes both initializers and controls through the stock C caller and replays
native member allocation. It executes actual final-image processing bytes for
seven transition/overdub cases per width, 3136 frames each, with zero observed
sample error against the independent C++ reference. Strict read/write guards
cover the 16-word mono buffers, 24,000-word history and 163-word private state;
negative tests reject stereo-sized mono buffers, wrong init width and misbound
registry/graph declarations. Independent cross-reviews found no actionable
defects in DSP, native lifecycle/model handling or linker composition.

**[verified on unit: mono width and history]** RAM timing images retain the exact
external and internal Atmosphere executable bytes and addresses. The diagnostic
wraps the shared native processing entry, supplies deterministic input, mutes
output after the measured span, and reuses existing compressor-meter storage.
Hardware telemetry reports channel count 1 and ring extent 24,000 on every sampled
mono call. MODE2 is `0x42000020`; cache remains enabled. The callback interval is
approximately 150,000 cycles for 16 frames, as before. The 320-case sweep includes
all modes, eight Modify zones, four Length choices, overdub, fastest clock and
four reduced clocks. Peaks include all callbacks, not only host snapshots.

Mono alone: 1881 snapshots, peak 19,774 cycles (**13.18%**). With the seven stock
Microcosmos blocks: 1746 snapshots, peak 19,689 cycles (**13.13%**). The latter
includes the bypassed native looper and preserves the original effects/settings.
Raw evidence is ignored locally under
`build/optimization-probes/mono-shared-checked-chip-timing.json` and
`mono-shared-mixed-chip-timing.json`.

**[verified on unit: shared stereo comparison]** The same mixed-preset sweep
records 1759 snapshots, channel count 2, ring extent 48,000, and peak 24,184 cycles
(**16.12%**) in `stereo-shared-mixed-chip-timing.json`. Mono's mixed-preset peak is
18.6% lower; its isolated maximum is 18.2% below this stereo maximum. Sharing the
core adds channel branches to stereo, whose earlier dedicated implementation
peaked at 14.0%. The new stereo path remains below the existing 20% native charge.
Use 1700 units (**17%**) for mono and 2000 (**20%**) for stereo in this measured
compressor-meter/NAM2 configuration. These are conservative sampled budgets,
not exhaustive timing qualification. The NAM3 helper-only placement has offline
fit/behavior coverage, but this shared kernel has not been timed in that profile;
the earlier stereo-only 32% result does not qualify it.

**[verified offline: final clean artifact]** The canonical
`build/HX_Stomp_v3.80.0_HXtra.hxf` has MD5
`ba4e9a12c9b6dab551be6326b2f70c94`, with mono 1700 and stereo 2000 native charges.
Every non-M4 archive entry, including the complete DSP boot entry, is identical
to the verified candidate used for timing. The complete image passes the same
emitted-byte allocation/audio gate for both widths. Entry 2 is 524,064 bytes,
leaving 224 below its partition limit. There is no profiling code in this image.
Kernel source SHA-256 is
`857a23bdd3b2dec1a4fe4e13f723e4a6a61ddb6e669b46e2b21f63d2b0a43515`.

**[verified offline: measurement harness correction]** A first attempt to repeat
the sweep after a graph change restarted the diagnostic sequence number. The M4
readback correctly discarded the new lower sequence until it caught up; the
unit remained responsive. The corrected probe keeps stream sequence monotonic
and stores a separate graph-relative sweep origin. This affects diagnostic
instrumentation only. That incomplete attempt is retained separately and is not
used as the final timing evidence.

**[verified offline: regression]** The full suite ran 2254 passing tests and 73
expected skips in 438.87 seconds; one loader reproducibility check failed because
the shell selected a system ARM compiler missing `nano.specs`. The isolated check
passes in 0.30 seconds with the project's pinned compiler first on PATH. Thus all
2255 selected tests pass with the correct toolchain. Skips are the missing XL/
Effects fixtures and separately selected upstream NAM suites. The initial
sandboxed launch also failed in Unicorn's native JIT setup; the actual full run
used the required native execution permissions. No code was changed to bypass
either environment failure.

After moving the final mono identity to 381, native/model/helper checks pass
199 tests in 11.53 seconds and both-profile linker/build/final-byte checks pass
96 tests in 45.15 seconds. The canonical 381 image passes the full emitted-audio
and allocation gate with archive SHA-256
`0541567e4c180d0cf1b03dce945c9f7ef7695f90bc7f30469235feef6720631c`.

**[verified on unit: current handoff impediment]** The attempt to replace the
stereo timing diagnostic with the clean image failed in the temporary RAM
loader's DFU reconnect, before image upload. Neither normal USB, DFU nor loader
USB enumerated afterward. A power cycle to the installed firmware was requested;
clean-image RAM boot and final edit-buffer setup remain pending that recovery.
This is not a measured looper failure and no permanent firmware write occurred.
