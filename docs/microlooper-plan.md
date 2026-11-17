# Atmosphere implementation plan

Status, 2026-11-17: Atmosphere's shared declaration and external ISA placement are
implemented and verified offline. The current build preserves baseline NAM3,
or NAM2 with GR, without changing NAM sources or fixed storage. The earlier
fixed-NAM1 results below remain historical evidence. Incremental hardware RAM
tests isolated and corrected a UI-context/assignment-manager mix-up; the full
build now passes boot/USB checks. Subsequent transport-flag and native-DDR2
descriptor corrections enable on-unit Tape tap capture. Held overdub, other
modes, stereo separation and real-time timing/resource qualification remain
outstanding. See the
[hardware log](research/features/microlooper-hardware-log.md). Current evidence:
[external placement](research/features/microlooper-code-placement.md),
[integration](research/features/microlooper-integration.md),
[feasibility](research/features/microlooper.md),
[preset resources](research/features/microlooper-preset-resources.md).
Target: HX Stomp stock 3.80.0; baseline HXtra commit
`8004c8e8d032046306374b006a4693bec3bb4cab`. Existing unrelated local changes
are preserved. No commit, push, dependency installation or hardware flashing
was performed.

## Accepted requirements

- A build-time selectable stereo micro-looper, inserted into ordinary presets from the device model browser. Tape, Envelope and Stretch retain Atmosphere behavior. No reverb, delay, Slip, wet freeze or wet recapture path.
- One assigned switch: tap on release captures recent input or resumes listening; hold for 400 ms enables overdub until release, only during playback. A hold must never also execute the tap action. The block stays enabled while listening; Capture is separate from bypass.
- Preserve 24,000 stereo float history frames, stepped 48/24/12/6/3 kHz processing, interpolation, corrected splices, clock/pitch behavior, independent chronological overdub head and existing mix/transition behavior.
- No special code, singleton storage, instance-count rejection, warnings or UI around assuming one instance. State and audio storage remain private to each instance. Normal firmware resource admission applies.
- HX Edit compatibility is deferred. Use a stable unused model identity, not a replacement for a stock effect. Do not consume NAM's ID555 or metronome's ID181.
- Including Atmosphere in the firmware must not reduce NAM capacity in presets without a Atmosphere block, relative to the equivalent HXtra build without Atmosphere. Resource admission must reflect blocks actually present in the preset and use the normal native browser availability result. Any reduced simultaneous NAM capacity must follow actual resource consumption, with capacity returned when the consuming block is removed or replaced. Stored captures and User IR slots are unaffected. Do not silently remove GR or the metronome. Reject actual binary overlap/size errors. This supersedes the earlier permission for a firmware-wide NAM1 profile.
- Declare a measured, conservative DSP cost. The native model browser must gray out the micro-looper when the current preset's remaining DSP is insufficient. This is a release acceptance criterion, not a new instance-count rule.
- Captures are RAM-only. Preset reload starts empty/listening. No promise of capture persistence across graph reconstruction. Snapshot recall must not synthesize a capture/overdub action.

## Module interfaces and ownership

The reference audio module owns capture state, one audio ring, modes, clock and mix. Its interface is Init/Configure/SetPlaying/SetOverdub/ProcessStereo. Repeated state writes are idempotent; capture happens once at a Listen-to-Play transition. Empty history is safe; no synchronous large memory clearing occurs in an audio callback. The firmware DSP adapter must implement this same behavior at 16-sample quantum boundaries with instance-local state.

The gesture module accepts pressed/released levels and elapsed time, emits tap/listen/capture and overdub transitions, and owns the 400 ms decision. Explicit time units prevent a host-sample/16-sample-block/1ms-tick mismatch. The M4 adapter must coordinate with the existing long-press handler rather than claim its entry twice.

The build module owns the permanent ID, parameter slot/types/defaults, stereo host registration, instance resource declarations, code placement and patch order. No audio algorithm lives in the model patcher. Probe code and production code are distinct; a diagnostic passthrough must never be offered as a working micro-looper.

## Parallel work packages

| Package | Files owned | Dependencies | Deliverable and acceptance |
|---|---|---|---|
| A: reference engine | `tools/microlooper/reference.h`, `tests/microlooper_reference.cpp`, `tests/test_microlooper_reference.py` | Atmosphere source snapshot | Looper-only C++ engine, no wet effects/hardware; compiled sanitizer tests for source parity and transport, stereo isolation, clock, all modes, overdub, splice and abrupt changes. |
| B: gesture state machine | `src/m4/microlooper_gesture.s`, `tests/test_microlooper_gesture.py` | accepted one-switch semantics; existing M4 test harness | Cortex-M4 gesture routine with caller-owned state, explicit microsecond timestamps, level outputs and tap pulse; Unicorn tests for release tap, 400ms boundary, hold/no tap, listening hold, duplicate levels, wraparound and independent state. |
| C: DSP diagnostic and layout | `src/sharc/microlooper_probe.asm`, `tools/sharc/microlooper.py`, `tests/test_microlooper_probe.py` | existing sasm/ssim and instance descriptors | Minimal assembled diagnostic with explicit documented calling contract, per-instance counters and bounded SDRAM ring access, stereo test vectors; current layout measurements and hard code/image fit accounting. Unknown stereo host ABI must remain marked unverified until hardware probe. |
| D: integration (primary agent) | schema/build patcher, `build.py`, shared hooks, docs, web sources | A/B/C contracts | Integrate only after independently tested modules; primary agent owns changes to shared files to avoid conflicts. |

