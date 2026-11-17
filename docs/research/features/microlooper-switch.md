# Atmosphere-looper native footswitch and transport routing

Research date: 2026-11-14. Scope: the M4 side of the HX Stomp micro-looper, model ID 380 (`HD2_AtmosphereStereo`). The explicit development build now installs input, polling and lifecycle routing through `HX_MICRO_LOOPER`; it is default-off and excluded from browser selection. Ordinary builds retain their existing behavior. No firmware was installed, no hardware session was opened and no on-unit behavior is claimed here.

Evidence follows [research conventions](../conventions.md). Input is stock HX Stomp 3.80.0, MD5 `a2cd8f4ae56f49415380270ebc484bf1`. Findings come from targeted Thumb disassembly using the installed `arm-none-eabi-objdump`, existing firmware parsers, and Unicorn tests that load original functions directly from the user-supplied fixture. No extracted Line 6 code or data is stored in the repository. Existing system references: [footswitches](../m4/footswitches.md), [snapshots](../m4/snapshots.md), [editor service](../m4/usb-editor.md), and [microsecond clock](../m4/tempo-and-leds.md).

## Transport contract and implemented adapter

**[verified offline: source and Unicorn]** [microlooper.s](../../../src/m4/microlooper.s) consumes the standalone [gesture state machine](../../../src/m4/microlooper_gesture.s). A tap on release alternates Listen/Play. A 400 ms hold during playback enables Overdub until release, without a subsequent tap. Holding while listening does not capture. Mode, Length, Modify, Clock and Mix occupy UI slots 1–5; Play and Overdub are boolean UI slots 6/7, corresponding to DSP parameter IDs 10/11. The native setter's parameter index is zero-based, so transport uses indices 5/6.

**[verified offline: source and Unicorn]** Caller-owned state is 32 aligned bytes: gesture flags/time at +0/+4, block identifier at +8, generation at +12, desired Play/Overdub at +16/+20, dirty bits at +24, and initialized at +28. An immutable 20-byte binding supplies `{context, write_fn, block, generation, model_id}`. State is per binding; there is no singleton enforcement. A new generation resets to Listen/OverdubOff and cannot interpret an old release as Capture. Failed writes retry; failed Play prevents Overdub overtaking it. Cancellation sends OverdubOff before clearing a matching state, leaves failed cancellation retryable and ignores stale generations. This adapter does not itself establish native ownership or generate epochs.

## Installed native controller and lifecycle

**[verified offline: installed Thumb code and actual native functions]** [microlooper_native.py](../../../tools/microlooper_native.py) exposes `install(p, shared_input_hook=...)`. The long-press feature supplies its unbound `(Hook, original_trampoline, lp_event)` tuple; one veneer owns the original key entry. Without long-press enabled, the installer owns the stock entry and passes unrelated events directly to stock. The existing class-3 tick callback runs first, then the controller polls. Selected Atmosphere switches bypass the alternate one-second action while ordinary blocks assigned to that switch still receive PRESS/RELEASE. Tests also execute the actual existing `lp_event` for another switch.

**[verified offline: native storage bounds and controller tests]** The controller has forty 80-byte records, matching native five-switch/eight-assignment storage. Copied kind-1 assignment IDs are deduplicated to one transport per unique block, with a switch bitmask; duplicate nodes cannot double-toggle a block, and assigning one block to two switches combines their pressed levels. This is native storage capacity, not a Atmosphere-instance restriction. Eligibility requires Stomp function2, Footswitch Mode other than2/3, model380, native bypass off, and a native block with in-use/associated flags and a non-null runtime link. The grid-to-object lookup follows the same record/node table as native `0x28e0904c` and the DSP meter.

