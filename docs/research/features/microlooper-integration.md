# Atmosphere initialization, lifecycle and build integration

2026-11-14. Target: the user's HX Stomp 3.80.0 firmware, MD5 `a2cd8f4ae56f49415380270ebc484bf1`. This records the completed offline integration of implementation items 1–3. Hardware validation is separate. No unit was RAM-run or flashed.

**2026-11-15 continuation:** the current Atmosphere builder now uses a shared effect
declaration and [external ISA placement](microlooper-code-placement.md), preserving
baseline NAM2/NAM3 without changing NAM sources. The fixed-NAM1 sizes and artifact
hashes below describe the earlier integration. Hardware boot, stereo binding
and external-fetch timing remain acceptance gates.

**Requirement revision:** the fixed-NAM1 build documented here does not meet the
user's subsequent requirement to preserve baseline NAM capacity in presets
without Atmosphere. Memory-layout work is reopened; the earlier offline results
remain evidence for that implementation, not proof of preset-dependent
resource use. See [preset resource research](microlooper-preset-resources.md)
and the [updated plan](../../microlooper-plan.md).

**2026-11-17 hardware continuation:** RAM comparisons isolated an input-path
object mix-up and verified the correction with every control hook restored
individually. The complete corrected build passes boot/USB checks; audio and
gesture qualification remain pending. See [the hardware log](microlooper-hardware-log.md)
for current status; the original checkpoint below is historical.

## Native allocation and initialization

**[verified offline: original encoded constructor and dispatcher]** [microlooper_allocation.py](../../../tools/sharc/microlooper_allocation.py) executes the native alignment, descriptor copy and arena-carving path beginning at `0x177f8c`. It reads the selected composite member's DM/PM/SDRAM sizes from fields 13/14/15 and bounds the child's ranges against its parent. The production declarations are **199 private DM words, zero private PM words and 48,000 SDRAM words**. Tests cover exact boundaries, exhaustion, alignment and multiple private bases. The replay includes stock memcpy and guard words; no allocator arithmetic is substituted with Python.

**[verified offline: composed dataflow]** On the same simulator state, native process-record construction at `0x178139`, private-state binding at `0x17827d` and ISA dispatch at `0x8cb37` carry allocated descriptor word 0 through process-record word 4 into **I0**. Descriptor words 6/7 bound the SDRAM ring; process-record word 2 carries the instance descriptor. The parent arenas, selected member and audio buffers are explicit fixture inputs. The complete outer graph traversal, heap acquisition and physical stereo port layout are not simulated by this bounded test.

**[verified offline: actual native C callback dispatch]** [microlooper_init.asm](../../../src/sharc/microlooper_init.asm) supplies custom init and control callbacks. The stock NAM initializer is unsuitable: it clears a hardcoded 145-word state and mutates shared IR state. The Atmosphere initializer instead clears only Play, Overdub and the audio core's reset marker. The core then performs its bounded scalar reset on first processing; it never clears the entire SDRAM ring.

**[verified offline: actual registry-copy/control loops]** Stock code at `0x177a55` copies registry callbacks into the child descriptor and invokes init through the copied pointer. The control loop at `0x178108` supplies PID in R4, value pointer in R8 and descriptor in R12. The callbacks preserve the native C nonvolatile state and return zero through the native frame epilogue, rather than process `CALL`/`RTS`. They use no Acoustic Sim or IR callbacks and allocate no shared capture state. See [callback tests](../../../tests/test_microlooper_init.py).

**[verified offline: fresh transport]** Normal controls 5–9 are accepted during construction. Play/Overdub delivery is ignored until the first processing call, preserving the initializer's low levels despite saved high values. The first audio block starts listening and arms capture; the first physical tap then captures immediately. Tests dirty all 199 words with ordinary values, NaNs and all bits set, across all three modes. Output starts finite and exactly dry, old SDRAM contents remain untouched, and capture succeeds without a second tap. Native constructor controls execute synchronously before constructor return; publication of a half-constructed instance is outside the native caller contract and remains a device acceptance check.

## Ownership, input and snapshots

**[verified offline: installed assembly and native M4 execution]** [microlooper_native.py](../../../tools/microlooper_native.py) installs the controller through the same feature engine as existing HXtra features. It shares one key-handler owner with long-press, preserves the native tick and filters only the Atmosphere block's bypass action. Ordinary blocks sharing its physical switch still receive native events. The 400 ms hold decision uses the existing 100 Hz event thread. The [switch note](microlooper-switch.md) records exact mutation seams and tests.