A, B and C run in parallel. Agents may inspect all files but edit only assigned paths; no edits to shared build files, stock firmware or Atmosphere. They must report tests, assumptions and unresolved ABI details. No nested agents needed. The primary agent reviews and joins their interfaces before advancing dependent tasks.

## Staged execution and stop conditions

### Stage 1: executable reference, gestures and diagnostic

- [x] A extracted reference engine and sanitizer tests.
- [x] B assembly gesture module and M4 tests.
- [x] C SHARC diagnostic, simulator tests and current resource report.
- [x] Primary agent reviews contracts, tests all three together and records exact unverified hardware assumptions.

Stage 1 can complete offline. Do not expose the new effect in release/browser builds here.

### Stage 2: experimental model and RAM probe

Register an opt-in development-only stereo model using the existing 2-in/2-out FX host. Reserve model ID 380 (`HD2_AtmosphereStereo`) and primitive `0x012e` at registry `0x200058`, checked unused by read-only stock parsing on 2026-11-14; recheck every input image rather than relying on that observation. NAM uses 555 and metronome 181; the chosen identity does not replace them or a stock effect. Clone the stereo host `L6SPB_AcousGtrSimStereo` with ordinary stereo Delay browser metadata as the initial category candidate. Define Mode, Length, Modify, Clock, Mix and transient transport inputs. Standard browser category/icon avoids the metronome's repurposed Unknown category. Use host-allocated 48,000-word SDRAM history plus explicit small state/scratch, with valid-frame accounting. New instances start empty and cannot read prior contents.

First build a distinct diagnostic image only: verify input/output channel pointers, in-place input preservation, instance descriptors, SDRAM bounds, callback/input delivery during bypass and safe initialization. Instrument instance identity/init count/capture epoch and counters, readable using existing telemetry mechanisms. Build-size and overlap checks must pass, and no unmeasured probe DSP cost may be advertised as production cost. Build to the repository's canonical output and identify the MD5. No installation/flash; a hardware RAM run requires a connected HX Stomp and an explicitly identified experiment.

Gate: stereo ABI and large-ring ownership proven on hardware. If unavailable, offline implementation may proceed against the documented provisional adapter, but no hardware-ready claim or release enablement is permitted.

### Stage 3: SHARC audio port and profile selection

Port incrementally: recording and capture, Tape, Envelope, Stretch, overdub, splices, clock/reconstruction and mix/transition smoothing. Render deterministic input/control event vectors through A and assembled SHARC simulator code. Compare state transitions exactly, sample output with an explicit justified float tolerance, and preserve registers/MODE1. Add targeted regressions for abrupt Envelope length shrink rather than blindly port a suspected negative-fade edge case.

Measure actual section sizes and boot-stream growth, then qualify a memory layout that preserves baseline NAM capacity in presets without Atmosphere. Selecting NAM1 globally when Atmosphere is included no longer satisfies the requirements. Changing admission counts alone cannot recover memory occupied by resident code; prove real non-overlapping storage and executable placement first. No arbitrary global ring addresses or unbounded DMA waits. Start with direct SDRAM access; add shared EP0 staging only if measured necessary and safe alongside NAM. External code execution is a separate path requiring explicit patcher/simulator/hardware validation, not assumed available space.

Gate: complete algorithms pass differential tests and build fits without dropping approved features. If native memory limits cannot fit it, report the exact deficit before broadening scope.

### Stage 4: switch and lifecycle integration

Route the assigned switch to B without ordinary bypass toggling or competing 1-second long-press actions. Coordinate with the existing long-press handler. Preserve other blocks' footswitch behavior. Use idempotent transport state delivery, with initialization and snapshot handling that cannot turn restored Play/Overdub values into fresh actions. Validate tap/hold/release and rapid events, switch reassignment, model deletion, block moves, graph reconstruction and preset reload. Tests must use actual hooked M4 paths as well as isolated gesture tests. Multiple instantiated blocks must not alias memory; there is no bespoke instance-count enforcement or warning.

Gate: RAM hardware tests establish footswitch routing and capture continuity. Capture/Overdub controls must not silently depend on bypass DSP scheduling.

### Stage 5: native admission, release and validation