**[verified offline: stock bypass polarity]** Native `0x28e04514` returns **0 for active and 1 for bypassed**. It calls `0x28e06ab4` at `0x28e04574`; that lower getter calls `0x28dfc244`, which reads node +0x20 bit0, then inverts the byte with `CLZ`/`LSR #5` at `0x28e06afc`/`0x28e06b00` before writing the result. The stock switch dispatcher independently establishes the sense: it loads its newly toggled ON latch at `0x28dd11f2`, inverts it at `0x28dd11f8`/`0x28dd11fe`, and passes that bypass value to `0x28e0f884` at `0x28dd1200`; the same latch selects controller value 1.0 when set and 0.0 when clear at `0x28dd1226`–`0x28dd123a`. Thus ON maps to bypass 0. The direct-stock getter regression executes all three getter bodies, with only lookup and locking boundaries stubbed, and verifies enabled bit0 → bypass1 and enabled bit1 → bypass0. The installed eligibility check uses this proven polarity.

**[verified on unit: manager identity; offline: ROM recursion and bool setter]** The input callback context is a UI listener, not the bypass-assignment manager. The controller resolves the manager through native getter `0x28d96084` (returns `0x28128b4c`) for locking and traversal; pressed-state reads continue to use the UI context. Hardware comparison exposed and corrected the earlier object mix-up; see [the hardware log](microlooper-hardware-log.md). The controller acquires graph mutex first, then assignment-manager mutex; it holds both through discovery and transport writes. Copied-ID access takes the assignment mutex recursively. ROM acquisition `0x10000500` compares the current task with mutex owner at+0 and increments recursion count at+4 for the same task (`0x10000560`). ROM release decrements that count and releases only at zero. Tests execute these ROM bodies and the actual `0x28e04864 → 0x28e02040` setter path while already owning the graph mutex, observing count2 inside the lower writer and count1 afterward. Native full-buffer `0x28df2038` establishes graph-before-assignment ordering during restores; inspected manager graph getters run before manager acquisition, for example `0x28dd596a/0x28dd5978` before `0x28dd59ea`, and `0x28dd72b2/0x28dd72ba` before `0x28dd72e2`. Failure tests verify both controller locks are released.

| Native entry | Installed boundary |
|---|---|
| `0x28dfc2c4(manager, block, descriptor)` | Suspend old overdub before initialization; successful initialization establishes a new epoch even at reused addresses. |
| `0x28df38d0(manager, block)` | Suspend before destruction; native link/in-use changes establish lost ownership, including partial-error cleanup. |
| `0x28e02d40`, `0x28e02ee0` | Suspend the affected model-replacement binding before mutation. |
| `0x28e030bc`, `0x28e03268`, `0x28e03380` | Suspend affected ID ranges before retained-instance moves; retarget surviving runtime links afterward. |
| `0x28e03498` | Suspend the removed block before native removal. |
| `0x28e06b4c(dsp, address, bypassed)` | Cover ordinary UI/MIDI and direct snapshot bypass writes; suspend only on an actual bypass-state transition. |

**[verified offline: real mutation status and ownership tests]** These entries use owned veneers with at most four native arguments. A pre-handler keeps the graph mutex held across the native body; a post-handler receives its real result, reindexes surviving ownership and releases the mutex while preserving native return values. A failed initializer that retains the old runtime link preserves Play and retries failed OverdubOff. A destructor that returns an error after clearing ownership retires old state. Successful initialization and delete/recreate allocate fresh local generations independently of block IDs, node pointers or allocator-address reuse. Every installed transport write rechecks current primary model380 before calling the raw bool writer; a retained native link cannot authorize slot7 writes into another effect.

**[verified offline: eligibility suspension and release tests]** Mode, function, assignment or explicit bypass changes suspend Overdub and disarm held input while preserving playback when the DSP allocation survives. Returning to eligibility never treats an old release as capture; a fresh press after released reassignment works immediately. An unchanged snapshot bypass leaves transport untouched. Native retained-ID move replay preserves Play and generation while retargeting the binding. Destruction/new initialization clears ownership so the next live binding starts Listen/off.

