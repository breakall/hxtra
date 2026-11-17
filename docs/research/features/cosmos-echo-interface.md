# Cosmos Echo as a native effect interface example

2026-11-15 continuation: the allocation/lifecycle trace below now executes the native graph-buffer constructor, exhaustion paths, retained-arena rebuild, reset/teardown dispatch and M4 request/failure handling. Its scope is the resource/lifecycle interface needed by HXtra, not complete Cosmos algorithm reconstruction or hardware qualification. Remaining explicit limits are listed after the trace.

This traces the stock Cosmos Echo model/control graph, rather than designing a replacement effect. **[verified offline]** Source: the user-supplied HX Stomp 3.80.0 image `HX_Stomp_v3.80.0_0x103966115.hxf`, MD5 `a2cd8f4ae56f49415380270ebc484bf1` (recomputed). Nothing here was executed on a unit, and no firmware was modified. All offsets below are in decoded, word-swapped Entry 3/4 payloads unless explicitly identified as Entry 2 SHARC addresses. An Entry 4 word offset is multiplied by four to obtain a byte offset; blob-local and blob-0-local offsets have different bases.

**[verified offline: method]** Container loading used [`kit_patch_amp.load_l6ia_from_any`, `get_entry_swapped`, `parse_entry3_full`](../../../tools/kit_patch_amp.py); graph parsing used [`entry4_blob.directory`, `blob`, `nodes`, `parse_composite`](../../../tools/sharc/entry4_blob.py). Registry records were independently read from the **raw, unswapped** Entry 2 LDR through [`microlooper_adapter.ldr_blocks` / `ldr_word`](../../../tools/sharc/microlooper_adapter.py). The parameter map was followed from its slot table through its four-word directed edge records to its writer nodes; the relevant format descriptions are `kit_patch_amp.nam_host_blob` and [`patch_comp.pmap_sizes` / `core_paths`](../../../tools/patch_comp.py). These are static parsing observations, not proof that every parameter-map opcode has been implemented correctly in an emulator.

**[verified offline: validation]** Independently checked identity, every Entry 3 default raw word against root kind-1 post-init, exact equality of declared and mapped slot sets, node IDs and all edge bounds for both variants. Local document links resolve. The read-only reproducer is [`tools/sharc/cosmos_echo_trace.py`](../../../tools/sharc/cosmos_echo_trace.py); it also contains the companion bounded native allocation/binding probes.

## Model identity

**[verified offline]** Entry 3 binds a model identity to a separate Entry 4 graph blob through descriptor word 13:

| Fact | Mono | Stereo |
| --- | --- | --- |
| Internal name | `HD2_DelayCosmosEchoMono` | `HD2_DelayCosmosEchoStereo` |
| Display name | Cosmos Echo | Cosmos Echo |
| Entry 3 model ID / blob index | 113 / 113 | 400 / 400 |
| M4 static-table preset ID | 394 | 395 |
| Native declared DSP cost | 1060 | 1920 |
| Entry 3 descriptor byte offset | `0x1b3b8` | `0x1f280` |
| Internal-name string index | 1148 | 2813 |
| Parameters / states | 15 / 15 | 16 / 16 |
| Displayed parameter count | 13 | 14 |
| Category / subcategory | delay / mono | delay / stereo |
| Additional metadata | `type=tape`, `Z=10K` | `Z=10K`; no `type` metadata |
| Entry 4 blob start, words | `0x9d00f` | `0x10f7e5` |
| Blob length, words | 2925 | 4890 |
| Root composite | `0x600102` | `0x60005a` |
| Node tree offset / records, blob words | `0x111` / 22 | `0x1ff` / 43 |
| Parameter-map offset / length, blob words | `0x169` / 1872 | `0x2ab` / 2893 |
| Post-init offset / records, blob words | `0x8b9` / 103 | `0xdf8` / 195 |

The name string index, public model ID, graph blob index, composite type and primitive registry ID are distinct namespaces even where two happen to have the same numeric value.

## Parameter and persistent-state schema

**[verified offline]** Typed Entry 3 records occupy `0x4ed98..0x4ef78` (mono; 15 records, 32 bytes each) and `0x5ff38..0x60138` (stereo; 16 records). Interpret the last three record words by the parameter's type: type 3 is float, type 2 integer, type 1 boolean. `parse_entry3_full` prints all three as floats, which hides the actual Mode/SyncSelect integer bounds and defaults. The following table uses typed values and independently checks every default against the blob's root post-init records.