Profile real kernel time using EMUCLK/actual DSP load: each mode, fastest signed rates, seam reads, simultaneous overdub, clock/parameter changes and expensive stock/NAM neighbors. Account for initialization spikes and memory stalls; simulator instruction counts and Hothouse CPU readings are not hardware percentages. Choose a conservative declared cost from worst-case measurements. Verify native gray-out when preset DSP is insufficient, insertion when sufficient, and refund on removal, including snapshot/loaded presets. Existing admission compares `current total + new cost - replaced block cost <= 9000`, with an initial declared total of 1500; use that path without a replacement browser hook. Test immediately below/at/above the limit and replacement of a costly block, not only insertion into an empty slot. See [DSP cost research](research/m4/dsp-cost.md). No custom singleton restriction or warning.

Update the CLI build switch, browser worker sources/steps, M4 release cache if needed, checksum pins, feature guide, research findings and user controls. Add default-off experimental flag until all hardware acceptance gates pass; publish only through the existing release workflow when requested. Run affected suites, full non-NAM and NAM groups, stock-firmware builds, build-profile matrix and browser parity. Existing features must remain green. Final report states hardware-verified versus offline-only behavior, exact image MD5, declared cost and NAM profile.

## Execution log

- 2026-11-14: plan saved; A/B/C dispatched in parallel. No production feature or hardware change yet.

- 2026-11-14: A/B/C completed and reviewed. Combined new-module, M4 harness, SHARC simulator and documentation checks: **97 passed in 2.72 s**. Command: `.venv/bin/python -m pytest tests/test_microlooper_reference.py tests/test_microlooper_gesture.py tests/test_microlooper_probe.py tests/test_ssim.py tests/test_m4asm.py tests/test_m4emu.py tests/test_docs.py -q --tb=short` (outside sandbox for native Unicorn/sanitizer execution).
- A: 2,088,960 scalar output samples compared to pinned Atmosphere source over 120 mode/clock/speed combinations with overdub and partial recapture. Maximum measured difference 1.49e-8, accepted absolute tolerance 2e-7; standalone original-source golden samples also pass. Abrupt Envelope LENGTH shrink was reproduced as a negative fade and corrected by wrapping the old head before fading the new slice. No wet effects carried over.
- B: real position-independent M4 gesture assembly passes 18 tests, including 400 ms boundaries, polling gaps, wraparound, release/no double action, independent state and register preservation. The firmware event handler is not hooked yet.
- C: real 116-instruction SHARC diagnostic passes 25 tests under its documented provisional interleaved ABI. It fits the current NAM3+metronome shared gap and all supported measured profiles. Its single code LDR block adds 708 bytes to the measured all-web baseline, leaving 2140 bytes below the current injection guard before registry/adapter additions. This is not a fit claim for the complete audio engine.
- Next: Stage 2 experimental model/instance adapter and a native stereo ABI RAM probe. The reference is desktop C++, not runnable HX Stomp audio firmware; no production block is registered, no micro-looper image was flashed, and native DSP menu graying remains a Stage 5 hardware acceptance test.

### Continuation: audio port and native integration

- The actual SHARC audio engine implements all three modes, stepped clock, capture/listen, overdub, corrected splices and mix. It uses 153 private DM words and a 48,000-word SDRAM history. Direct differential tests compare the encoded instructions to the C++ reference, including wrapped full captures and hardware reciprocal seeds.
- Independent review found cancellation error in quotient-based wrapping after a sharp length reduction and stale Overdub state crossing a capture transition. Both are fixed: bounded exact binary remainder reduction, and per-instance effective/previous Overdub levels. Fresh overdub requires a low-to-high level transition; ignored high while listening cannot become a new command. Native initialization must still force Play/Overdub off before the first processing call.
- `tools/patch_microlooper.py` registers the stereo model/graph and explicit native cost without replacing stock effects. It is a metadata library, not a runnable effect builder. Tests execute the actual firmware admission function at totals just below/at/above 9000 and verify cost-table integration. Structural test costs are not measured hardware load.
- `HX_NAM_SLOTS=1` now builds a single-slot NAM kernel. Its encoded audio/lifecycle/DMA checks pass against the reference; existing NAM2/NAM3 generated assembly remains unchanged. `patch_comp.dsp_place(lay)` and the resource tool account for the selected profile without silently removing GR or metronome.
- Opt-in `tools/sharc/ldr_compact.py` uses the manufacturer's documented ZERO_LDATA records for zero runs in injected internal data. Boot-memory replay tests compare the complete initialized data and preserve all instruction records, the boot kernel and FINAL_INIT. This tool is not enabled in default builds; hardware boot verification is still needed.
- Run `.venv/bin/python tools/sharc/microlooper.py --audio --compact-data --image build/HX_Stomp_v3.80.0_HXtra.hxf` for actual code-size/profile accounting. The Entry 2 guard is confirmed against the existing RAM-loader partition map: payload sectors 0x8803 through 0x8c03, 512 KiB excluding the sub-header. Native adapter growth must still be included.
- M4 assembly now has a tested native bool writer, selective bypass filtering that preserves ordinary blocks assigned to the same switch, a proven 100 Hz polling seam, and a caller-origin filter for external snapshot/control transport writes. Actual stock code is loaded from the user's firmware during tests. These hooks are not enabled: assignment ownership/epoch, initial graph delivery and complete event routing remain unresolved. See [native switch findings](research/features/microlooper-switch.md).
- Stereo graph evidence was corrected: ordinary stereo hosts and native stereo loopers both have root 0-in/2-out and processing members 2-in/2-out. That does not identify runtime audio pointer layout. The native context sampler records registers and candidate SDRAM bounds without dereferencing audio pointers. The prior HD500 investigation is a different firmware architecture and cannot prove this ABI.
- A read-only USB registry check found no connected HX Stomp. No hardware write, RAM run or flash was performed. The native stereo adapter and lifecycle observations remain the immediate hardware-dependent gates; no micro-looper HXF is offered for user testing yet.