**[verified offline: actual identical-layout reload dispatcher/removal replay]** Full-buffer block application follows `0x28deb1f4 → 0x28deb18c → 0x28e024e0 → 0x28e0e5d0`. The latter reaches `0x28e0b4ec` on every branch, including its equal special-model comparison. That clears ordinary blocks through `0x28df4a98 → 0x28dfcee4 → 0x28df5530 → 0x28df38d0`; only special kind0x16 has preservation logic. Model380 is ordinary kind1. The regression executes the actual dispatcher and this complete ordinary-removal chain with the same incoming model380/grid record, verifies OverdubOff before native unlink, retirement before the rebuild seam and the subsequent model380 rebuild request. Descriptor validation and downstream DSP construction are isolated seams in this replay; native DSP initialization and empty-state behavior have separate tests. Thus an isomorphic full-buffer load does not inherit the old Atmosphere allocation merely because model/slot metadata match.

**[verified offline: linked-image integrity]** The installer appends a versioned runtime manifest. `verify_installed(e0)` requires the exact assembled runtime hash/entry offsets and actual input, tick, parameter/bypass-filter and all nine lifecycle relationships, including native trampolines and real-result/unlock veneers. A marker string alone is insufficient. Shared long-press and standalone installations pass; tampered code, hooks, manifests and duplicate records are rejected. The final DSP linker can require this verification before accepting a Atmosphere image.

**[hardware qualification remains]** Native parameter enqueue/notification and DSP scheduling still need end-to-end on-unit confirmation. Tests execute defined M4/ROM paths with downstream graph messaging isolated; they do not establish audio deadlines, worker scheduling or hardware SPI visibility. M4 graph-lock publication orders the controller after native graph mutation; initial saved-control handling is also enforced by the separate native DSP adapter. No new public effect is claimed hardware-qualified by these offline results.

### Explicit key/tick composition

**[verified offline: source and Unicorn executing the existing `lp_event`]** `microlooper_binding_event(event, obj, route)` now composes one explicitly live binding with the shared long-press ABI, without modifying `long_press.s` or its feature owner. A route is 20 bytes: `{state*, binding*, switch_index, stock_handler, lp_event_handler}`. Unrelated events call the existing `lp_event(event,obj,stock_handler)`. For the selected model-380 binding, PRESS/RELEASE update transport and call stock directly, preserving other blocks assigned to that physical switch. HOLD type 5 is consumed; CLICK type 3 reaches stock directly, avoiding a deferred press replay. Return values are 0 unclaimed, 1 claimed, or 5 claimed with a retryable parameter-write failure.

**[verified offline: source and Unicorn]** `microlooper_binding_tick(event,obj,route)` accepts class 3, reads the native handler's pressed byte at `obj+0x78+switch_index`, reads the proven microsecond clock and updates that binding. A 400 ms hold therefore need not wait for the native one-second HOLD event. Tests execute the actual existing `lp_event` module alongside the router: the looper suppresses its tuner Hold action while another switch retains its tuner action. Failed transport retries do not replay ordinary blocks' presses.

**[verified offline: explicit adapter boundary]** These single-binding helpers remain independently testable. The installed multi-binding controller described above supplies discovery, eligibility, epochs and shared ownership; the helper itself does not infer them. The long-press feature now defers its owned entry to the shared composition when the development Atmosphere feature is selected.

## Native bool parameter writer

**[verified offline: stock callers and actual-code test]** `0x28e04864(tone, block_id, descriptor, value)` is the native outer parameter setter. The ordinary-block path tail-calls `0x28e02040`; special split/merge identifiers can take other routes. Stock controller writes at `0x28dde5b2..0x28dde60c` and the MIDI parameter caller around `0x28d9b2fc..0x28d9b436` establish these records:

| Record | Layout |
|---|---|
| Parameter descriptor | signed selector at +0, zero-based parameter index at +4, flag byte at +8 |
| Packed boolean value | type byte 1 at +0, boolean byte at +1; callers reserve five bytes |
| Other packed values | type 2 integer or type 3 float, four value bytes beginning at +1 |

