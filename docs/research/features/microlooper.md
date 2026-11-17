# Atmosphere feasibility and implementation research

Research date: 2026-11-14. Scope: a selectable, stereo Atmosphere-style micro-looper for the HX Stomp, with Tape, Envelope and Stretch; no reverb, delay, Slip, wet freeze, or wet feedback routing. This is research, not an implemented feature or a hardware qualification.

Implementation and current requirements: [parallel execution plan](../../microlooper-plan.md). Subsequent user decisions supersede the alternatives below: defer HX Edit, use one switch with tap-to-capture/listen and 400 ms hold-to-overdub, preserve Atmosphere behavior, permit fewer simultaneous NAM blocks, and use native DSP-based browser graying. Do not add instance-count enforcement or warnings.

HXtra source baseline: `8004c8e8d032046306374b006a4693bec3bb4cab`, plus the existing local test/toolchain-documentation fixes. Stock HX Stomp 3.80.0 input MD5: `a2cd8f4ae56f49415380270ebc484bf1`. Atmosphere source is the sibling local project `../chase bliss mood clone`; it is not a Git checkout. Its paths below refer to that project when explicitly named.

Evidence follows [research conventions](../conventions.md): **[verified offline]** covers source inspection, arithmetic, builds and desktop/simulator checks; **[verified on unit]** refers only to historical results already recorded in the cited notes; **[hypothesis]** includes recommendations and proposed behavior. No new HX Stomp hardware experiment, preset write, firmware installation or flash was performed.

## Answers to the nine planning questions

| Question | Research conclusion | Remaining proof |
|---|---|---|
| 1. Reuse the stock looper? | Stock loopers have additional gain/harness stages; root port counts alone do not distinguish them from ordinary effects. A regular stereo FX host is the better-understood candidate. | Reuse would require more transport, buffer and harness reverse engineering; it is not required for the leading path. |
| 2. Where do buffers/code live? | 24,000 stereo float frames need 192,000 bytes; this fits the stereo host's declared SDRAM budget. Code/scratch are much tighter. | Stereo channel/instance ABI, large-buffer allocation, valid-count reset, and code placement. |
| 3. DSP cost and instance count? | No defensible percentage or instance guarantee yet. The current code-space and boot-image limits are quantified below. | Assemble the port; profile worst-case memory access and processing on the HX Stomp. |
| 4. Listen while bypassed? | Existing evidence does not establish input delivery or execution while bypassed. | Use enabled+Listen as the initial contract; probe ordinary/snapshot/global bypass separately. |
| 5. Capture/overdub controls? | Standard parameter plumbing exists; explicit Listen/Play state plus Overdub is the leading interface. | Footswitch/MIDI transitions, snapshot exclusion, preset initialization and gesture integration. |
| 6. Extract Atmosphere? | Looper algorithms are separable; retain one ring, transport, clock, splices, mix and transitions. | SHARC numerical port and deliberate handling of abrupt parameter changes. |
| 7. Identity/HX Edit? | Device registration is established. HX Edit requires compatible donor identity/type/range layout or accepted device-only editing. | Choose and validate a donor or explicitly accept the editor limitation. |
| 8. Lifecycle? | Per-instance, RAM-only captures; preset controls are separate from audio. | Which graph actions retain an instance, and how initial parameter writes behave. |
| 9. Verification? | Existing C++ reference and splice regressions are available and pass. | Differential SHARC tests, resource checks, hardware lifecycle/control/timing/audio tests. |

## Leading design and bounded feasibility gates

**[hypothesis]** Implement a regular stereo effect with private stock-allocated SDRAM. While enabled and listening it passes dry input and continuously records. An explicit Listen-to-Play transition captures recent history; Play-to-Listen resumes recording. Overdub is a separate level. Keep Mode, Length, Modify, Clock and Mix as ordinary parameters. Do not bind capture to normal bypass or promise recorded audio survives graph reconstruction.

**[hypothesis]** Decide the editor policy together with the parameter layout. A new ID is suitable for device-only experimentation; a shipping HX Edit-compatible design must preserve a tested stock donor's identity, slot types and ranges, and sacrifices that donor on the device. Neither ID555 (NAM) nor ID181 (metronome) is available. Standard browser styling avoids depending on the metronome's repurposed Unknown category.

The implementation plan should have four explicit go/no-go gates:

1. **Stereo memory probe:** prove two independent input/output channels, instance memory lookup, bounded ring reads/writes, guard words and initialization; no full DSP algorithm yet.
2. **Transport and lifecycle probe:** instrument instance/init/capture epochs and input delivery; test control duplication, snapshot changes, preset reload, move/delete/recreate, bypass and two instances. Saved Play must not masquerade as a fresh capture press.
3. **Fit the complete algorithm:** port all three modes against a minimal C++ oracle; measure PM/DM sections and the complete LDR image for NAM2/NAM3, GR and metronome combinations. Reject unsupported combinations at build time. Do not silently drop existing features.
4. **Hardware qualification:** EMUCLK and actual load measurements, input/output recordings, repeat/crossfade checks, worst-case speed/seams/overdub, memory pressure, multiple instances and soak. Only then set a conservative declared DSP cost and supported instance count.

The port must also update `build.py`, feature registration if M4 work is required, browser worker sources/build steps, release cache/hash generation, feature docs and tests. Merely dropping a Python feature module into `tools/features` does not add a DSP model: see [the metronome implementation](../../../tools/patch_click.py), [build orchestration](../../../build.py), [browser worker](../../../web/firmware-worker.js), and [release cache](../../../tools/m4cache.py).

## Fresh baseline build and external hardware facts

**[verified offline]** Built the current browser feature set plus Real Names from the supplied stock file with `--no-check`; checksum verification reported `ALL OK`. This verifies packaging and current code assembly, not audio execution or the NAM reference simulator check. Result: `build/HX_Stomp_v3.80.0_HXtra.hxf`, MD5 **`b4d16bae62fc91c8593b692b5c47016b`**. No micro-looper patch is in this image.