### Regression checkpoint

- Full regression invocation split the existing marker groups: non-NAM **1354 passed, 5 failed, 2 skipped in 348.56 s**; NAM **71 passed in 138.95 s**. Total wall time including process overhead: **487.74 s (8 min 7.74 s)**.
- All five failures were integration issues and are corrected: the new research note was missing from the index; the unfinished rejecting feature was inadvertently discoverable by all-flags builds; the browser source list lacked both assembly files, also changing its cache key. Unfinished constants now live in `tools/microlooper_native.py`, outside feature discovery; no micro-looper build flag is advertised yet. Both assembly files are listed for browser cache parity. Existing tests were retained.
- Rerun of the entire documentation, web-build and TAP-color files: **66 passed in 4.95 s**. M4, gesture, feature engine and all-features regression group after the discovery fix: **197 passed in 7.36 s**. No failures remain from the full run; the entire suite was not repeated after these targeted corrections. XL/Effects firmware checks are skipped because those stock fixtures are unavailable.
- At the previous checkpoint, the audio core was **1191 instructions**, padded to 1192 / 7152 raw code bytes. The NAM1 + GR + metronome all-web baseline Entry 2 is 521408 bytes; opt-in data encoding saves 4604 bytes. Audio LDR plus registry would reach **524012 / 524288 bytes**, leaving **276 bytes before the native adapter**. This is a constrained projection, not a completed image fit or a runnable micro-looper build. The canonical baseline `build/HX_Stomp_v3.80.0_HXtra.hxf` contains NAM1 and existing features only; MD5 `fe3514a293b5c5d239ba7fa4ec6f79d8`.
- Remaining work: prove native stereo buffers and ownership; implement the native DSP bridge and initialization; complete shared switch routing and lifecycle invalidation; fit the final adapter; measure real DSP load and verify native menu graying; run RAM/hardware acceptance. No Stomp is connected and no firmware has been installed.


### Further native qualification

- Native candidate pricing now runs original cost lookup, replacement budget and preset-total recomputation in Unicorn, with the registered model's relocated table and no cost stubs. Insertion boundaries, costly-block replacement, removal/refund and non-mutating browsing pass. Model registration/admission group: **23 passed in 0.51 s**. These tests do not establish visible hardware menu graying or a measured declared cost.
- Model metadata now exposes only the five ordinary knobs while retaining both hidden transport inputs. Entry 3 `displayParamCount=5` matches Entry 0 `(5,7,7)`, following existing hidden-input plumbing. Persistence is still explicitly unresolved; hiding a parameter does not exclude snapshots.
- Follow-up work dispatched in parallel: native assignment/router/lifecycle proof; stereo VISA/call-list decoding; semantics-preserving audio size reduction and initial-Listen qualification. No new feature flag is exposed and the USB inventory still has no HX Stomp.

- Audio core reduced from 1191 to **1123 instructions** (1124 padded / **6744 raw code bytes**) using exact binary scaling and register reuse. All **47 audio tests pass in 37.21 s**, including eight Tape-rate zones and the endpoint. The unchanged 153-word private allocation now includes Play arming: a new instance ignores initial high until it observes low, then permits fresh capture. This does not replace snapshot exclusion on a live armed instance.
- Updated Entry 2 projection: baseline plus compacted data, full audio LDR and registry is **523604/524288 bytes**, leaving **684 bytes before the native bridge**. Current measurements are in `build/microlooper-audio-fit.json`; no production effect image is built from the provisional calling convention.
- Reusable instruction-path sampler: `tools/sharc/microlooper_profile.py`; current report `build/microlooper-instruction-profile.json`. Across 720 synthetic combinations, sampled peaks per 16 stereo frames: Listen 3294, Envelope 9581, Tape 7751, Stretch 13418 executed instructions. These are not exhaustive bounds, hardware cycles or DSP percentages; external-memory stalls and pipeline behavior are not modeled.
- Staged M4 routing now copies assignment IDs under the native lock, composes per-binding key/tick updates with the actual existing long-press module, and prevents successful-but-empty model lookups from reusing stale output. Regression group **278 passed in 14.00 s**. Ownership generation and pre-destruction/initialization ordering are still unproven, so no hooks are installed.