**[verified offline: disassembly]** Descriptor selector -2 selects the primary model and -3 the secondary model in stock callers. The lower writer `0x28e08454` treats -3 as secondary and other selectors as primary. Its bool branch reads one byte at packed-value +1, forms an aligned typed value and calls graph writer `0x28dfbf54`. The descriptor flag is inverted for that lower call. Flag 0 selects ordinary effect parameters; flag 1 selects native special-control fields. The transport writer must use flag 0. A live hardware test exposed the former flag-1 implementation returning -3 for Play/Overdub; actual native getter regressions now cover this distinction. See [the hardware log](microlooper-hardware-log.md).

**[verified offline: actual-code test]** `microlooper_native_write(tone, block, slot, bool)` rejects slots other than 6/7 and emits descriptor `{-2, slot-1, 1}` with flag 0 plus a normalized packed bool. Tests execute the actual outer setter, ordinary dispatch, preflight getter and graph parameter-space getter against a node with separate special/control counts, verifying that both transport indices reach the normal control space. Additional tests verify exact descriptor/value forwarding. They do not establish the complete DSP transaction or initialization order.

## Bypass Assign traversal and selective bypass suppression

**[verified offline: disassembly and actual-code test]** The native stomp bypass dispatcher is `0x28dd10c0(obj, switch_index)`. Helper `0x28dd71c4` returns the switch's sentinel at `obj + 32*(switch_index+1)`. The first node is the sentinel's word at +0, each node's next pointer is at +0, and traversal ends at the sentinel. The node kind is a byte at +9. Kind 1 enters the block branch at `0x28dd1190`, reads block ID at node +0xc and calls `0x28e0fe94(tone, block, out_info)`. Kind 2 handles switch/controller state; kind 3 handles Command Center. An actual-stock dispatcher test establishes the kind-1 branch and block-ID field.

**[verified offline: disassembly, existing metadata use and explicit-seam tests]** `0x28e0fe94` produces a 52-byte model-info record, with primary preset model ID as an unaligned word at +1. This agrees with the existing [metronome lookup](metronome.md). `microlooper_native_node_match` checks only kind 1, looks up that model and returns its block ID only for model 380. The matcher tests stub the getter; they do not claim stock lookup recognizes an unregistered new model.

**[verified offline: actual getter execution]** An invalid block-ID branch at `0x28e0ff6c` can return success 0 without writing the output record. Success status alone is therefore insufficient. Both the model matcher and transport filter now clear the first eight output bytes before lookup, covering the unaligned model ID. A test executes the actual getter with its ID resolver rejecting the block, verifies the untouched output, and checks that stale stack data resembling model 380 cannot create a false match.

**[verified offline: source, stock accessor disassembly and Unicorn]** `microlooper_native_assignment_ids(manager, switch_index, out_ids, capacity_words)` takes the same `manager+4` mutex as native accessors `0x28dd71c4`/`0x28dd71e4`, copies kind-1 block IDs under that lock, and releases it before any DSP operation. It returns the total number of kind-1 assignments while writing at most the requested capacity. No native node pointer escapes. Tests include mixed node kinds, zero/small/excess output capacity, lock ordering and nodes invalidated immediately at unlock. This establishes a bounded snapshot operation, not that a copied block ID still denotes the same graph after unlocking.

**[verified offline: actual-code test]** `microlooper_native_bypass_filter` is an inline hook at `0x28dd11aa`, after successful model-info lookup and before ordinary kind-1 latch, RGB and bypass writes. Its displaced instruction is the stock four-byte category load. The model ID is then at original stack +29. For model 380, the hook branches to the original next-node path `0x28dd1186`; other models replay the displaced instruction and resume at `0x28dd11ae`. The patch constants and exact stock-byte guard are in [microlooper_native.py](../../../tools/microlooper_native.py).