**[verified offline: ownership]** Discovery resolves actual block objects and model 380 under the native graph mutex. Assignment snapshots and writes follow graph-then-assignment lock order. ROM tests establish recursive mutex behavior, including a real parameter write nested under the controller's graph lock. Routes receive owned generations; a block ID, assignment node address or reused runtime pointer alone does not establish ownership. The table follows the platform's 40 assignment records and deduplicates shared assignments. It adds no Atmosphere instance limit, enforcement or warning.

**[verified offline: lifecycle behavior]** Deletion/recreation invalidates old ownership. Retained-instance moves retarget the binding. Mode/function/assignment/bypass changes cancel Overdub and disarm a held gesture while retaining Play when the DSP instance survives. Failed writes remain retryable; native mutation failures preserve a still-live capture. Status veneers pass the actual native result to the after-handler. A fresh model check prevents a cached transport write from reaching another effect's slot 7.

**[verified offline: reload coverage]** The full-buffer application route reaches the ordinary-block removal dispatcher even when incoming model IDs and layout are identical. Tests execute the native path through `0x28e0e5d0`, `0x28e0b4ec`, `0x28df4a98`, `0x28dfcee4`, `0x28df5530` and `0x28df38d0`. A subsequent new Atmosphere instance therefore reaches the custom initializer; restored transport values cannot create a capture. Actual device scheduling remains unmeasured.

**[verified offline: snapshot exclusion]** The native parameter filter blocks external Play/Overdub writes for model 380 while allowing the controller's validated writer. Ordinary knob changes continue normally. Bypass retains its native UI/MIDI/snapshot meaning; an unchanged snapshot bypass does not stop playback. A bypass or move that reconstructs the DSP instance follows the fresh-instance rule.

## Complete build path

**[verified offline: full build]** `HX_MICRO_LOOPER=1` enables the default-off development feature. It selects the single-slot NAM profile and requires an explicit `HX_MICRO_LOOPER_DSP_COST` in native units. The flag is excluded from browser/release selection pending hardware validation. There is no guessed production DSP percentage. Stored NAM captures and User IR slots are unaffected.

**[verified offline: phase ordering]** [build.py](../../../build.py) registers Atmosphere metadata after NAM metadata and before M4 feature installation. NAM, metronome and GR DSP code are then installed normally. [patch_microlooper_build.py](../../../tools/patch_microlooper_build.py) runs last and verifies the exact NAM1 code, registered model/parameter contracts, runtime hook manifest and NAM-capacity wrapper. It installs the complete audio core, planar bridge and native callbacks. The full parameter blob is compared against the expected slot/PID/type/default graph; it rejects incorrect transport defaults or routing.

**[verified offline: native admission]** The [NAM-capacity installer](../../../tools/nam_capacity.py) supplies the actual final NAM name index and compiled capacity to both native candidate-admission calls. Native DSP cost/refund checks run first. Its final verifier checks the compiled wrapper, native budget/total entry guards and both call targets. The Atmosphere model uses ordinary cost admission and refund; there is no separate instance policy.

**[verified offline: image fit]** Core 1,099 instructions, bridge 101 and init/control 33 occupy 1,236 instructions including alignment. One combined PM loader record retains all entry addresses and padding while saving two redundant headers. Opt-in zero-data encoding saves 4,604 bytes without changing initialized memory. The complete NAM1 + GR + metronome image is **524,276 / 524,288 Entry 2 bytes: 12 bytes free**. Overlap and partition checks reject growth beyond that limit.

**[verified offline: concrete artifact]** `build/HX_Stomp_v3.80.0_MicroLooper_experimental.hxf` was built with all standard web features plus Atmosphere and passes every archive integrity check. Its report is `build/microlooper-build.json`. The verification build declares cost **7,500**, explicitly unmeasured; this consumes the native remaining budget in an otherwise empty preset. Hardware profiling must replace that experimental value before relying on ordinary multi-block availability. The canonical baseline HXF remains separate and unchanged.

## Remaining hardware acceptance

**[not yet verified on unit]** Physical loader parcel order, native L/R planes, full graph boot/publication, bypass scheduling, RAM-loader boot equivalence, real DSP timing and audible behavior remain acceptance tests. Exercise reloads, snapshots, assignment changes and multiple independently allocated instances on the unit. Confirm native visible graying/refund, and qualify existing presets whose NAM usage exceeds the selected execution profile. HX Edit support remains deferred. The earlier fixed-profile software integration is complete; the revised preset-dependent allocation is unimplemented, and this experimental firmware has not run successfully on a Stomp.