- Native diagnostic linking is now implemented in `tools/patch_microlooper_probe.py`, with four build/overlap tests and 19 adapter tests passing together (**23 passed in 2.68 s**). The absolute logger has 97 instructions and 200 reserved DM words; native graphs, allocation, init/control and parameters are unchanged. Only primitive 0x9c51's process pointer changes to the preserving wrapper. A concrete L6IA built from the all-web NAM1 baseline passes every integrity check: `build/microlooper-acoustic-diagnostic.l6ia`, MD5 `91ca9bf232f195efcd113b9fc661ac88`, Entry 2 **522036/524288 bytes**. This is an offline diagnostic archive with no host readback or coherent sample snapshots yet, not runnable micro-looper firmware. The canonical baseline HXF is unchanged; no hardware action or diagnostic HXF publication occurred.


### Clean regression checkpoint

- After all code edits settled, the full non-NAM group completed with **1397 passed, 2 skipped, 71 deselected in 347.86 s**; total wall time 347.99 s (**5 min 47.99 s**). This includes the optimized audio engine, staged switch router, native cost/replacement/refund paths, new diagnostic linker, web parity and the pinned default firmware MD5. No failures. XL/Effects stock fixtures remain unavailable.
- NAM remains **71 passed in 138.95 s** from the prior complete marker run; NAM implementation has not changed since that check. A discarded concurrent-development run mixed old imported probe offsets with edited assembly; the stable rerun above supersedes it.
- Next offline investigation: focused native VISA pointer decoding and a coherent diagnostic readback design using the existing DSP-frame transport. Neither a physical Stomp nor an audio-lane snapshot was obtained. Production registration/build enablement and hardware acceptance remain pending.


### Planar bridge and capacity follow-up

- Bounded VISA helper and original-initializer tests now establish a conditional two-row,16-word buffer geometry. Explicit tag3 high-first / external tag10 low-first assumptions remain; copied-word float use and live context are unproven. The initializer's16/2 dimensions are fixed constants, not inferred from supplied register values. See the native adapter note and `tools/sharc/microlooper_visa.py`.
- Added the disabled planar bridge: **101 instructions**,102 padded /624 loader bytes; **199 private DM words** including core/staging/spills. It converts complete input before writing output, supports in-place/separate buffers, validates full call/instance extents against actual SRAM banks, preserves ASTAT/STKY and requires an explicit per-graph reset. **100 bridge tests pass in 3.57 s**. No native initialization or registry wiring is implied.
- `tools/sharc/microlooper.py --bridge --compact-data --image ...` now counts each odd section's padding/header separately. Core 1123 + bridge 101 = 1224 instructions  / 1226 encoded. With the all-web NAM1 baseline, compact data and registry, Entry 2 is projected at **524228/524288 bytes, 60 spare**, excluding any further native-init/lifecycle DSP code. Fit remains tight and must be rechecked after those are known.
- NAM1's shared pool needs admission coverage even when normal DSP cost permits another NAM. Added staged `src/m4/nam_capacity.s` and `tools/nam_capacity.py`: native pricing/errors run first; the helper can only change the normal availability result from true to false for an exhausted NAM pool. It follows native object eligibility and exact replacement refunds. **98 tests pass in 4.99 s**. No Atmosphere instance restriction/warning exists. This helper is uninstalled; the final build must provide the actual NAM name index/profile and guard the native call sites.
- Diagnostic SRAM guards were tightened too: 114 instructions,200 reserved DM words. Regenerated archive `build/microlooper-acoustic-diagnostic.l6ia`, MD5 `d2215103dcddce500cf1de7757f1c6e7`, passes every integrity check; Entry 2 **522132/524288 bytes, 2156 spare**. It still has no host readback or coherent sample snapshots and is not user-testable micro-looper firmware. Canonical baseline HXF remains unchanged.
- Before broad user testing, include NAM-capacity admission/replacement and loaded-preset behavior in addition to looper DSP-cost graying. The development NAM1 kernel's overflow fallback does not itself gray browser choices; production must not rely on silent passthrough for accepted extra NAM blocks.


### Final affected checks for this batch

- After every source file settled, all micro-looper tests plus NAM-capacity, browser build, documentation and firmware fingerprint checks completed with **510 passed, 2 skipped in 109.06 s** (wall 109.17 s, **1 min 49.17 s**). The skips are the unavailable XL/Effects stock fixtures. The earlier clean full non-NAM run was 1397 passed/2 skipped in 347.86 s; NAM's unchanged implementation previously passed 71 tests in 138.95 s. No unresolved test failures.
- Current resource report: `build/microlooper-bridge-fit.json`, **524228/524288 Entry 2 bytes, 60 remaining** with separately encoded core/bridge sections and registry; additional native-init DSP code is not included. Private looper allocation is 199 DM words plus 48000 SDRAM words per instance.
- Remaining: prove loader parcel ordering and float use; qualify native allocation/reset and graph ownership; install composed switch/snapshot/lifecycle routing and NAM-capacity checks in the final builder; implement coherent diagnostic host readback/sample capture; then run hardware timing/load, admission/menu, controls and audio acceptance. No Atmosphere instance-count policy or warning will be introduced. No unit is connected, no production micro-looper build flag is exposed, and no firmware was RAM-run or flashed.