**[verified offline: actual-code test]** Tests install this hook into the actual firmware dispatcher and run a two-node assignment list. The micro-looper node's latch/RGB remain untouched while the ordinary second block toggles. A non-micro-looper first block follows native behavior. The hook does not unlink or mutate assignment lists and does not own the shared long-press handler. Skipping an entire physical-switch event would lose other assigned blocks/controllers; this hook supplies selective suppression instead.

## A real periodic polling seam

**[verified offline: disassembly]** Callback `0x28dd18b0`, pointed to by literal `0x28dd2950`, is deferred work rather than a periodic timer. Producer code around `0x28dd04ac` sets a bit in `obj+0xc4` under a critical section, then queues the work node `obj+0xb4` through `0x28d96800`. The latter checks whether the node is already queued, links it to a work list and signals a semaphore. The callback exchanges its pending mask with zero and performs requested operations. It does not provide a regular 400 ms polling cadence.

**[verified offline: disassembly and actual-code test]** The stomp already has a class-3 tick listener: literal `0x28dd2944` holds callback `0x28dd1015`. Constructor `0x28dd27fc` registers it with the stomp object as context and event class 3. The key task posts a class-3 event around `0x28db8e70..0x28db8e7c`, sleeps 10,000 microseconds and repeats. Thus its cadence is 10 ms plus work/scheduling time, not an exact realtime deadline.

**[verified offline: actual-code test]** Event dispatcher `0x28db8830` loads callback/context from listener +8/+12 and calls `(event, context)` under its listener-list lock. An actual-code test runs the native class-3 callback and a subsequent test listener, checking callback arguments and preserved native counter updates. The installed controller uses `p.chain_ptr(0x28dd2944, 0x28dd1015, after=...)` for polling while retaining stock tick behavior. This keeps transport handling on the queued event-dispatch thread.

## Snapshot/control-write filter

**[verified offline: disassembly]** Native snapshot-controller writes at `0x28de33ce` and `0x28de349c` call the same outer setter `0x28e04864`. The latter caller stores the result and checks for a negative status at `0x28de34a2`; success 0 follows its ordinary continuation. Other known calls include the controller, MIDI and editor paths, plus the tail wrapper at `0x28df28b8`. This identifies a real filter route; it does not prove all initialization or direct graph writes pass through it.

**[verified offline: actual-code test]** The isolated `microlooper_native_parameter_filter` entry hook permits primary-model-380 transport writes only when incoming LR equals the actual return label immediately following the native setter call inside `microlooper_native_write`. There is no shared allow flag and no cross-thread authorization window. For external primary-model-380 parameter indices 5/6 it returns success 0 without forwarding. Other models, ordinary settings, secondary-model writes and unknown-block lookup failures follow the original setter, with original arguments/registers preserved. The exact entry guard is recorded in `microlooper_native.py`.

**[verified offline: actual-code test]** Tests install the entry hook into actual stock outer-setter code. They verify rejection of external primary transport writes, passage of ordinary settings/other models/secondary-model parameters, native status preservation, and acceptance of the real custom writer's return address. The full snapshot-select function and live DSP delivery are not executed by these tests. Future HX Edit support would need an explicit policy for transport control; this filter currently reserves that native transport route for the one-switch adapter.

**[verified offline: separate initialization boundary]** This filter excludes observed live snapshot/controller setter calls. Initial graph parameters can use a direct graph path, so startup transport suppression is enforced independently by the native DSP adapter; the M4 filter alone is not claimed to cover construction.

## Diagnostic context readback

**[verified offline: encoded SHARC/M4 execution and host decoding; not hardware-qualified]** Context telemetry is now implemented through the established GR SPI-frame transport. It is installed only by the explicit `--telemetry` diagnostic builder, outside feature discovery. It does not register the Atmosphere or change the Acoustic Sim graph, native allocation, initializer, controls or static parameters. The snapshot remains a last-invocation diagnostic; its sequence is not a graph generation or a production instance-count policy.