Enabled flags: `HX_TUNER HX_TAP_COLOR HX_BPM HX_GR HX_BREATHING_LINE HX_DSP_METER HX_LONG_PRESS HX_CLICK HX_MORE_SNAPSHOTS HX_REAL_NAMES`, each set to `1`. Reproduce with those environment variables and `.venv/bin/python build.py /path/to/stock.hxf --no-check`.

| Archive entry | Payload bytes |
|---|---:|
| 0, M4 application | 1,013,248 |
| 2, DSP boot stream | 521,440 |
| 3, model metadata | 893,036 |
| 4, graph library | 14,669,656 |
| 7, image index | 79,968 |
| 8, images | 4,842,784 |

**[verified offline: manufacturer documentation]** The ADSP-21469 supports core/DMA external memory access and both traditional ISA and VISA execution from external bank0. This establishes hardware capability, not that HXtra's patcher, address map or simulator supports a new external-code implementation. Mixed 32-bit data/48-bit instructions require distinct address accounting. Source: [Analog Devices data sheet, Rev B, pages7–8](https://www.analog.com/media/en/technical-documentation/data-sheets/ADSP-21467_21469.pdf). The existing patcher/internal-memory path remains the initial route; external execution is an alternative requiring separate validation.

## DSP host, resources and processing

### Decision: use a regular stereo effect host as the leading candidate

**[verified offline]** `tools/kit_patch_amp.py:1166–1206` already supports a stereo two-input/two-output in-place effect host (composite `0x600096`), custom primitive selection, and declared per-instance DM/PM/SDRAM sizes. `add_model_entry4(..., fx=True)` clones the host and installs the new primitive (`tools/kit_patch_amp.py:1317–1353`). This is the existing addition mechanism, not a proposed abstraction.

**[verified offline; corrected by subsequent stock parsing]** The stock One Switch and Shuffling Looper graphs have these root descriptors: one-switch blobs 849/850 have zero explicit input ports and two outputs (root composites `0x6001c1`/`0x6001c0`); their cores are primitives `0x271e`/`0x271f`. Shuffling blobs 853/854 likewise have zero inputs/two outputs and cores `0x9c54`/`0x9c53`. AppLooperHarness blob 855 has zero inputs/six outputs and nests `0x600008` and `0x6001c0`. The ordinary stereo host root also has zero inputs/two outputs, and both its processing member and the One Switch Stereo processing member have two inputs/two outputs. Root counts therefore do not establish a special calling convention. The One Switch graph has extra gain stages and the application harness has additional routing; these are structural observations, not proof of runtime buffer layout. Reproduce with `load_l6ia_from_any`, `get_entry_swapped(...,4)`, `entry4_blob.blob`, `entry4_blob.top_type`, `entry4_blob.parse_composite`; parser definitions are at `tools/sharc/entry4_blob.py:40–105`. Source input: stock file checksum `a2cd8f4ae56f49415380270ebc484bf1`.

**[hypothesis / recommendation]** Reusing the stock looper is possible only after further RE of its specialized harness, ring pointer ownership, transport, allocation and grain algorithms. Nothing currently exposes a safe reusable stock looper buffer interface. A separate stereo FX primitive is the smaller known engineering path for porting Atmosphere's already-understood three modes. Do not promise the native looper's global buffer, footswitch UI or duration automatically transfers to the custom block.

### Buffer allocation: declared per instance, not a hard-coded global address

**[verified offline]** The regular stereo FX slot grants DM `0x3a2` (930 32-bit words), PM `0x1e0` (480 words), and SDRAM `0x63000` (405,504 words; 1,622,016 bytes). The helper checks requested sizes and writes them to the cloned primitive member (`tools/kit_patch_amp.py:1178–1205`). Mono budgets differ; choose stereo from the start rather than routing a mono host twice.

**[verified offline / arithmetic]** Atmosphere's 24,000 stereo float frames require 48,000 32-bit words = 192,000 bytes (187.5 KiB) per instance. This is below the stereo slot's declared budget. Reserve additional state and any staging scratch explicitly; do not conflate normal 32-bit words, 48-bit program instructions and bytes. Even 8 such rings total 1,536,000 bytes, but this is capacity arithmetic only, NOT a proven eight-instance runtime promise.

**[verified on unit, existing NAM evidence]** Runtime heaps are divided into slot arenas; current=end pointers cannot be treated as actual usage. Probe measurements and silent-block failures from missing host SDRAM budget are documented at `docs/research/KIT_UNIT_MEASUREMENTS.md:10–20` and `docs/research/KIT_HEAP_USE.md:10–17,59–65`. Simply choosing apparently unused global DDR2 is unsafe.

**[verified offline, existing code]** NAM obtains the calling instance through `DM(2,I3)`, then SDRAM start/end at instance offsets 6/7, validates size, and notices instance/buffer changes (`tools/sharc/nam_multi_kernel.asm:222–237`; generated ABI constants at `tools/sharc/nam_multi.py:334–337`). That is a usable reference for buffer lookup, but the stereo host’s call-list layout and channel pointers must be verified in a minimal probe before the full port. Keep ring transport/state instance-local; no shared `I0`-only ownership heuristic that aliases a new block reusing an old allocation.

**[hypothesis / experiment required]** Stock lifecycle reset/zero behavior for a large stereo ring and changing presets must be tested. Avoid synchronously clearing 48,000 SDRAM words in an audio callback; use valid-frame counts or bounded staged clearing. Verify create/remove/recreate, move, duplicate, preset change, and simultaneous instances. A declaration fitting the helper is not sufficient evidence of safe runtime behavior.

### Fresh internal code-space measurements