### Coherent diagnostic readback and conditional float-use checkpoint

- Implemented and tested the source sequence, preserving SHARC publisher, M4 RX/cache/USB handler and host decoder. This closes the earlier missing host-readback implementation; actual unit/DMA qualification remains open. Existing GR audio, fields and all process/control addresses are retained. Command 0x51 is reserved only for the explicit diagnostic, outside feature discovery.
- The explicit diagnostic linker now checks the complete original Acoustic Sim registry and exact installed GR code/callbacks, rewrites only changed instructions' final boot writers in place, handles PM records crossing bank boundaries, preserves existing M4 chains and rejects image overflow. Normal build selection and the canonical HXF are unchanged. No production Atmosphere flag or hardware operation is added.
- Built `build/microlooper-acoustic-telemetry.l6ia`, MD5 `f4dc2163cce14fd8b92bbffb30ff4a1e`, Entry2 **522648/524288 bytes, 1640 spare**. The logger-only artifact was regenerated: MD5 `31ce3f81bfbda0da0915ab8767f3f9ee`, Entry2 **522180/524288 bytes, 2108 spare**. Both archives pass every integrity check. These are diagnostics with unchanged stock Acoustic audio, not the Atmosphere. Full audio+planar bridge still projects only 60 spare bytes before native initialization.
- The bounded VISA continuation establishes copied-word float use under the explicit INIT16 order assumption: I1[0] read at 0x13ae6a → staging at 0x13ae6d → F4 at0x1828a9 → F12=F2*F4 at0x1828ab. Separate sign/zero-extension hypotheses produce identical provenance/results without choosing the unresolved immediate semantics. Default unsupported-form stopping remains. Physical loader order, L/R identity and actual allocation/lifecycle are still unverified.
- Affected diagnostic, VISA, host, GR, screen mirror, shared M4 framework, browser, docs and stock-firmware regression group: **428 passed, 2 skipped in 93.99 seconds (1 min 33.99 s)**. Skips remain missing XL/Effects fixtures. Documentation checked again after evidence updates: 2 passed. The audio core, planar bridge and NAM kernels were unchanged; their prior differential/profile checks remain applicable. No whole-suite rerun is claimed for this batch.

Next independent packages remain suitable for parallel work:

| Package | Owned boundary | Exact acceptance |
|---|---|---|
| Native initialization/allocation | Focused native allocator/init tracing and a separately tested reset adapter | Prove the actual private allocation size and init callback arguments/order, including first control delivery; reset marker/transport safely before processing, with actual-code tests. Do not infer allocation from registry size alone. |
| Graph/switch ownership | M4 mutation/commit paths and lifecycle routing | Establish pre-destruction quiesce plus completed-graph publication across preset/edit-buffer/model/delete/move/assignment changes; no reused ID or node pointer treated as an epoch. Install shared routing only after these facts are demonstrated. |
| Runtime context qualification | Explicit diagnostic plus connected-unit experiments | Qualify frame/cache freshness and collect native private dimensions/sample lanes for known L/R signals; preserve stock audio. The current 16-word register record alone cannot establish sample lanes. |
| Final integration (primary) | Builder, remaining DSP size, native NAM capacity and release surfaces | Join proven interfaces, fit actual native init code within Entry2, supply real NAM name/profile, measure DSP cost and visible browser graying, then run full audio/control/preset acceptance. No instance-count limit or warning. |

No diagnostic was RAM-run, flashed or offered as a user-testable Atmosphere image. Native lifecycle/build wiring, sample-lane evidence and connected Stomp qualification are the next gates.


### Completed items 1–3: native init, lifecycle and complete build