**[verified offline: encoded source publication]** [microlooper_adapter.asm](../../../src/sharc/microlooper_adapter.asm) reserves the existing 200-word sidecar: context160–175, status saves176–179, source sequence180, publisher saves181–189 and sampler saves192–199. It makes the source sequence odd before any snapshot store and publishes the next even value after the complete snapshot. Zero is valid after wrap. Its 121 instructions take122 loader words /744 loader bytes.

**[verified offline: encoded frame publication and complete GR regression]** The standalone [publisher](../../../src/sharc/microlooper_publisher.asm) validates even source sequence and context magic, copies once and abandons publication if the source changed. Both frame guards become odd before the first tag/count/payload store; commit writes the even end guard before the matching begin guard. It preserves registers, MODE1, ASTAT/STKY and touches only frame219–238. The [GR variant generator](../../../tools/sharc/microlooper_publisher.py) replaces precisely the old62-instruction diagnostic export with a call and61 NOPs. All GR entry/control symbols, its336 DM words /600 PM instructions, marker200, peaks216–217, packed controls218 and window/coefficients250–252 remain unchanged. The publisher adds75 instructions, padded76 /468 loader bytes.

| Frame word | Content |
|---|---|
| 219 | Diagnostic tag/version `0x4d4c0001` |
| 220 | Begin sequence guard |
| 221 | Payload word count16 |
| 222–237 | Sidecar context160–175 |
| 238 | End sequence guard |
| 239–249 | Unchanged; not diagnostic payload |

**[verified offline: native callback composition and Unicorn]** [microlooper_readback.s](../../../src/m4/microlooper_readback.s) normalizes halfword-swapped wire words, checks frame markers/tag/length and matching even guards before and after its private copy. It uses integer operations and barriers; the RX path takes no blocking lock, draws no UI and writes no USB. The first source record is accepted; subsequent records require positive modular sequence progress below half the uint32 range. Duplicate, older and ambiguous records leave both cached context and receive timestamp unchanged. `0xfffffffe → 0` remains valid progress. USB takes a bounded three-attempt stable cache copy into request-local memory, returning explicit no-data on exhaustion. Existing RX and editor-registration chains are retained by [the installer](../../../tools/microlooper_readback.py).

**[verified offline: skeptical review, native RX disassembly and encoded receiver regression]** The diagnostic pre-hook runs before stock callback `0x10001094` rejects older native session/frame headers at `0x100010f6..0x10001102` and `0x10001110..0x1000112c`. Therefore native stream filtering cannot protect telemetry already cached by that hook. The previous equality-only source check admitted a coherent delayed sequence98 after100, replaced the newer context and refreshed its age. A replay of100 refreshed it again without forward progress. The receiver now rejects non-positive signed modular deltas before clock sampling or cache publication. Regressions cover replayed/stale context, ambiguous half-range deltas, uint32 wrap and the signed boundary; no hardware-ordering assumption is required for this guard.

**[verified offline: stock registration scan and emulated editor reply]** Editor-service command **0x51** is now reserved in [usb_commands.py](../../../tools/usb_commands.py) for the explicit diagnostic, with no automatically discovered feature owner. It was absent from the stock110-command registration set. The no-parameter handler reuses the native reply writer, request sequence and stream framing. It returns a MessagePack binary value containing96 little-endian bytes:

| uint32 index | Content |
|---|---|
| 0–1 | Tag/version `0x4d4c0001`, total length96 |
| 2–3 | Valid0/1, source sequence |
| 4–6 | Receive timestamp, current timestamp, elapsed age; uint32 microseconds |
| 7 | Reserved0 |
| 8–23 | Sixteen context words |

No-data zeros sequence/receive time/age/payload and still reports the current clock. Elapsed age handles a single clock wrap but cannot distinguish a full additional71-minute period. Receive age and source sequence do not establish current graph ownership.