These are calculated from current `nam_multi.layout(['--mid-sweep', '--slots',str(n)])`, `report()`, `patch_click.kernel_size()/pm_base()`, `patch_comp.dsp_place()` and assembly section lengths. Source: `tools/sharc/nam_multi.py:459–470,1492–1497`, `tools/patch_click.py:188–208`, `tools/patch_comp.py:329–346`.

| Current configuration | Block 2 free normal words | Block 3 gap normal words |
|---|---:|---:|
| NAM 3 slots, mid-sweep | 4 | 512 before metronome |
| NAM 3 slots + metronome | 4 | 299 |
| NAM 2 slots, mid-sweep | 4 | 2,528 before metronome |
| NAM 2 slots + metronome | 4 | 2,315 |
| NAM 2 slots + metronome + GR | 4 | 1,077 |

The metronome is 142 program instructions = 213 normal words. GR is 336 DM words plus 600 program instructions plus alignment. These fresh numbers supersede `docs/resource-limits.md`'s older 568/2720 totals. The **1,077-word** remaining gap with GR+metronome can hold at most 718 48-bit instructions if it held code alone; global scratch would reduce that. It cannot yet be claimed to fit all three micro-looper modes.

**[verified offline]** `patch_kernel` currently permits PM sections only in the two internal free ranges (`tools/kit_patch_amp.py:386–420`). It does NOT already support freely placing our new 48-bit kernel in DDR2. Stock uses external VISA code, but the simulator does not execute VISA (`docs/research/sharc/registry.md:16–18`). External execution is an independent research/validation project, not free space we can assume available.

**[verified offline]** Default and browser-wide builds differ in NAM slot count and features. Parent's fresh all-web-feature+opt-in baseline payload sizes include Entry 2 = 521,440 bytes; the current injection guard is 524,288 bytes (`tools/patch_amp.py:266–287`), leaving **2,848 bytes under the existing guard**, around 474 instructions before LDR descriptor overhead. The archive also stores a separate 512-byte entry sub-header (`tools/l6ia.py:25–32`); confirm physical partition boundary accounting before interpreting the guard as exact usable flash space. Parent retains checksum and size measurement artifact. Boot file space and internal execution space are distinct limits, both must pass.

**[hypothesis / recommendation]** First assemble the port and measure actual sections. Likely choose an explicit build profile that reduces NAM slots or excludes GR/metronome rather than silently overlapping memory or replacing tested binaries. Three modes on top of the all-web build are not yet shown feasible. Treat a zero-fill encoding optimization (existing notes estimate ~3.2KB saving for NAM staging) or unused primitive instruction reclamation as separate measured optimizations, not assumed budget.

### Runtime cost and DMA

**[verified on unit, existing evidence]** Custom processing is invoked once per 16-sample block. An audio quantum is about 150,900 SHARC cycles; the measured base load was 19.8% for the probe preset (`docs/research/KIT_UNIT_MEASUREMENTS.md:10–16`). At 48kHz this means 3,000 callbacks/s. M4 declared cost is an admission estimate, not a runtime watchdog; existing documentation notes 15% declared base and a 90% admission cap (`docs/resource-limits.md`, DSP time section). These are different measures; do not compute free real cycles from declared cost alone.

**[verified offline]** `tools/nam_meter.py` and NAM meter injection already expose EMUCLK timing and stock idle/load words (`tools/sharc/nam_multi.py:473 onward`). Use those to measure the actual port. No meaningful micro-looper DSP percentage can be stated before kernel implementation/probe timing. C++ host benchmarks and Hothouse CPU percentages are not predictions for the ADSP-21469.

**[verified offline]** NAM uses shared external-port DMA channel 0 and requires it idle plus its interrupt masked (`tools/sharc/nam_multi_kernel.asm:248–260`), and has bounded timeout/backoff. Historical `KIT_EP_DMA.md` says its original standalone probe was not hardware-tested; this is older than the current NAM integration. Cite current code and actual NAM hardware notes, not the historical probe as proof of port performance.

**[hypothesis / recommendation]** Begin with direct core SDRAM access for the minimal ring probe and measure stalls; random fractional read heads and splice crossfades are not a sequential streaming benchmark. Introduce block staging/DMA only if measured necessary. Any use of EP0 must coordinate serially with NAM, leave channel idle at return, use bounded waits, and avoid interrupts/global DDR configuration. The stereo ABI, in-place input preservation, MODE1 and registers must all be preserved. Control ABI is documented at `docs/research/sharc/registry.md:16`: pid R4, value pointer R8, core state R12.

### Required feasibility experiments before committing to an implementation profile

1. **Stereo passthrough + ring probe**, custom unused primitive distinct from NAM and metronome; verify channel order, own SDRAM extent, guard words, no allocation/global corruption.
2. **Capture/playback and lifecycle**, 24k stereo ring with valid count, silence/empty buffer, re-creation, mode changes and duplicates. Explicitly measure initialization spikes.
3. **Assemble full candidate**, report code bytes, live internal state/scratch and LDR size for NAM2/NAM3 × GR × metronome. Refuse unsupported combinations at build time.
4. **EMUCLK/load sweep**, each mode, fastest forward/reverse, splice boundaries, overdub, reduced clock and control changes; run with NAM and expensive stock delay/reverb/pitch neighbors. Choose conservative declared cost from worst-case hardware data.
5. **Instance sweep**, 1–8 blocks as resource admission permits, guard/counter checks and long soak. Advertise only the proven count; do not hard-code a single shared buffer unless single-instance design is deliberately chosen and enforced.

## Runtime controls, model identity and lifecycle

### 4. Continuous listening versus bypass

**Answer: bypassed-block scheduling is still unknown; do not make always-listening depend on it.**