| Slot | Preset/state-facing name | Type | Range | Mono default | Stereo default |
| --- | --- | --- | --- | --- | --- |
| 1 | Time | float, seconds | 0.15..2 | 0.6 | 0.6 |
| 2 | Ramp | float, knob | 0..1 | 0.75 | 0.75 |
| 3 | Feedback | float, percent display | 0..1 | 0.40 | **0.38** |
| 4 | WowFlutter | float, knob | 0..1 | 0.5 | 0.5 |
| 5 | Mix | float, percent display | 0..1 | 0.5 | 0.5 |
| 6 | Level | float, dB | -60..6 | 0 | 0 |
| 7 | Headroom | float, dB | -12..12 | 0 | 0 |
| 8 | Mode | integer list | 0..5 | 4 | 4 |
| 9 | Bass | float, dB | -18..18 | 0 | 0 |
| 10 | Treble | float, dB | -18..18 | 0 | 0 |
| 11 | FBTone | float, knob | 0..1 | 0.38 | 0.38 |
| 12 | Splice | float, knob | 0..1 | 0 | 0 |
| 13 | DryThru | boolean | record bounds 0,0 | false | false |
| 14 | Spread | float, knob | 0..1 | absent | 1 |
| 23 | TempoSync1 | boolean | record bounds 0,0 | false | false |
| 24 | SyncSelect1 | integer note list | 1..19 | 6 | 6 |

**[verified offline]** Mode values 0..5 select Head 1, Head 2, Head 3, Head 1 3, Head 2 3, Head 1 2 3 respectively; default 4 therefore selects Head 2 3. SyncSelect1 values 1..19 run from 1/1 through dotted/straight/triplet subdivisions to 1/64 Triplet; 6 is 1/4. Its metadata has `persistent=note`. Time has `sync=1`, `coupledIndex=24`, `toggleSelectIndex=23`; SyncSelect1 couples back to slot 1 with the same toggle. Thus a synced Time control is three parameter slots, not one float sent directly to DSP.

**[verified offline]** State records begin at Entry 3 `0x29dec` mono and `0x34738` stereo, with 20 bytes per record. Their order is Mix, Feedback, Time, Level, WowFlutter, TempoSync1, SyncSelect1, Headroom, Mode, FBTone, Ramp, Splice, Bass, Treble, DryThru; stereo appends Spread. State indices are zero-based in that order. They are **not** the parameter descriptor order or slot order. Parameter-map table E agrees with the state order: input node 2 maps to state 0 (Mix), node 8 to state 2 (Time), node 64 to state 10 (Ramp). Table D is ordered by parameter slot; its second word follows that table's ordinal, so it must not be blindly treated as the Entry 3 state index for Cosmos Echo.

**[verified offline]** Root post-init kind-1 records contain one default for every exposed/hidden slot. Root default value words are blob-local `0xea..0x106` mono and `0x1ca..0x1e8` stereo, every two words, in state order. Separately, both blobs have a root pid-0 kind-2 initialization with integer value 1 (value word `0x28` mono / `0x3e` stereo). This root initialization is distinct from the DryThru slot-13 default. **[unknown]** This investigation did not round-trip an actual preset file; descriptor/state names and the `persistent=note` declaration establish the native schema, not full serialization semantics or retention across power cycles.

## Actual parameter-map edges

**[verified offline]** The mono map has 91 nodes, 90 edges, 15 slot entries and 15 persistent-state entries; stereo has 138 nodes, 152 edges, 16 slot entries and 16 state entries. Its input nodes are shared by number across variants: Time 8, Ramp 64, Feedback 6, WowFlutter 33, Mix 2, Level 30, Headroom 44, Mode 53, Bass 82, Treble 83, FBTone 61, Splice 75, DryThru 89, TempoSync1 41, SyncSelect1 42; stereo Spread is node 92. Float/int/bool inputs use opcodes `0xa`/`0xb`/`0xd`. A writer is opcode 1 with a target path, target pid and mode; its target pid generally differs from the public parameter slot.

The following is directed **reachability**, not an assertion that each intermediate opcode is an arithmetic identity. `[k]` means path slot k, composite member index k-1. `pN` is a primitive control pid.