**[verified offline: explicit linking]** [patch_microlooper_probe.py](../../../tools/patch_microlooper_probe.py) requires the exact NAM1/mid-sweep code, exact original Acoustic Sim registry and, for telemetry, the exact existing GR code and installed process/control callbacks. It rewrites only the final boot writer of changed GR instructions in place, preserving all addresses and boot-record sizes. It rejects sidecar/code collisions, including PM records that start in another bank, and rejects Entry2 overflow. M4 instrumentation appends through the normal Patch engine and preserves prior finalized chains. Ordinary builds and the canonical baseline HXF are unchanged.

```sh
.venv/bin/python tools/patch_microlooper_probe.py \
  build/HX_Stomp_v3.80.0_HXtra.hxf --telemetry \
  -o build/microlooper-acoustic-telemetry.l6ia \
  --report build/microlooper-acoustic-telemetry.json
```

**[verified offline: host decoder]** [hx_microlooper_probe.py](../../../tools/hx_microlooper_probe.py) issues only the diagnostic request on `HxCtl.ed`, validates the complete versioned reply and context magic, and emits JSON with fresh/stale/no-data state. `--reply FILE` decodes a saved96-byte result without USB. Live use requires the diagnostic running on the unit with HX Edit closed. It does not edit a preset or select an effect. No USB readback has yet been performed on a Stomp.

**[hardware qualification still required]** A running wrapped compressor and Acoustic Sim must coexist in the experimental preset; absent either, no fresh context is expected. Meter thickness zero does not disable GR frame export. On the unit, qualify SPI/DMA ownership and visibility, call-count/sequence advancement, no-data/stale behavior and normal GR/audio operation. The record contains registers and candidate extents, not audio-lane samples or complete native allocation/lifetime evidence. No firmware was RAM-run or flashed, and this diagnostic is not user-testable Atmosphere firmware.

## Staged NAM profile-capacity admission

**[verified offline: native-code execution and assembly]** A reduced NAM profile has a finite shared execution-slot pool independent of declared DSP cost. [nam_capacity.s](../../../src/m4/nam_capacity.s) adds that resource check to native candidate-budget function `0x28dfae0c`. [nam_capacity.py](../../../tools/nam_capacity.py) supplies explicit assembly constants for the compiled profile capacity (1, 2 or 3) and the built image's actual NAM name index; the development feature installs it using registered metadata. This is NAM resource accounting; it adds no micro-looper instance restriction or warning.

**[verified offline: actual native function and its callers]** The wrapper retains the native five-argument ABI: context in r0, preset in r1, replaced block-object pointer in r2, candidate load descriptor in r3, and output admissible-byte pointer as stack argument 5. Calls at `0x28dfffc4` and `0x28e0060a` target that budget function. The native routine sets the output byte, prices the candidate through `0x28e01d50`, computes `preset[0xa88] + candidate_cost - replaced[0x44]` when r2 is present, and calls the original cost limit. The wrapper calls this original routine first, preserving its status and output on pricing errors or native refusals. It only changes an otherwise admissible result to false for a nonempty NAM candidate when adding it would exceed the configured pool capacity. Native kind 0 is treated as empty/removal, even if the descriptor retains a stale NAM name.

**[verified offline: actual total-function execution]** The capacity scan follows the exact object eligibility demonstrated by `0x28dfa31c`: inspect objects at `preset+0xaf0+0x9f4*index`; objects 0–4 participate only when their index is below the byte at `preset+0xac4`, and objects 5–8 always participate. An object counts only when bit 0 at +0x24 is set and primary name +0x54 equals the supplied NAM name index. No meaning for `0xac4` beyond this observed rule is assumed. Replacement refunds one NAM slot only when r2 points to the exact eligible, in-use NAM object that would otherwise be counted. Inactive, excluded and non-NAM replacements do not grant a NAM refund. No preset or block object is modified by the helper.