- **[verified offline]** The existing bypass smoke check only switches a NAM block off/on, reads its enabled state, and checks that the device remains alive. It does not count DSP callbacks, check input delivery while bypassed, or check preservation of private DSP state. Therefore its passing result cannot establish that a micro-looper would continue recording during bypass. Source: [tools/hx_smoke.py:452](../../../tools/hx_smoke.py).
- **[verified offline]** A custom effect's processing primitive normally runs in 16-sample blocks. NAM's implementation assumes that its I0 identifies an instance and its call timestamp can be used to reclaim a slot whose previous owner has stopped running. That is a NAM-specific allocation policy, not proof of what the stock dispatcher does on bypass. Source: [tools/sharc/nam_multi_kernel.asm:10](../../../tools/sharc/nam_multi_kernel.asm).
- **[hypothesis: proposed behavior]** Make listening a live DSP transport state: the block is enabled, writes its input into the circular buffer, and emits dry audio until Capture changes it to playback. Capture is not the block's normal bypass operation. This meets background capture while avoiding a bypass scheduler dependency. Normal bypass can remain ordinary bypass, with the contract explicitly saying that recent input while bypassed is not guaranteed to be captured.
- **[hardware experiment required]** A small primitive increments a callback counter and records an input checksum/write cursor. Read them while enabled, block-bypassed, snapshot-bypassed, DSP All Bypass and Analog All Bypass. Re-enable and inspect whether state resumes or reinitializes. A callback counter alone is insufficient: a bypassed primitive could receive zeros or no actual input. The result determines whether a richer bypass/listen behavior is possible.

### 5. Capture/overdub controls

**Answer: use parameter control first; the original one-switch tap/hold UX needs separate investigation.**

- **[verified offline]** Stock parameter controllers include EXP1/2, FS1–5, MIDI CC and Snapshot. CC receive drives the shared controller dispatcher with a normalized float. Sources: [docs/research/m4/footswitches.md:16](../../../docs/research/m4/footswitches.md), [same note:24](../../../docs/research/m4/footswitches.md).
- **[verified offline]** Parameters of type float, int and bool map to separate input-node operations. The metronome registers custom parameters and writers that deliver them to DSP parameter IDs. Thus transport can be expressed as parameter values without inventing a new USB protocol. This proves the parameter plumbing pattern, not the desired momentary behavior on a new block. Sources: [tools/kit_patch_amp.py:1097](../../../tools/kit_patch_amp.py), [tools/patch_click.py:50](../../../tools/patch_click.py), [tools/patch_click.py:216](../../../tools/patch_click.py).
- **[hypothesis: proposed behavior]** Start with an explicit Listen/Play state parameter plus a separate Overdub parameter, with Mix, Mode, Length, Modify and Clock as ordinary values. Capture occurs only on a Listen→Play transition; a repeated write of Play is idempotent. Overdub is level controlled and effective only while a capture exists. This avoids a pulse that can be lost between M4 writes and DSP polling.
- **[verified offline / existing unit evidence]** HXtra's virtual FS6–FS10 use CC20–24; Controller Assign can use those CCs as parameter controls too. Its long-press feature owns the stock footswitch event-handler entry and deliberately defers taps until release. It uses a one-second hold, not Atmosphere's 400 ms threshold. A new tap/hold handler cannot independently own the same site. Sources: [tools/features/long_press.py:1](../../../tools/features/long_press.py), [same file:20](../../../tools/features/long_press.py), [docs/research/features/long-press.md](../../../docs/research/features/long-press.md).
- **[hypothesis: proposed behavior]** First prove two ordinary controller assignments (latching Capture, momentary Overdub) and MIDI values 0/127. A later one-switch tap/hold convenience should be implemented in coordination with the existing handler, not by adding a conflicting hook. Verify per-switch momentary/latching configuration because that can affect every assignment on the same switch.
- **[verified offline]** Snapshot selection sends controller values and restores enabled states. Consequently a transport parameter controlled by snapshots can cause Capture/Listen transitions. Disable snapshot control for transport if the stock setting supports it; test whether a parameter's exclusion remains effective on reselect and preset reload. Source: [docs/research/m4/snapshots.md:7](../../../docs/research/m4/snapshots.md).
- **[new offline observation; unproven mechanism]** Parsing the supplied stock firmware's model descriptors shows that the One Switch Looper has ten runtime parameters, but both `displayParamCount` and `presetParamCount` are four. The remaining parameters include transport operations. The generic custom-effect path intentionally strips `presetParamCount` and `followEnable`. This is a lead toward transient transport parameters, not proof that merely setting `presetParamCount` makes arbitrary custom parameters nonpersistent or snapshot-exempt. Source and reproducibility path: `kit_patch_amp.load_l6ia_from_any(stock)` → `get_entry_swapped(...,3)` → `parse_entry3_full` → select `HD2_LooperOneSwitchStereo`; [tools/kit_patch_amp.py:1176](../../../tools/kit_patch_amp.py).
- **[hardware experiment required]** Verify button press/release ordering, rapid taps, duplicate CCs, assignments to virtual switches, and snapshot recall. Explicitly check initial preset parameter delivery: loading a saved Play value must not capture an empty buffer as if the user had pressed Capture. A custom init/control path may need an armed/ready epoch distinct from persisted settings.

### 7. Model identity and HX Edit

**Answer: on-unit model registration is established; full HX Edit compatibility requires a known donor identity or additional editor work.**