- Native allocation evidence now executes the stock SDRAM alignment, 27-word descriptor copy, DM/PM/SDRAM carving, exhaustion checks and process-record/I0 binding. The callback tests execute actual registry copying and native C dispatch. Parent arenas/selected member/audio pointers are explicit fixture inputs; complete native boot and physical stereo mapping remain item 4.
- Custom native callbacks replace unsuitable IR initialization. They reset transport and marker per instance, accept ordinary controls, and ignore restored transport before first processing. NaN/all-bits-set dirty state tests across all modes start finite/dry/listening, then capture on the first physical tap. No ring-wide clear or shared capture buffer is used.
- The ownership controller is installed: actual init/destruction boundaries, same-layout preset reload, retained moves, assignment changes, snapshots, explicit bypass, native mutation failures and dirty write retries have tests. Mode/function/bypass changes preserve Play when ownership survives, cancel Overdub and disarm held gestures. Input remains composed with the shared long-press owner. No Atmosphere instance limit or warning is introduced.
- Full build wiring is complete through `HX_MICRO_LOOPER=1`, default-off and excluded from web/release selection. The single-slot NAM profile is selected automatically. Native admission uses the final NAM name index and physical pool capacity; Atmosphere uses normal native DSP-cost admission. An explicit experimental cost is required until device measurement.
- Exact final parameter maps/defaults, native hooks, versioned runtime manifest, NAM capacity code/calls and memory/partition boundaries are verified before linking. Core 1099 + bridge 101 + callbacks 33 are 1236 padded instructions in one PM loader record. Entry2 is **524276/524288 bytes, 12 free**; per-instance DM199 / PM0 / SDRAM48000. Updated sampled instruction peaks across 720 configurations: Listen 3194, Envelope 9386, Tape 7586, Stretch 13253. These remain sampled instruction counts, not hardware cycles or DSP percentages.
- Built all standard web features plus Atmosphere into `build/HX_Stomp_v3.80.0_MicroLooper_experimental.hxf`, **MD5 `e4f7117243a5a61a1c425469435603fc`**. The named L6IA copy is `build/HX_Stomp_v3.80.0_MicroLooper_experimental.l6ia`, MD5 `e22f19590bc1d680a09ff959c6744720`. Every archive integrity field passes. Final source/registry/runtime/code comparisons pass. `build/microlooper-build.json` records all resources, hooks and checksums. Cost 7500 is explicitly unmeasured and consumes the native available budget in an otherwise empty preset; calibrate it during item 4.
- Clean frozen-tree full groups: **non-NAM 1981 passed, 2 skipped, 71 deselected in 386.08s (6 min 26.08s)**; **NAM 71 passed in 144.37s (2 min 24.37s)**. The groups ran in parallel: **2052 passed, 2 skipped in those full groups**. Skips are the unavailable XL/Effects fixtures. An earlier run collected an unfinished reload-test fixture; it is superseded by the clean groups. Final focused lifecycle/link run: 92 passed in 14.08s. Source-cache, docs, final link and manifest rechecks after comment cleanup: 26 passed in 9.71s. No unresolved test failures.
- The canonical baseline HXF is unchanged, MD5 `fe3514a293b5c5d239ba7fa4ec6f79d8`. No firmware was installed, RAM-run or flashed. No commit or push was made.

Remaining item 4 is hardware acceptance: boot/loader and native stereo lane confirmation, complete graph publication and worker/lock scheduling, audio/controls/preset/snapshot behavior, multiple private instances, measured DSP cost and visible native admission/refund. Qualify existing over-capacity NAM presets for the selected profile. HX Edit remains deferred by agreement. See [the integrated evidence and limits](research/features/microlooper-integration.md).


Final native bypass check: the actual outer/lower/node getters invert the enabled bit, confirming controller eligibility uses **0 active /1 bypassed**. Two additional native getter cases passed in 0.18s without runtime changes. Current collection is 2056 cases: 2054 passing cases covered across the full groups and those final two checks, plus 2 unavailable-fixture skips. Documentation recheck: 2 passed; `git diff --check` clean. See the switch note for addresses and the regression.


### Skeptical maintainer review and remediation

- Reviewed the full working changes, including untracked files, against `8004c8e8d032046306374b006a4693bec3bb4cab` using the user's bug-only skeptical-maintainer brief. Frozen pre-review diff SHA256: `1ec17f9ae9b25d99ada6e9ecfd7318c0d67a282798ec965aebb62485a0a5b8b8`. The delegated reviewer inspected native lifecycle/input and diagnostics; primary-agent inspection covered build, loader and NAM integration.
- One confirmed **P2** finding: the diagnostic receiver's equality-only source check accepted a delayed coherent sequence98 after100, replacing newer context and refreshing receive age. The pre-hook runs before the native RX old-frame rejection. An actual encoded-M4 replay reproduced sequence100→98→100 reporting fresh age0 without forward source progress.
- Fixed `src/m4/microlooper_readback.s` to require a positive modular delta below the uint32 half-range before clock sampling or publication. First-record acceptance is retained; wrap `0xfffffffe → 0` works. Added eight regressions for older/ambiguous records, replayed timestamps and positive progress across both wrap/signed boundaries. Independent focused re-review found no remaining actionable defect.
- Verification: readback/host/diagnostic group **111 passed in 7.00s**; cache parity/default firmware/docs/main-runtime hash group **15 passed, 2 skipped in 12.35s**. The skips are the unavailable XL/Effects fixtures. **126 passed, 2 skipped** in these affected checks; no runtime changes outside diagnostic telemetry. `git diff --check` passes.
- Regenerated `build/microlooper-acoustic-telemetry.l6ia`, MD5 `70087f2ec12b5ede201174b0ed182764`; every archive integrity check passes. Entry2 remains 522648 bytes / 1640 free. The integrated Atmosphere HXF is unaffected. No hardware operations were performed.


### Architectural review and remediation