**[verified offline: tests]** [test_nam_capacity.py](../../../tests/test_nam_capacity.py) passed 98 tests in 4.99 seconds. Tests execute the actual stock table sorter `0x28e01b1c`, pricing function, total function, cost limit and candidate-budget body; there are no cost/total stubs. Two real stock name indices serve as the caller-configured NAM/other identities in these isolated fixtures, without claiming to register production NAM metadata. The matrix covers capacities 1/2/3, full and spare pools, NAM/non-NAM presets, exact replacement refunds, non-NAM and excluded/inactive replacements, removal, original pricing errors and DSP refusals. Non-NAM candidates retain native admission even with a full or overfull NAM pool. A 63-case matrix verifies every object position against the actual native total for `0xac4` values 0–5 and 255. Tests also check stack/register preservation, output-byte bounds and unchanged preset objects.

**[hardware qualification outstanding]** The development installer supplies the image's real NAM name index and compiled capacity through existing native admission calls. Ordinary browser graying and preset/import behavior still need confirmation on the HX Stomp. No object-lifetime or locking guarantee is inferred for arbitrary background callers; ordinary builds do not select this development feature.

## Upstream routes and remaining hardware qualification

**[verified offline: disassembly]** Preset-select wrapper `0x28df02fc` normally calls loader `0x28df22f8`; that takes the graph lock around `0x28df2234`. File-section loading calls block parser `0x28deb18c` at `0x28deb596` and `0x28deb81e`, reaching the same native block-application boundary described above. Editor full-buffer command0x15 takes `0x28df03a8 → 0x28df2038 → 0x28df1fa4 → 0x28deb1f4`. Neither a stable DSP-context pointer nor the high-level preset-select wrapper is used as a generation source.

**[verified offline: disassembly]** Assignment removal `0x28dd60b0(manager,fs,slot)` and tail alias `0x28dd6b94` unlink fixed0x38-byte storage under `manager+4`, then notify after unlocking. Scanner `0x28dd6d60(manager,block)` and UI/editor model wrapper `0x28e0fba0` remain upstream helpers; the installed controller relies on held assignment snapshots and lower native graph initialization/destruction instead of treating these reusable addresses as epochs.

**[verified offline: bounded notification audit]** Native setter `0x28e02040` can call `0x28e054a8`, which builds message0x1406 and synchronously invokes callback `[dsp+0x3b58]`. The common message-post `0x28d99820` allocates a message, copies its data and enqueues through `0x28d93918`; it does not itself wait for completion. The controller tests isolate the dynamic notification callback and native DSP messaging. Their complete callback/worker scheduling and latency under both locks remain on-unit checks, not an inferred guarantee from ROM mutex recursion.

**[hardware qualification outstanding]** Exercise capture/hold timing, ordinary/momentary blocks sharing the switch, snapshots, mode/function/assignment transitions, explicit bypass, same-preset reload, delete/recreate, native error recovery and independent block instances. Confirm initial-control delivery, model lookup/writes against registered metadata, DSP deadlines and absence of lock/worker stalls. There is no Atmosphere-instance count guard or warning.

## Reproduction and validation limits

**[verified offline]** The frozen lifecycle/controller, existing M4 seams, shared long-press and full-feature build regression passed152 tests in15.04 seconds. The default-off development feature is present; ordinary builds retain stock bindings. Reproduce with the user's firmware fixture:

```sh
HX_STOMP_HXF=/path/to/HX_Stomp_v3.80.0_0x103966115.hxf \
  .venv/bin/python -m pytest tests/test_microlooper_lifecycle.py \
  tests/test_microlooper_m4.py tests/test_long_press.py \
  tests/test_tap_color.py::test_builds_alongside_every_other_feature -q --tb=short
```

**[verified offline: test design]** Actual-code tests establish defined routing, native lifetime transitions, register/stack preservation and selective behavior. DSP transactions, dynamic notification callbacks and model-info resolution use explicit downstream seams where stated. These tests do not establish live sound, complete on-unit snapshot behavior or hardware scheduling.