- **[verified offline, metronome previously verified on unit]** Registering a selectable block involves Entry 3 descriptor, Entry 4 graph/parameter map, and Entry 0 model/browser records. The metronome checks all three parameter definitions agree, chooses a permanent preset ID, and patches its primitive. Browser placement under Looper does not make it a native looper: its block kind remains a normal effect. Sources: [tools/patch_click.py:36](../../../tools/patch_click.py), [same file:198](../../../tools/patch_click.py), [tools/kit_patch_amp.py:537](../../../tools/kit_patch_amp.py), [docs/research/features/metronome.md](../../../docs/research/features/metronome.md).
- **[existing verified-on-unit evidence]** HX Edit uses its own catalog rather than fetching a custom firmware's model definitions. Unknown model IDs disappeared from its whole-preset writes. Choosing a known donor ID alone was not enough: type mismatches dropped a whole preset, and ranges were clamped according to the donor catalog. NAM survived whole-preset writes once it replaced known Xenomorph Mono and matched its slot-by-slot types/ranges. Sources: [docs/research/HX_EDIT_DROPS_NAM.md:10](../../../docs/research/HX_EDIT_DROPS_NAM.md), [same note:48](../../../docs/research/HX_EDIT_DROPS_NAM.md).
- **[hypothesis: proposed behavior]** Select a stable unused model ID only if device-only editing is an accepted limitation. Otherwise select a stock stereo donor whose complete parameter shape can encode the desired looper controls without incompatible type/range changes, remove that donor's model registration, and accept that HX Edit will show the donor's name and controls. Do not reuse NAM's occupied ID555 or the metronome's occupied ID181.
- **[new offline observation]** Stock Shuffling Looper descriptors have numerous knobs plus hidden Transport/DirectStop parameters, making them candidates for semantic research. Native loopers also use special block kinds/metadata and controller handling; their identity is not a free safe drop-in donor. A normal stereo effect donor avoids those special paths but may be harder to map to transport parameters. No donor has yet been validated for this micro-looper, and no existing stock effect should be removed before making that product choice explicit.
- **[hardware experiments required]** Device add/move/save/reload; HX Edit drag with gaps and between rows; parameter changes; copy/paste; export/import and backup restore. Check emitted value types/ranges and every block survives, not only that the UI still responds.

### 8. Lifecycle, multiple instances and capture ownership

**Answer: allocate state per instance, treat recordings as volatile, and verify graph reconstruction explicitly.**

- **[existing verified-on-unit evidence]** Instance addresses follow creation order rather than grid position. Moving a block must not equate its screen slot to private DSP memory. Source: [docs/research/KIT_HEAP_USE.md:53](../../../docs/research/KIT_HEAP_USE.md).
- **[verified offline]** NAM reads its instance's SDRAM extent from the stock instance descriptor, checks capacity, and resets if the base changes. Its custom global owner-slot policy is specialized for scarce NAM internal-memory slots. A micro-looper should use its own instance descriptor allocation and avoid copying the slot-reclamation heuristic unless sharing resources is actually needed. Sources: [tools/sharc/nam_multi_kernel.asm:222](../../../tools/sharc/nam_multi_kernel.asm), [same file:10](../../../tools/sharc/nam_multi_kernel.asm).
- **[verified offline]** Presets describe blocks by model ID, enabled state and values. Snapshot records describe enabled states/controller values; no generic recorded-audio serialization exists in these formats. Adding persistent recordings would require separate storage, a much larger feature. Sources: [tools/hx_ctl.py:28](../../../tools/hx_ctl.py), [docs/research/m4/presets.md:5](../../../docs/research/m4/presets.md), [docs/research/m4/snapshots.md:6](../../../docs/research/m4/snapshots.md).
- **[hypothesis: proposed minimal contract]** New instance starts empty/listening, valid-count zero; no stale SDRAM sample is readable. Deleting or replacing the model relinquishes its capture. Power loss clears captures. Preset load starts a new instance with an empty capture unless a separately proven seamless-lifecycle mechanism preserves it. Changing Mode/Length/Modify/Clock on the same live instance preserves its captured samples and changes reading behavior. Snapshot changes preserve audio only if the graph keeps the instance and transport values do not command otherwise.
- **[hardware experiments required]** Instrument init count, instance identity, buffer base/length and capture epoch. Exercise move within/across rows, insertion ahead of it, model swap, preset save, same-preset reload, different preset, snapshot recall, reselect, bypass, two/three instances and memory-pressure refusal. Determine which actions preserve the DSP instance and which reconstruct it. Never promise sample persistence across moves or snapshots solely from parameter readback.

### Planning consequences

1. Prove an enabled stereo custom primitive with private SDRAM, dry-through input capture and explicit Listen/Play control before optimizing UI gestures.
2. Make parameter design and HX Edit donor selection one decision: type/range/layout persistence constraints are inseparable.
3. Treat bypass recording and graph-lifecycle preservation as gated experiments, not assumed stock services.
4. Use source/reference and simulator tests for state-machine behavior; use the hardware matrix for scheduler/input/lifecycle questions, since the simulator directly calls the kernel and cannot establish dispatcher behavior.

#### Bounded transient-parameter probe

**[hypothesis: proposed behavior]** Baseline transport is a numeric 0/1 parameter (0 Listen, 1 captured playback), not a toggle command. DSP graph init resets actual playback/listening state to empty/listening, arms transport after initial parameter delivery, and accepts a later observed 0→1 transition as Capture. It never interprets the first restored `1` as a user capture. This avoids saving an action by accident; the exact initialization ordering is part of the probe.

Build one diagnostic custom model with distinguishable regular-settings and transport sentinels. Inspect its generated Entry 3 `presetParamCount`, Entry 4 input/state slots and Entry 0 count fields together. Read the edit buffer before save, after save, after preset reload, and after each snapshot select/reselect; log the values delivered to the DSP and its init/capture counter. Compare with the stock One Switch Looper's metadata/count behavior. Test setting Snapshot Control Off for the transport independently of `presetParamCount`. Success means ordinary settings round-trip and snapshots do not cause an unsolicited capture or resume-overdub action. If the model counts metadata does not reliably exclude the action, use safe initialization/edge semantics and a transport-specific exclusion hook as needed; do not claim setting `presetParamCount` alone solves snapshot exclusion.

## Atmosphere extraction and verification

### Evidence status

- **Verified offline from source** below means direct inspection of C++ implementation, not SHARC execution.
- **Verified offline here:** rebuilt and ran `tests/engine_test.cpp` and `tests/loop_splice_test.cpp` linked to the actual `firmware/engine.cpp`, with clang++ C++17, `-O1 -Wall -Wextra -Werror -fsanitize=address,undefined`; both passed. Binaries were placed in a temporary directory outside the original project.
- **Unverified on HX Stomp:** algorithm timing, port numerical equivalence, resources and audible quality. Atmosphere Hothouse runtime measurements do not establish Stomp feasibility.