| Public input | Mono reachable writer destinations | Stereo reachable writer destinations |
| --- | --- | --- |
| Time, Ramp, TempoSync1, SyncSelect1 | `[6,7,8].p1`; `[24].p3` | `[24,25,26,6,7,8].p1`; `[46].p3` |
| WowFlutter, Splice | `[6,7,8].p1` | `[24,25,26,6,7,8].p1` |
| Feedback | `[22].p2` | `[44,51].p2` |
| Mix | `[18].p1,p2` | `[38,18].p1,p2` |
| Level | `[19].p1` | `[39,19].p1` |
| Headroom | `[2,19].p1` | `[20,2,39,19].p1` |
| Mode | `[9].p1,p2,p3` | `[29,9].p1,p2,p3` |
| Bass | `[14].p3` | `[34,14].p3` |
| Treble | `[15].p3` | `[35,15].p3` |
| FBTone | `[21].p2` | `[42,50].p2` |
| DryThru | root `[0].p0`, writer mode 0 | root `[0].p0`, writer mode 0 |
| Spread | absent | `[6,7,8].p1` |

All non-root destinations in this table use writer mode 1. In mono the table ends at blob word `0x505` (node 90); stereo's extra processing/writers continue through node 137 at blob word `0x81d`. Table C begins at map-relative word `0x4c8` mono / `0x71d` stereo; table D at `0x630` / `0x97d`; table E at `0x66c` / `0x9bd`.

### Tempo, ramp and delay-head path

**[verified offline]** Both maps contain these exact directed dependencies, expressed as `(source node.port → destination node.port)`:

- `41.0 → 43.0`, `42.0 → 43.2`: TempoSync1 and note select enter opcode `0x2a` node 43. Its two data values are zero; port 1 has no incoming edge.
- `8.0 → 60.0`, `64.0 → 65.0 → 60.1`: Time and a Ramp-driven table node meet in opcode `0x3a` node 60 (data endpoints 0 and 100).
- `60.0 → 48.0`, `43.0 → 48.1`: opcode `0x54` node 48 combines that branch with the tempo branch; its data bounds are 0.15 and 2.0 seconds.
- Node 48 fans into nodes 72, 67, 51, 52, 37 and 35. The data of nodes 51/52 include 0.6666/0.3333; the downstream network also combines WowFlutter and Splice before the three delay-head writer nodes.
- Mono writer nodes 9/49/50 target `[6]/[7]/[8].p1`; corresponding stereo nodes target `[24]/[25]/[26].p1`, and additional writer nodes 101/102/103 target `[6]/[7]/[8].p1`.

**[inference / not executed]** The structure is consistent with a ramped, tempo-selectable tape-time control feeding three head offsets with modulation, with stereo Spread entering only one head bank. Opcode `0x2a`'s tempo meaning and `0x54`'s selection/clamp role are supported by the earlier [Simple Delay / Metronome investigation](../sharc/model-blobs.md), but this trace does not independently establish the numerical behavior of `0x3a`, the table interpolation, every modulation opcode, or their update rates. Replacing the entire map with a direct Time-to-head writer would discard observed native behavior.

### DryThru and the spillover boundary

**[verified offline: bounded negative search]** Neither model's parameter names, state names or table-D slots contain Trails, Spillover, or a separate bypass/trails toggle. DryThru is directly connected `89.0 → 90.0`; writer 90 targets root path `[0]`, pid 0, mode 0, unlike ordinary child control writes. Its record is mono blob word `0x505` / stereo `0x647`.

**[unknown]** The model/control graph alone does not establish whether root pid 0 means enable, dry routing, bypass behavior, or a related framework operation. Nor does absence of a Trails slot establish absence of trails: that policy can belong to the surrounding effect harness or application model. A replacement-effect interface should keep root/framework commands separate from child control pids and expose a deliberate lifecycle/bypass/tail policy. Actual tail continuation, clearing, preset transitions and spillover timing require the native framework trace and eventually runtime evidence; this static graph does not verify them.

## Effective DSP graph and registry mapping