- A delegated reviewer applied the user's architectural-quality brief to the complete working changes against `8004c8e8d032046306374b006a4693bec3bb4cab`, including untracked files and surrounding implementation. Frozen pre-review diff SHA256: `d63ab8680194c666006e4e4176e394446b57743ad0ba80b0be2191e1defd0a23`.
- One confirmed **P2** finding: the independent `HX_NAM_SLOTS=1` build setting could select a single-slot kernel without Atmosphere's native NAM-capacity admission hook. Native DSP pricing could then admit a second NAM whose single-slot kernel fell back to passthrough. Removed the independent setting rather than adding another production profile configuration. This supersedes the earlier development-profile entry above. Enabled effects now determine the profile: normal NAM3, GR NAM2, Atmosphere NAM1 with capacity admission.
- Explicit diagnostic layouts now flow directly into the existing click/GR placement helpers. Diagnostic callers no longer change process-wide NAM-profile environment variables. Regression coverage confirms the retired variable cannot select an unchecked NAM1 production build. The reviewer inspected this focused remediation and reported no remaining material concerns.
- Affected build, link, diagnostic, NAM admission, click/GR, browser, documentation and default-firmware checks: **274 passed, 2 skipped in 77.28s (1 min 17.28s)**. Skips remain the unavailable XL/Effects fixtures. `git diff --check` passes.
- Rebuilt the complete experimental Atmosphere firmware: byte-for-byte identical HXF, MD5 `e4f7117243a5a61a1c425469435603fc`. The report confirms NAM1, verified controls and Entry2's 12 remaining bytes. No DSP/M4 runtime changes or hardware operations were needed for this remediation.


### Requirement change: resources follow the preset

- The user rejected the firmware-wide NAM1 tradeoff after its effect on presets without Atmosphere was clarified. The accepted behavior is now baseline NAM capacity when Atmosphere is absent, and normal native availability based on resources actually consumed by the preset. The fixed-profile experimental artifact above does not meet this requirement and is not the target user-testing image.
- Source inspection confirms why an admission-only change is unsound: `nam_multi.Layout` reserves all model workspaces in Block3 at build time, and the Atmosphere linker places permanent executable code in the freed region. Removing a Atmosphere block cannot release that resident code through the current instance allocator. Current mid-sweep NAM1 reserves one 4,760-word workspace; NAM2 reserves two; NAM3 uses three 3,824-word workspaces with a different near/far-ring arrangement. The profile numbers cannot simply be exchanged at runtime.
- Next implementation gate: demonstrate a memory arrangement that retains baseline logical NAM capacity without Atmosphere while fitting resident code, GR and click. Investigate moving private working state into native per-instance storage before considering code overlays or shared-workspace swapping. Each candidate must prove full allocation bounds, initialization, multiple independently sounding NAM captures, ownership/replacement and worst-case processing cost. Neither DDR2 capacity nor a passing count check establishes executable placement or real-time feasibility. See the preset-resource note for evidence and alternatives.
- Once the storage design is proven, integrate its resource demand with native admission for insertion in either order, replacement, removal/refund and loaded presets. Browsing must be non-mutating. Restore baseline availability after removal; preserve normal DSP refusals; do not add a Atmosphere instance-count rule. Hardware checks must confirm menu graying and audio under the admitted combinations.
- This requirement update changes documentation only. The earlier development builder, artifact and its tested fixed-NAM1 admission remain unchanged pending a proven replacement; no preset-dependent firmware implementation is claimed.

### Shared Atmosphere declaration and resident layout

- Implemented the first two interface work items for Atmosphere only. The shared
  model compiler generates and validates model identity, typed parameters,
  separate public/state mappings, private resource declarations and callback
  registry entries. NAM is not migrated to the interface.
- Placed the complete Atmosphere engine in permanently reserved external ISA memory,
  using the hardware's documented normal-data alias and existing boot record
  encoding. Checked native heap setup and exact NAM code/data before placement.
  Baseline NAM3 and NAM2/GR retain their original workspaces and kernel; all
  13 NAM source/test fingerprints are unchanged. The Atmosphere build no longer
  selects NAM1 or installs a NAM-capacity wrapper.
- Shared clamp constants removed six Atmosphere instructions while preserving audio
  behavior. Current core/bridge/callback counts are 1093/101/33, padded to 1230
  instructions in 1845 DDR2 words. Complete all-standard-features + Atmosphere HXF
  MD5 is `5698d12ba91646e21bd382d90ec920c8`; Entry 2 is 524272 bytes, 16 free.
- Full Atmosphere/shared-declaration/default-firmware regression group: **782 passed,
  2 skipped in 125.33 seconds**. Skips are missing XL/Effects fixtures. Default
  firmware checksum remains pinned. See [the implementation evidence](research/features/microlooper-code-placement.md).
- Shared runtime memory admission and NAM migration were outside this work.
  Hardware boot, physical stereo binding, graph scheduling and measured external
  fetch/cache/DSP cost remain outstanding. No firmware was run or installed.