### Exact reusable behavior

1. **History and capture:** recorder is a `Ring<24000>` of stereo pairs of 32-bit floats. The audio payload is 24,000 * 2 * 4 = **192,000 bytes** (48,000 SHARC 32-bit words); scalar state and any transfer staging are additional. Full Engine also has two 48,000-frame wet/freeze rings and two 2,048-frame diffusion rings, which must not be carried into a looper-only port. Source: `firmware/engine.h:8-32`, `49-85`.
2. **Listening:** records one internal-clock sample per tick only while `loop_on_` is false. Current recorder input is clipped dry input plus half wet output if wet is enabled. For looper-only behavior, remove wet contribution and record just block input. Capture takes the valid history accumulated before the button event, not a newly started recording. Valid history saturates at ring capacity; early capture uses a shorter history; empty capture is one initialized silent frame. Source: `firmware/engine.cpp:72-86`, `219-240`.
3. **Returning to listening:** toggling playback off clears the valid-count, not the physical ring. New input overwrites in chronological order; a quick recapture includes only newly recorded samples. Capture resets playback/transport/grain anchors, overdub cursor and held-envelope state. Toggling loop always stops overdub. Source: `firmware/engine.cpp:72-86`.
4. **Tape:** LENGTH chooses `max(1, full * (.02 + .98 * length^2))` frames from the captured region. MODIFY chooses eight discrete rates `[-4,-2,-1,-.5,.5,1,2,4]`. No stationary Tape position. Linear interpolation handles fractional positions. Source: `firmware/engine.cpp:99-123` and `10-25`.
5. **Envelope:** computes peak of L/R input, envelope attack coefficient .02 and release .0008 per internal tick, threshold `.25 * 2^(-9*modify)` and .7 hysteresis. Above threshold, repeats the slice starting at the current transport position; below, playback advances normally. LENGTH gives `min(full,48+length^2*(full-1))` frames. Slice edges have short fades. This is input-driven stutter, not a gate muting output in silence. Source: `firmware/engine.cpp:113-139`; behavioral assertions `tests/use_case_audit.cpp:85-106`.
6. **Stretch:** two half-cycle-offset triangular grains; grain length `min(full,96+length^2*16000)`. Grain reads move forward at unity local pitch; anchors scan at `(2*modify-1)*abs(2*modify-1)`, which ranges -1..1 and stops at midpoint. Thus reverse means reversed progression of anchors, not fully reverse grain playback. Source: `firmware/engine.cpp:140-156`.
7. **Splices:** tail overlaps head by `min(240,length/8)` frames. Effective period is source length minus overlap, including reverse reads. Port exactly this corrected algorithm; don't reintroduce the old "fade toward head then jump back" discontinuity. Source: `firmware/engine.cpp:6-25`; prior diagnosis and measured improvement: `docs/VALIDATION.md:60-80`.
8. **Overdub:** allowed only during playback. Each internal tick writes `clip(old*.9995 + dry_input*.5)` through its own chronological cursor modulo **full captured length**, independent of read position, cropped Tape length, speed, or Stretch anchors. Cursor advances only while overdub is on and resumes on later holds. This is deliberately bounded textural accumulation. Do not describe it as aligned sound-on-sound: even unity playback uses a shortened splice period, so the write/read periods differ. Source: `firmware/engine.h:56`; `firmware/engine.cpp:158-164`; analysis `docs/MOOD_USE_CASE_AUDIT.md:88-98`.

### Clock, mix and transitions that must be specified explicitly

- Clock uses divisors 1/2/4/8/16 with .58-step hysteresis, while codec input/output remain 48 kHz. This gives nominal .5/1/2/4/8 seconds of maximum history. During playback a clock change retimes/pitches the existing audio without conversion. History recorded while changing clock has no per-sample time metadata. Source: `firmware/engine.cpp:57-64`, `243-250`; `docs/VALIDATION.md:143-150`.
- Downsampling takes the current input at each tick with **no anti-alias filter**. Reconstruction linearly blends previous and held ticks. Preserve this as Atmosphere's lo-fi clock behavior or explicitly scope improved resampling as a changed algorithm. Lower clock settings also slow envelope coefficients and transition time in wall time, because those advance in internal ticks. Source: `firmware/engine.cpp:115-116`, `236-250`; validation `143-147`.
- Capture/resume and mode changes blend from last held output over 240 internal ticks: 5ms at 48k, 80ms at 3k. Mix and effect-enable gain smooth at .002 **per host sample**, ~10.4ms time constant at 48k. Final output is clipped linear dry/wet blend, exact settled dry while listening. Source: `firmware/engine.cpp:52-54`, `72-74`, `236-258`.
- Mode changes retain capture, transport and most phase state, resetting only `env_held_` and starting blend. LENGTH/MODIFY changes don't trigger transition smoothing. Changing to a shorter Envelope slice can leave an old `play_` outside the new slice for one tick; its `min(play_,slice-play_)` edge formula can become negative before the wrap at end of tick. Treat this as a **source-derived risk, not a demonstrated audible bug**; add an abrupt-length-change regression before deciding to preserve it. Clock changes retain tick_count_. Source: `firmware/engine.cpp:48-69`, `125-139`, `243-250`.

### Extraction seam and things to omit

Keep Stereo arithmetic; one recorder; ReadSpliced/Wrap; Loop mode processing; history valid/start/size and transport state; divider/clock; dry/wet smoothing; capture/resume transitions; overdub. Remove wet and freeze_history rings, diffusion, Wet(), wet routing, delay heads, wet freeze and chromatic PlaybackRate (only Slip uses that branch). Tick becomes dry recording or Loop(input), then crossfade; Process retains reconstruction/mix with target `loop_on_`. Keep Hothouse controls and USB/peripheral/debug layers entirely outside DSP. The current separation already places them in `main.cpp:37-100`; DSP has no peripheral access, allocation or blocking work (`engine.h:45-46`).