**[verified offline]** Blob 0 begins at Entry 4 word `0x6c6`. Its composite table rows are blob-0-local `0x1883` (mono) / `0x13eb` (stereo); member records start at `0x2ed83` / `0x1291f`, 20 words each. Every child entry in both model node trees has type `0xffffffff`: the model inherits all base composite primitive types. There are no Cosmos-specific substitutions hidden by looking only at Blob 0. This check matters because [other stock models do override their base members](../sharc/model-blobs.md#the-node-tree).

| Primitive | Mono paths | Stereo paths | Mono/stereo instances |
| --- | --- | --- | --- |
| `0x80` | 2,19 | 2,19,20,39 | 2 / 4 |
| `0x89` | 18,22 | 18,38,44,51 | 2 / 4 |
| `0x102` | 3,10–15,21,23–25 | 3,10–15,21,30–35,42,45–47,50,52–54 | 11 / 22 |
| `0x258` | 9 | 9,29 | 1 / 2 |
| `0x832` | 4,26 | 4,22,48,55 | 2 / 4 |
| `0x2397` | 6,7,8 | 6,7,8,24,25,26 | 3 / 6 |
| `0x2394` | 27 | 49,56 | 1 / 2 |

**[verified offline]** Mono has 27 members, 22 primitive instances; stereo has 56 members, 44 primitive instances. Mono's flag-4 input-port record has one output-buffer reference, and its flag-8 output-port record one input-buffer reference. Stereo's corresponding records have two each. These port records establish mono/stereo structural width. Do **not** interpret the helper's `n_out` label as physical output-channel count: the composite header's second word is 6 mono / 11 stereo, corresponding to numbered working audio-buffer references, whereas the output-port record width is 1 / 2. Both first header words are 1. This trace preserves those raw-field distinctions rather than repairing the shared parser's schema.

**[verified offline]** In mono the buffer-reference path runs through input gain `[2]`, filtering `[3]`, nonlinear stage `[4]`; three zero-audio-input primitive instances `[6,7,8]` produce references 2/3/4, consumed by `[9]` (three inputs, one output). A filtered branch passes through Bass/Treble targets `[14,15]`, dry/wet taps and Mix target `[18]`, then Level `[19]` to the output-port record. The feedback branch uses FBTone `[21]`, Feedback `[22]`, filtering `[23,24,25]`, nonlinear stage `[26]`, then `[27]` (one audio input, no audio output). This is the structural evidence for treating `0x2397` as delay readers and `0x2394` as the writer, pending native buffer-binding/code evidence. Stereo has two such primitive banks and additional cross-bank taps; its primitive multiset is exactly twice mono's, while its control graph is shared and extended, not two independent mono parameter maps.

**[verified offline]** Registry lookup gives the following actual native entry addresses and declared per-instance word counts. DM/PM here are the registry fields, not graph-wide totals or a zero-SDRAM assertion.

| Primitive | Registry DM address | Init | Control | Process | DM / PM words |
| --- | --- | --- | --- | --- | --- |
| `0x80` | `0x200298` | `0x60f710` | `0x60f3e2` | `0x8d7f5` | 2 / 1 |
| `0x89` | `0x200330` | `0x610224` | `0x61017a` | `0x8da28` | 2 / 2 |
| `0x102` | `0x200040` | `0x60aceb` | `0x60ac56` | `0x8ce8a` | 9 / 4 |
| `0x258` | `0x2001f8` | `0x60e763` | `0x60e6f2` | `0x8d5c5` | 3 / 0 |
| `0x832` | `0x200470` | `0x61283e` | `0x612045` | `0x8dffd` | 32 / 22 |
| `0x2397` | `0x200100` | `0x60c3e8` | `0x17a872` | `0x8d151` | 5 / 6 |
| `0x2394` | `0x200110` | `0x60c4c0` | none | `0x8d1a4` | 3 / 0 |

Registry word 3 is nonzero for `0x102` (`0x60ad36`) and `0x2397` (`0x60c2e5`); describing every registry record as having two unused zeros would lose these entries. The continuation below establishes word 3 as reset and word 2 as teardown through native call sites and execution. The generic control ABI already researched in [registry.md](../sharc/registry.md) remains separate evidence; this graph proves the destinations without executing every control pid's numerical interpretation.

**[verified offline]** Graph-buffer descriptor lists are at blob-0-local `0x2efde` mono (one record) / `0x12e07` stereo (two records). Their capacity fields are 384000 mono / 192512 per stereo record. Individual primitive member SDRAM fields being zero therefore cannot establish that Cosmos Echo has no large memory allocation. Native allocation and connection semantics are handled by the companion resource investigation.

## Provisional interface contract and remaining limits

**[inference from the verified structure]** A useful effect boundary has at least five distinct pieces: a named model/schema with stable public slots and typed state; a graph binding with inherited or overridden member types; a control graph that transforms public values into child pids and root commands; declared instance/graph-buffer resources; and native init/control/process/lifecycle entries. Mono/stereo identity and widths are explicit, while a stereo model may share control computations across two primitive banks. Persisted state order, UI order, public slots and native pids cannot be merged into a single index.

**[scope]** Cosmos Echo provides a concrete descriptor/control-graph linkage and an executed resource/lifecycle example for an effect interface. The native allocation, binding, arena rebuild, reset/teardown and admission/failure evidence follows. Remaining limits include complete graph boot/publication, physical sample-pointer layout, parameter-map opcode semantics/update scheduling, root commands/tails and hardware behavior. Only the stock buffer writer was sample-tested; the complete Cosmos audio algorithm was not rendered. No hardware was accessed and no patched image was created.

## Native memory declaration and executable buffer binding

**[verified offline: source extraction and original constructor replay]** Primitive members request a total of **192 DM / 112 PM words** in mono, **384 DM / 224 PM words** in stereo. Every primitive's DM/PM request matches its actual registry row. All member field-15 SDRAM requests are zero, but the graph has separate large-buffer records: one candidate span of **384,000 words** in mono, two of **192,512 words** in stereo. These primitive totals exclude framework descriptors, parameter-map state, working audio buffers, alignment and the graph buffers. They are not total preset memory usage. The native member-carving spans at `0x177f8c..0x17801d` were replayed for all seven distinct primitive declarations; each fits the supplied parent arenas and preserves descriptor guards. This establishes child carving, not complete outer-graph allocation. Reproduce with [the trace tool](../../../tools/sharc/cosmos_echo_trace.py).

**[verified offline: original init callbacks]** Primitive `0x2394`'s initializer at `0x60c4c0` follows instance-descriptor word 36 to a buffer-binding record. It reads binding word 0 as a cursor pointer, word 4 as the ring base and word 5 as the circular length. It stores those values into its three private DM words and initializes the shared cursor to the ring base. Original initializer `0x60c3e8` for `0x2397` clears five private DM and six PM words, consumes the same binding, and retains the cursor pointer and ring base/length in its own state. Both callbacks return through an actual native C caller replay with balanced frames and state guards. The initial callback probe supplies the descriptor and binding; the continuation below separately executes the original constructor that creates those bindings from Cosmos declarations.

**[verified offline: original writer process]** The actual `0x2394` process at `0x8d1a4` uses the stored ring base/length as circular addressing registers. With explicit input I1/B1, scalar/CBUFEN context and a supplied external ring, it copies all 16 distinct float words exactly, advances the shared cursor by 16, and wraps at the last block without touching either ring guard. The probe covers both graph-record candidate lengths. A crucial distinction is that binding word 5 is a **length**, not an end address. These are bounded native process tests against synthetic pointers, not physical audio-lane or device-timing qualification. The writer/readers share one binding within the graph; they do not each request an independent delay ring from their primitive SDRAM field.

**[inference]** This is a useful native interface pattern: declare a graph-owned buffer once, then bind several small primitives to it. Resource accounting must include graph buffers as well as each primitive's private memory. Simply summing registry DM/PM fields or primitive SDRAM requests would substantially undercount Cosmos. The shared allocation is local to an effect graph instance; these probes do not establish cross-instance sharing or global buffer ownership.

## Native model eligibility, DSP admission and failure semantics

**[verified offline: stock descriptors and original ARM execution]** Cosmos's actual browser descriptors have kind 8. Mono is Delay category 6 / mono subcategory 0 / item 9 at M4 `0x28011580`, with name index 1148 and preset ID 394; stereo is category 6 / stereo subcategory 1 / item 13 at `0x28011a90`, name 2813 and preset ID 395. Actual pricing at `0x28e01d50` returns costs **1060 / 1920**. The stock table's native boot sorter at `0x28e01b1c` was executed before its binary-search pricer. This avoids treating the unsorted on-disk table as its runtime arrangement. Existing [M4 replay infrastructure](../../../tests/test_nam_capacity.py) supplies the isolated test memory; every reported budget call enters the untouched stock function, not the NAM wrapper.

**[verified offline: 26 admission scenarios]** Original `0x28dfae0c` accepts the mono candidate at current total 7940 and rejects 7941; stereo accepts 7080 and rejects 7081. Each accepted threshold totals 9000. At current 9000, replacing a block of the candidate's own cost permits the change; refund one less and it refuses. Browsing leaves preset and descriptor unchanged. Actual pricing writes the same object cost field used by the constructor (`block+0x44`); native total recomputation gives 1500 plus the Cosmos cost, and clearing the object's in-use flag restores 1500. Crowded-preset cases become admissible after native removal/recomputation. Current/replaced objects are supplied fixtures; these checks do not execute the complete native insertion/removal operation.

**[verified offline: error contract]** Invalid kind returns -3, and an unknown model name returns -21, while the initialized admissible byte remains 1. Therefore an integration must preserve **status plus admissibility**, rather than treating the boolean alone as success. A kind-0 removal ignores a stale model name. The scalar budget refunds `replacement+0x44` for any non-null replacement pointer; valid ownership/eligibility is the caller's obligation, not something this function verifies. Native call-site inspection finds the cost-field installation at `0x28dfc78c`, and the load path's false-admissibility handling at `0x28e00108` writes output handle -1 and returns -19.

**[verified offline: separate eligibility check, 20 scenarios]** Both native load (`0x28dfff8a`) and query (`0x28e005ee`) call `0x28dfa9a4` before DSP admission. The complete precheck `0x28dfa9a4..0x28dfac17` was executed for both actual Cosmos descriptors with instrumented reads. On the Cosmos kind-8 path it reads only the candidate kind byte, three existing type counters at preset offsets `0xa90/0xa94/0xa98`, and the replacement kind when present. Counters at 2 accept; any counter at 3 refuses unless replacing the corresponding counted kind refunds it. Saturating unrelated I/O masks and the looper counter, or changing every descriptor field after the kind word, does not affect these Cosmos outcomes. It does not read a model name, graph, size declaration or allocator capacity on this path. This is **type-count eligibility**, not evidence of a general Cosmos memory-budget calculation. Other kind paths contain I/O and looper rules; those paths were statically inspected, not exercised by these Cosmos cases.

**[verified offline: evidence scope]** Scratch results are `build/cosmos-admission.json`, including source Entry 0 SHA256, all 46 cases and residual limits. Native scalar-budget disassembly was independently corroborated through REA using an exact extracted ARM Thumb ELF wrapper, whose binary round-trip was checked against the supplied stock slice. Retained parent evidence ID: `ev_316b01bf31d37eea15d2778a5f7bb32bf98f830779e121475fe5d25a556dc299`. No device code was executed. The continuation below establishes local failure propagation and the remote-status discard boundary; it does not substitute a transport failure for a SHARC allocation outcome.

## Allocation, ownership, reset and replacement

**[verified offline: original constructor]** [cosmos_echo_allocation.py](../../../tools/sharc/cosmos_echo_allocation.py) executes `0x177e1a` through `0x177f22` with the actual mono/stereo header and buffer declarations, relocated into explicit fixture memory. The fifth C argument is a parent containing nine arena triples; R4 is output composite metadata, R8 its header, and R12 its identity. Before creating members, native code reserves member vectors, 37-word descriptors per member, working audio storage and six-word buffer bindings. These are real metadata demands in addition to primitive DM/PM sizes. Header word 4 supplies the number of graph buffers and word 5 their four-word declaration list.

**[verified offline]** Each Cosmos buffer declaration requests **one DM word for a cursor, zero PM words and its external ring span**: 384,000 words in mono, 192,512 per stereo ring. The buffer loop reads the DM/PM/SDRAM requirements, carves the corresponding parent arenas, creates a six-word binding with each base/count, and zero-initializes the small cursor allocation through stock helper `0x8c6cf`. The ring itself is not cleared by this constructor prefix. Both stereo bindings are disjoint; their cursor allocations are distinct. A plugin must explicitly initialize validity/state before reading old ring contents rather than assume newly reserved history is zero.

**[verified offline: 12 composed native joins]** The continuation in [cosmos_echo_lifecycle.py](../../../tools/sharc/cosmos_echo_lifecycle.py) joins those constructor-created bindings to all real Cosmos reader/writer records, without manually assigning their binding pointers. Native `0x177f6e` reads member word 19 as the one-based buffer selection; `0x177f73` reads the constructed composite's binding table at word 5; `0x177f75/7c` selects its six-word entry; `0x1780b7` writes the child's word 36. The actual initializer then consumes that word and binds to the allocated cursor, base and length. Mono readers/writer use ID1. Stereo paths 6/7/8/56 use ID2; paths 24/25/26/49 use ID1. Member-arena carving and initialization execute on the same machine state as buffer creation. The selected-member traversal context and native-reserved descriptor address are supplied explicitly; the full graph traversal is not emulated.

**[verified offline, conditional immediate interpretation]** Ten constructor scenarios cover both variants: exact-fit success under both immediate-extension interpretations, plus independent DM-cursor, SDRAM-ring and binding-metadata exhaustion under the signed-immediate interpretation used by the native C error path. Every exact-fit allocation matches the declarations; every exhausted case returns through the original epilogue without writing the ring or crossing guards. The signed-model errors are -31075 for cursor DM, -31107 for ring SDRAM and -31349 for binding metadata. Successful allocation is identical under both extension hypotheses. Negative 16-bit immediate sign extension remains explicit in the decoder; choosing zero extension changes the firmware's subsequent signed-error test. These error replays are conditional on that interpretation, not a hardware proof of an undocumented encoding detail. The decoder follows [ADI Programming Reference rev2.4, Types16b/17b](https://www.analog.com/media/en/dsp-documentation/processor-manuals/ADSP-2136x_2137x_214xx_pgr_rev2.4.pdf), with eight additional independently assembled Type16b tests preserving default rejection when extension is unspecified.

**[verified offline: original parent-copy and replacement paths]** [cosmos_echo_lifecycle.py](../../../tools/sharc/cosmos_echo_lifecycle.py) executes selector `0x1779ed → 0x177a2a → 0x177d3d`. The enclosing constructor copies the retained descriptor's first 27 words into stack-local allocator state through native memcpy at `0x177d67`; it then makes each local arena begin/current equal to the **retained current**, while preserving its end. The retained descriptor's nine triples remain unchanged. Repeating this prefix after dirtying all local triples reconstructs the same ranges. The task-level copy at `0x178a1c..0x178a55` similarly derives task-local arenas from retained global current/end values. These checks deliberately use different retained begin/current values so they cannot accidentally prove a reset to the wrong frontier.

**[inference from composed native spans]** Allocation failure may leave advanced cursors in the disposable local copy; it does not by itself consume the retained reservation permanently. Reconstructing the same descriptor recovers the same available ranges. That is the demonstrated replacement model, not an individual `free(buffer)` interface. Native replacement `0x178636 → 0x17871a → 0x178642 → 0x1779ed` executes teardown and re-enters construction using the same descriptor. Creation/reclamation of the outermost global reservation is outside these bounded spans; no general-purpose global free-space meter is implied.

**[verified offline: registry and lifecycle dispatch]** Native linkage `0x177a55..0x177a7e` copies registry words 1..5 into descriptor fields 31..35; null hooks become native no-op `0x1779e7`. Reset traversal `0x177b87` recurses composites and calls descriptor field 33, so registry **word 3 is reset**. Actual `0x2397` reset only clears PM[3]; actual `0x102` reset zeros PM[0..3]. Teardown traversal `0x17871a` calls field 32, so registry **word 2 is teardown**. All seven Cosmos primitive teardown hooks are null/no-op; none individually frees or clears the delay ring. Synthetic two-child graphs execute the actual recursive traversals. Descriptor flags gate reset/teardown behavior; the flag-8 framework call at `0x175ab9` remains an explicit boundary, rather than an assumed arena free.

## M4 request, local failure and remote-status boundary

**[verified offline: 43 native replay cases]** [cosmos_failure_trace.py](../../../tools/cosmos_failure_trace.py) follows native graph creation through `0x28df35d8 → 0x28da8148 → 0x28da79e0 → 0x28da9f44`, then the virtual creation entry `0x28da7190 → 0x28da7090`. Native packaging emits opcode 3 with token **-2**, a graph handle and the blob payload. The enclosing method invokes its previous-graph release interface before sending and clears its old local allocation fields. The actual release entry `0x28da7200` packages opcode 15; the replay observes the release-interface invocation without claiming to execute remote storage reclamation. Negative local stream-write results return unchanged.

**[verified offline: conditional local failure propagation]** Both real Cosmos descriptors were exercised through native construction, new insertion, in-place replacement, existing-block preset application and new-block preset application, with explicit negative local graph-create results -19, -42 and -4. Failed new insertion cleans its M4 handle mapping and clears the in-use bit. Cosmos-to-Cosmos replacement reuses the M4 block, disables the slot and attempts construction; a negative result returns without re-enabling or restoring the old graph. Existing-preset application takes this replacement path; absent-block preset application takes insertion. This disproves an atomic old-effect rollback guarantee for these paths. The injected failures are local call outcomes; they are not labelled remote allocator results.

**[verified offline: receiver execution]** Native receiver `0x28da7adc` checks a message token at `0x28da7b14..1c` and skips dispatch for token -2. Six cases use tokens -2 and 42 with statuses 0, -19 and -31107. A matched token 42 enters `0x28da6dc0`, stores the exact signed status in the pending record and signals it; token -2 leaves the pending result unchanged. The create request and receiver were executed separately. No actual wire reply from a failed SHARC graph was observed, and no substitute SHARC reply handler was invented.

**[consequence]** This native creation path's immediate success means the local request was accepted/sent; it is not a verified DSP allocation acknowledgement. Browser eligibility/DSP admission and successful transport therefore cannot serve as a general runtime memory-safety guarantee for arbitrary new effect declarations. HXtra must validate resource declarations against the actual enclosing native reservations before allowing such effects, or establish an explicit acknowledged construction path before promising recoverable allocation failures. Likewise, the interface must not promise automatic restoration of the previous effect on failed replacement.

## Effect interface implied by this trace

**[design proposal, not an implemented SDK]** The smallest useful package contract should generate native structures for these five concerns:

| Package declaration | Native Cosmos evidence | HXtra responsibility |
| --- | --- | --- |
| Model and state schema | Separate name/preset/blob IDs; typed defaults; UI, slot and state orders differ | Generate consistent model tables, parameter descriptors and persisted-state mappings from one declaration. |
| Processing and control graphs | Shared primitives; separate stereo graph; tempo/ramp/modulation graph; root versus child writes | Describe ports, member bindings and control transforms explicitly; preserve framework command semantics. A single primitive remains a valid simple graph. |
| Instance resources | Primitive DM/PM plus graph-owned delay rings and cursor bindings; retained reservations and local carving | Count every owner and metadata pool, fit the enclosing native reservation, and initialize dirty history safely. The framework owns arenas; effect code uses bound storage. Keep executable-code placement separate. |
| Native callbacks | Distinct init, reset, teardown, control and process entries | Generate correct registry linkage, preserve calling conventions and define reset independently of destruction. Do not free framework-owned arenas from a primitive's teardown hook. |
| Admission and errors | Kind eligibility, scalar DSP cost/refunds, status plus boolean; fire-and-forget construction | Reuse native policy, validate memory declarations before construction and distinguish transport success from DSP readiness. Do not promise atomic replacement rollback. |

**[interface design consequence]** The resource/lifecycle interface can now be designed around explicit native facts: a supplied retained reservation; a disposable constructor allocator; graph-local buffer declarations and bindings; separate reset/teardown; and a creation request whose local return is not an allocation acknowledgement. A dynamic global memory ledger or general `free` interface is not established by this trace. The earlier proposal to infer automatic resource refunds or failure rollback from the native browser must be narrowed accordingly.

**[remaining limits]** Native code spans execute against explicit context, with the parcel/immediate assumptions recorded by each probe. Complete graph scheduling/publication and outermost global reservation creation/reclamation are not simulated. The physical SHARC request/reply transport, audible tails, root pid-0 meaning, complete control-map numerical behavior and on-unit timing remain unverified. These limits prevent hardware-readiness or a fully reconstructed Cosmos implementation claim; they do not require inventing a different ownership/error contract for the proposed effect-package interface.

**[validation checkpoint, 2026-11-15]** The aggregate SHARC reproducer passes 10 graph-buffer allocation scenarios, 12 real-member binding/initialization joins, seven primitive lifecycle cases and the recursive traversal/arena-rebuild probes. The separate M4 reproducer passes 43 request/failure/receiver scenarios. Affected VISA, native allocation/init, SHARC simulator and documentation tests: **162 passed in 3.34s**. `git diff --check` passes. Source firmware and experimental Atmosphere firmware were not modified, and no device action was performed.

Reproduce the maintained declaration/allocation/buffer probe without changing firmware:

```sh
.venv/bin/python tools/sharc/cosmos_echo_trace.py /path/to/HX_Stomp_v3.80.0_0x103966115.hxf > build/cosmos-echo-trace.json
# Native M4 request/failure replay uses the repository's Unicorn test harness.
.venv/bin/python tools/cosmos_failure_trace.py /path/to/HX_Stomp_v3.80.0_0x103966115.hxf > build/cosmos-failure.json
```