Use explicit listening/playing and overdub levels at the HX parameter interface with transition detection rather than firing a toggle every control update. Existing Hothouse implementation compares requested logical state with actual state before ToggleLoop (`main.cpp:76-80`). Hothouse gestures are not directly portable: they assume one update per 1ms audio block, taps on release and 400ms holds (`firmware/gestures.h:6-7,23-30`). Stomp's 16-sample DSP blocks are ~.333ms, so block-count constants would change real-time behavior.

### Port/reference verification

Existing reference covers exact stereo dry bypass, pre-press capture, silent-input playback, absence of live-input leakage at full mix, dry overdub, 135 mode/routing/clock stability combinations, empty capture, clock zones, and gestures (`tests/engine_test.cpp:14-82`). Splice tests exercise wrapped physical ring starts, all three modes, eight MODIFY zones and two lengths (48 cases), with max adjacent-sample limits (`tests/loop_splice_test.cpp:14-62`). Rerun results here: onset .005189; main repeat .005986; worst48case .023505; all PASS under ASan/UBSan.

For the SHARC port, extract a minimal C++ reference and render deterministic input/event vectors. Compare state transitions exactly; compare sample values with explicitly chosen floating-point tolerances after first measuring reference-vs-SHARC error. Don't assume bit-identical output from a different arithmetic order/SHARC extended precision. `fmod`, `ceil`, `exp2`, integer/floating conversion, modulo and fractional interpolation need explicit SHARC equivalents; the envelope threshold can be precomputed per control update and Tape uses only eight constants. No nonlinear wet DSP is required. Maintain explicit 32-bit rounding where needed for oracle agreement, and keep all state per instance.

Add regressions for full/partial/empty capture at every clock; clock changes during recording and playback; capture/overdub events at 16-sample boundaries; rapid level/length/mode changes; backwards fractional seam reads; L-only/R-only channel isolation; overdub cumulative attenuation and independent write-head semantics; two independent instances; safe init/delete/reset. Cross-source comparison should exclude removed wet recapture behavior. Existing tests are behavior/safety tests, not MOOD sound equivalence (`docs/VALIDATION.md:97-105`; audit `docs/MOOD_USE_CASE_AUDIT.md:7-10,19-29`).

### What still requires research/prototype or hardware

- SHARC memory placement, instance allocator, bandwidth/read staging and code footprint cannot be inferred from Hothouse source.
- Tight upper bound on cost for Stretch plus seam overlap/interpolation and simultaneous overdub requires assembled kernel instruction counts, simulator measurement and on-unit load/timing.
- Abrupt parameter transitions, artifacts and aliasing need rendered audio plus on-unit listening; no evidence that every mode is artifact-free.
- Hothouse validation reports observed callback loads, not Stomp cost or a worst-case bound (`docs/VALIDATION.md:45-58,117-137`).

## Atmosphere source fingerprints

**[verified offline]** SHA-256 of the local source examined, to pin a future extraction:

| File in Atmosphere | SHA-256 |
|---|---|
| `firmware/engine.h` | `de73d92ad04cd35e9af11754363a6da088bb3ab7e5d0177a4a309e7dbfcb4988` |
| `firmware/engine.cpp` | `906e5606cf82c48fa8d2ffe3436427fefad12152025df766cd90657fb58407d1` |
| `tests/engine_test.cpp` | `f0232fd49e8dc2174dbde3953a86f614dc85b3c7691b5d42de17d09514886284` |
| `tests/loop_splice_test.cpp` | `16f1ccac09b0eb4641cb0eb331d605fe879fbe145aff49003156d685451b71f0` |

No production DSP code was changed during this research. The source/ABI/build checks narrow the implementation choices; they do not establish the performance or sound of a SHARC port that has not been written.

## Implementation follow-up, 2026-11-14

**[verified offline]** The looper-only [reference engine](../../../tools/microlooper/reference.h) and [tests](../../../tests/test_microlooper_reference.py) now exist. Direct comparison to the SHA-pinned original Atmosphere engine with wet disabled covers 2,088,960 scalar samples; maximum measured discrepancy 1.49e-8, with 2e-7 absolute test tolerance. The earlier abrupt Envelope LENGTH shrink risk was reproduced against the original source: the stale head made the shortened slice fade negative. The extraction wraps the head before reading/fading; a regression checks the original failure and corrected output. This deliberately corrects that edge case while retaining the other tested behavior.

**[verified offline]** A [gesture routine](../../../src/m4/microlooper_gesture.s) now implements 400 ms tap/hold handling in actual Cortex-M4 assembly, and a [SHARC probe](../../../src/sharc/microlooper_probe.asm) verifies caller-provided stereo ring processing in the simulator. Neither is integrated into firmware yet. The [resource tool](../../../tools/sharc/microlooper.py) reports current profile gaps and separate encoded LDR growth; run `.venv/bin/python tools/sharc/microlooper.py --image build/HX_Stomp_v3.80.0_HXtra.hxf` against the baseline. Native stereo host pointers, switch routing, lifecycle, execution cost and browser admission have not been verified on hardware. See the [execution plan](../../microlooper-plan.md) for the remaining gates.

## Continued port and resource findings

**[verified offline]** The full audio implementation and tests are now in [microlooper_kernel.asm](../../../src/sharc/microlooper_kernel.asm) and [test_microlooper_audio.py](../../../tests/test_microlooper_audio.py). It uses a provisional interleaved caller interface, not an established native stereo bridge. Wrapping now uses bounded binary reduction rather than cancellation-prone quotient multiplication. Effective Overdub state ignores stale levels across capture/listen transitions; duplicate high levels are not fresh commands. This matches the physical single-switch adapter's level transitions.

**[verified offline]** The one-slot NAM layout and simulator/reference checker are implemented. Normal two/three-slot generated assembly is unchanged. The GR placement helper accepts an explicit layout, and the [resource tool](../../../tools/sharc/microlooper.py) reports full audio code fits independently of boot-image bytes. Model registration is tested through actual stock parsing and the native DSP admission function, with no measured cost claimed yet.

**[verified offline]** The RAM loader's partition map resolves the earlier Entry 2 sub-header uncertainty: `(0x8c03 - 0x8803) * 512 = 524288` payload bytes, after the separate header sector. See [hxf_ram.py](../../../tools/hxf_ram.py). Opt-in [zero-data encoding](../../../tools/sharc/ldr_compact.py) preserves the replayed boot memory while saving image bytes. The format is defined in [ADI CCES Loader and Utilities Manual, Table 10-10 and ZERO_INIT Blocks](https://www.analog.com/media/en/dsp-documentation/software-manuals/cces-loaderutilities-manual.pdf); this establishes format semantics, not a new on-device boot result.

**[verified offline]** Native M4 writer, assignment-node matching, selective bypass, periodic tick and restore-filter facts are documented in [microlooper-switch.md](microlooper-switch.md). These narrow the remaining routing work but do not establish complete graph lifecycle coverage. Native DSP buffer layout remains open; see [microlooper-adapter.md](microlooper-adapter.md).


## Native admission and control metadata follow-up

**[verified offline: actual firmware execution]** Admission tests now execute the complete native candidate-budget function at `0x28dfae0c`, the registered image's cost lookup at `0x28e01d50` and limit check at `0x28e01e88`, without pricing stubs. They load the relocated static model table and its patched search bounds from the registered image. Cases cover insertion just below/at/above 9000, replacing a cheaper/equal/more expensive block, and preservation of the current total while browsing. A separate test executes native preset total recomputation at `0x28dfa31c`, clears an existing block's in-use flag, recomputes the total and confirms admission is restored. The test cost 1000 remains structural, not measured DSP load. This qualifies the native accounting path, not the visible menu on hardware. Reproduce with `tests/test_microlooper_model.py` against the stock fixture.

**[verified offline: stock and generated metadata]** Simple Delay Stereo already has seven runtime parameters with `displayParamCount=5`. The micro-looper now retains that display count and writes matching Entry 0 counts `(5,7,7)`: Mode, Length, Modify, Clock and Mix are visible; Play and Overdub remain runtime inputs for the footswitch. This follows the existing metronome's hidden-input technique. Hidden does not mean nonpersistent; transport snapshot exclusion and lifecycle initialization still require native integration and validation.

**[verified offline: boot-stream inventory]** The supplied stock Entry 2 already contains 81 ZERO_LDATA (tag 1) records. Its 45 INIT_L32 records have no additional savings under the current opt-in zero-run rule; all 4604 currently saved bytes come from injected records. There is no basis for claiming more space merely by broadening compaction to stock data. Stock instructions and the boot kernel remain untouched by this tool.


**[verified offline: initial transport qualification]** A newly reset audio instance now ignores restored Play high until a low level has been observed. It remains Listening with valid new recording history; a subsequent fresh low-to-high captures normally. The same rule applies after explicit reset. This protects the first-call case without clearing the whole ring. It intentionally cannot distinguish a real first command issued before any Listen observation from saved state; native initialization must send Listen before physical transport. Snapshot writes on an already armed instance still require native filtering.

**[verified offline: code size and sampled paths]** The exact-arithmetic optimized kernel is 1123 instructions  / 6744 padded raw code bytes, still 153 DM words, with 47 audio differential/qualification tests passing. [microlooper_profile.py](../../../tools/sharc/microlooper_profile.py) reproduces 720 synthetic control/history configurations and fingerprints the source. Current sampled instruction peaks per 16 stereo frames are Listen 3294, Envelope 9581, Tape 7751 and Stretch 13418. They are not hardware cycles, measured DSP percentages or exhaustive worst-case bounds; no memory-stall/pipeline model is claimed. With the NAM1+GR+metronome baseline, opt-in data compaction and registry, the projected Entry 2 is 523604 bytes, leaving 684 bytes before a native bridge. Final bridge fit remains open.


## Diagnostic transport and native float-use follow-up

**[verified offline]** The [diagnostic transport](microlooper-switch.md#diagnostic-context-readback) now spans coherent SHARC source/frame publication, guarded M4 cache and versioned USB/host decode. It is explicit diagnostic instrumentation, not an enabled production effect. The complete telemetry archive fits with1640 Entry2 bytes spare and preserves existing GR fields/audio and callback addresses; full audio/bridge has a separate60-byte projection before initialization. Actual SPI/DMA visibility and on-unit freshness have not been measured.

**[verified offline under parcel-order assumptions]** The [bounded native continuation](microlooper-adapter.md#conditional-visa-buffer-geometry-and-initializer) follows an actual copied incoming word through staging into F4, then F12=F2*F4. Both possible immediate16 extension hypotheses yield identical provenance and float32 results. This advances the conditional planar-float evidence while leaving physical loader order, L/R identity, native allocation/reset and graph lifecycle unresolved. No firmware was executed on a Stomp.

## Completed offline native integration

**[verified offline]** The subsequent [integration record](microlooper-integration.md) supersedes the earlier uninstalled-native boundaries: custom per-instance init/control, actual native allocation/I0 dataflow, installed ownership-aware switch/lifecycle routing, snapshot filtering and NAM-capacity admission are implemented. The complete development HXF builds and verifies with 12 Entry 2 bytes remaining. The DSP constructor discards saved transport levels before first processing, so a new instance starts listening and the first physical capture works. Reload, retained moves, bypass/mode changes and failure cases have native-code regressions. Hardware timing, channel/loader qualification and audio acceptance remain separate; the development flag is excluded from browser/release selection.
