# HXtra effect interface design

Draft, 2026-11-15. This is the proposed contract for adding audio effects to
HXtra, starting with NAM and the Atmosphere. It defines what an effect
declares, what the shared module owns, and how the native firmware admits and
constructs an instance. It is not an implemented SDK or a hardware qualification.

The first implementation slice now exists: [effect_model.py](../tools/effect_model.py)
generates and verifies direct-control mono/stereo FX models, and
[Atmosphere's declaration](../tools/microlooper_definition.py) supplies its identities,
typed parameters, persisted order, private storage and callback symbols. Atmosphere's
[external code placement](research/features/microlooper-code-placement.md) fits
beside unchanged NAM2/NAM3 profiles. The broader runtime admission contract below
remains a proposal; NAM has not been migrated.

An effect should supply its model, parameter mapping, DSP implementation and
resource requirements in one declaration. The shared module should turn that
declaration into consistent native firmware structures and enforce resource
eligibility through the HX Stomp's existing browser and construction paths.
Effect authors should not each need to patch model tables, invent a capacity
check, or manage framework-owned arenas.

## Required behavior

- DSP and instance-memory availability follow the blocks actually present in
  the preset. A bypassed block retains its allocation and its resource charge.
- An unavailable candidate is grayed out through the normal native browser.
  The same eligibility rules protect insertion, replacement and preset loading.
- Including Atmosphere support preserves the equivalent non-Atmosphere build's NAM
  capacity when no Atmosphere block is present: currently NAM3 without GR and NAM2
  with GR. Removing or replacing blocks restores the availability their actual
  resources permit.
- Atmosphere has no special instance-count restriction or warning. Each admitted
  instance owns independent state and history.
- Stored NAM captures remain separate from simultaneously active NAM blocks.
  This design does not reduce the capture store.
- Existing native kind restrictions and DSP refusals remain authoritative.
  HX Edit support is deferred.

These requirements supersede the earlier experimental Atmosphere build's fixed NAM1
profile. The current Atmosphere builder preserves the baseline NAM profile through
separate resident code placement. See [the resource analysis](research/features/microlooper-preset-resources.md)
and [the implemented placement](research/features/microlooper-code-placement.md).

## Evidence and design seam

The [Cosmos Echo trace](research/features/cosmos-echo-interface.md) establishes
the native allocation and lifecycle facts used here **[verified offline]**:

| Native behavior | Consequence for this design |
| --- | --- |
| Model names, preset IDs, blob indices and primitive IDs are separate identities. UI order, public slots, state order and child control pids also differ. | Declare these mappings explicitly and generate their native representations together. |
| Constructors carve several memory arenas, including metadata and graph-owned buffers. Primitive DM/PM totals omit part of the allocation. | Validate the complete graph allocation against its supplied reservations. |
| A retained reservation seeds a disposable constructor allocator. Rebuild can reuse the retained ranges. | The framework owns arenas; primitives consume bound spans. Do not expose an invented per-buffer free operation. |
| Reset and teardown are distinct callbacks. Cosmos teardown does not individually release or clear its delay rings. | Initialization, reset, destruction and history validity have separate responsibilities. |
| Native DSP pricing refunds the replaced block's declared cost. | Extend the existing admission decision rather than replacing DSP accounting. |
| Graph creation sends without a verified allocation acknowledgement; failed replacement need not restore the previous graph. | Validate storage before construction and never interpret local send success as DSP readiness. |

The interface seam sits between an effect declaration and the firmware adapter.
The effect knows its algorithm and state semantics. The adapter knows native
tables, graph encodings, callback conventions, hook sites and arena rules.
Firmware addresses belong in the adapter, not in every effect declaration.

The following sections are proposed behavior. The evidence does not establish a
general native global free-space meter, complete graph scheduling, or an atomic
replacement operation.

## Effect declaration

Use a Python declaration alongside the existing Python build tools. Do not add
a second configuration language or a runtime plugin loader. The initial
declaration has five parts:

| Part | Required information |
| --- | --- |
| Model | Stable model name and preset ID, display/category placement, mono/stereo ports and supported firmware target. Build-local blob and table indices are generated. |
| Parameters | Typed bounds/defaults, public slot, UI visibility/order, persisted key/order, restore policy and explicit native control destination or transform. |
| Graph | Primitive members, audio connections, initial controls and graph-owned buffer declarations with reader/writer bindings. A single custom primitive is a valid graph. |
| Resources | Assembled resident code/data, member DM/PM/SDRAM, graph buffers, required alignment and any proven shared workspace demand; declared DSP cost and its measurement status. |
| Implementation | Assembly sources and init, reset, teardown, control and process entry symbols; optional effect-specific M4 control integration using the existing feature engine. |

This is a logical contract, not a commitment to a particular class hierarchy.
Start with the smallest records and functions that express NAM and Atmosphere.
Absence of an optional callback produces the native no-op where appropriate.
There is no arbitrary maximum-instance field for Atmosphere.

A parameter's public slot is never implicitly its persisted-state index or
DSP pid. A direct mapping must still name its destination. Native tempo or
other control transforms can use a validated native graph; a general control
expression language is unnecessary for the first two effects. Framework root
commands remain separate from child controls. Cosmos root pid 0 and native
tail semantics must not acquire guessed meanings in the adapter.

Persisted values and momentary actions must be distinguished even when native
metadata represents both as parameters. For Atmosphere, restored Play/Overdub values
must not trigger capture or overdub on load or snapshot recall. Its existing
restore filters remain part of the effect's control integration until a shared
implementation can preserve the same behavior.

Atmosphere's visible **Loop** parameter is the explicit Controller Assign target.
Native assignment records own the FS1–FS5 selection and its per-switch Momentary
setting. Physical events from that assignment feed the gesture module; ordinary
bypass assignments keep their native meaning. Loop is public slot 6/PID 15, with
hidden Play/Overdub at slots 7/8 and unchanged DSP PIDs 10/11. Restoring a Loop
parameter value is not a physical press and must not trigger a gesture. The
adapter snapshots controller records outside graph ownership, then verifies a
lifecycle epoch before resolving their block IDs; it does not nest the two
mutexes. See [the current control contract](research/features/microlooper-switch.md#explicit-loop-controller-assignment).

## Shared module responsibilities

Build one effect module around the existing graph, assembler, container and M4
feature tools. Internally it needs three responsibilities, not three separate
public extension systems:

1. **Compile declarations.** Resolve identities, generate model/state/control
   tables, assemble implementations and calculate native graph requirements.
2. **Plan and link the image.** Assign resident code/data locations, validate
   collisions and partition limits, install native registrations and shared
   hooks once, and emit a checked report.
3. **Admit and bind instances.** Combine native eligibility with generated
   resource data and route native lifecycle callbacks to bound instance state.

Existing `kit_patch_amp` graph/model writers, SHARC layout/assembler tools and
`Patch` hook ownership remain implementation dependencies. This design does
not replace the M4 feature engine. Effect-specific switch behavior stays with
the effect; shared hooks and graph ownership routing stay with the shared module.

The intended build-facing surface is conceptually:

```python
plan = plan_effects(stock_firmware, selected_effects, build_options)
image, report = build_effects(stock_firmware, plan)
```

Planning is read-only. It returns resolved declarations, placements and either
validated instance-resource rules or concrete build errors. Linking verifies
the input image and resolved assumptions again. The names above are illustrative;
there is no need to introduce a framework merely to preserve these spellings.

The report records exact identities, parameter/state mappings, assembled
placements, graph allocation requirements, installed hooks, source/output
checksums and qualification status. Admission constants and reports come from
the same resolved declarations rather than separately maintained numbers.

## Resource contract

### Resident storage and instance storage

Resident storage exists whenever the firmware includes an implementation:
instructions, shared immutable tables and any fixed reservations. It must fit
at build time even when no instance is present. Removing a block cannot refund
resident code. A shared table is counted once, while mutable instance state is
counted per owner.

Instance storage includes native private DM/PM/SDRAM, graph buffers, working
audio and framework metadata. The adapter calculates the native allocation
including rounding, alignment and each applicable arena pool. It must reproduce
the allocator's order and capacities, not just sum payload words. Storage units
are explicit: Entry 2 bytes, normal 32-bit words and 48-bit PM instructions are
not interchangeable.

A buffer declaration names its owner, length and binding. Native bindings
contain base and length, not an assumed end pointer. Within an instance, several
members may intentionally share one graph buffer. Separate instances cannot
alias writable storage. Effect code receives bound storage and never obtains
extra capacity by increasing an unchecked member size.

There are two possible memory constraints:

- **Native reservation fit:** each graph fits the concrete enclosing native
  arenas. A model's placeholder budget is not proof of actual parent capacity.
- **Shared preset resources:** demands fit an explicitly established runtime
  pool, if the implementation uses one. Such a pool needs proven capacity,
  ownership, acquisition and release paths before it can admit effects.

Do not collapse these into one fictional global count of free words. Native
effects already consume native reservations; continue to respect that ownership
rather than subtracting incomplete estimates for every stock effect. A new
shared pool must occupy a proven disjoint reservation, or account for every
other user of that reservation.

The first implementation should prefer native per-instance storage. If NAM's
remaining fixed workspaces need a shared pool, represent their physical demands
in the common resource policy, not as an effect-name exception such as
"Atmosphere present implies one NAM." Do not claim a pool exists until storage and
lifecycle tests establish it.

### DSP and memory admission

The runtime interface is a read-only candidate check against the current native
graph, with an optional replacement target. Conceptually it returns the native
status plus an allowed/refused result. Internal refusal reasons support tests
and diagnostics; players see normal browser graying.

Admission follows these rules:

1. Run native model/kind eligibility and DSP pricing. A nonzero error status is
   a refusal even if the output boolean happens to remain true.
2. Validate the candidate's generated allocation requirements against the actual
   destination reservation and any established shared-resource capacities.
3. For replacement, subtract the old instance's resource charge only where the
   verified lifecycle makes that storage reusable. If old and new must coexist,
   validate peak simultaneous demand. Native DSP's cost refund alone does not
   establish memory reuse.
4. Recheck against the current graph at the serialized mutation point before
   destructive native work. Browsing neither allocates storage nor reserves a
   workspace. A stale browser result cannot authorize construction.

All custom-effect construction routes must use these rules: browser insert,
model replacement, preset load and any copy/restore route that constructs a
graph. Preset loading must validate its whole target graph before destructive
construction; checking additions one by one against the outgoing preset can
produce the wrong result. Native error handling remains the presentation for
refused mutations; no extra Atmosphere warning is introduced.

Use live graph ownership as the source of instance demand. Generate a lookup
from resolved model identities to resource requirements. Recompute a small
preset's demand through a shared native traversal rather than maintain a second
mutable ledger where possible. A native storage lease, if required by the
eventual layout, records physical ownership; it is not a competing preset model.
Removal refunds shared capacity only once the old DSP owner has stopped using
it. Retained moves must not briefly release a still-live allocation.

Unknown native capacity or an unproven shared allocation rule is an integration
error. It cannot become an optimistic zero-cost requirement. An unqualified
effect can remain explicitly experimental; it must not become eligible through
missing resource data.

## Instance ownership and lifecycle

The framework owns retained reservations and graph publication. An effect owns
the meaning of its private state and initialized history. Keep native callbacks
as the processing interface:

| Callback | Effect obligation |
| --- | --- |
| Init | Initialize dirty private state, bind supplied storage and make initial processing safe. Never assume history was zero-filled. |
| Control | Accept mapped, typed controls using the native convention. Restored momentary state must not become a physical action. |
| Process | Use only bound storage and preserve the native register/sample convention. Do not allocate memory or wait on locks in the audio path. |
| Reset | Apply the effect's explicit reset semantics without implying destruction or releasing framework memory. |
| Teardown | Stop effect-owned auxiliary activity where needed. Do not individually free framework-owned graph buffers. |

The adapter verifies registry callback order and generated graph sizes against
the assembled implementation. A zero teardown entry is valid when no
effect-owned cleanup is necessary. Graph-buffer reclamation belongs to the
framework reservation lifecycle.

M4 input routing also needs an instance ownership lifetime. Before destruction
or replacement it must stop targeting the old instance. Only a completed,
eligible graph may become a control target. Reusing a native block ID or pointer
does not prove continuity. Keep this ownership machinery inside shared native
routing rather than require every algorithm to interpret graph mutations.

For Atmosphere, preserve the accepted behavior: retained moves, bypass and assignment
changes preserve playback, cancel overdub and disarm a held gesture; mode
changes also preserve playback while cancelling overdub. Reload starts empty
and listening. Snapshot recall does not trigger transport. The one switch taps
to capture/listen and holds for 400 ms to overdub during playback; release ends
overdub without an additional tap. History validity must prevent stale storage
from being played before capture.

## Construction and errors

Admission is a precondition, not an allocation acknowledgement. The native M4
creation call's local success must not be exposed as "DSP ready." Complete graph
publication, control eligibility and storage retirement require the native
lifecycle evidence described above. The trace has not yet established their
complete scheduling behavior.

Before construction, reject invalid identities, mappings, placements, resource
declarations or missing capabilities. During construction, propagate native
errors and keep failed instances ineligible for custom control routing. Do not
promise restoration of the outgoing graph: the traced native replacement path
can disable it before failure and does not automatically rebuild it.

The initial interface does not add a new acknowledged transport protocol.
Instead, each supported layout must prove that admitted allocations fit the
supplied reservations. If later work requires recovery from unpredictable
remote allocation failures, acknowledgement and recovery become a separate
design requirement before that layout can be supported.

## Applying the contract to the first effects

| Concern | NAM | Atmosphere |
| --- | --- | --- |
| Existing implementation | `nam_multi` layout/kernel and model writers | Metadata writer, DSP core/bridge/callbacks and M4 switch/lifecycle integration |
| Instance demand | Native private rings plus remaining fixed workspaces; all mutable storage needs an explicit owner | 199 DM words, zero private PM and 48,000 SDRAM words in the existing implementation, plus native graph/framework overhead |
| Resident demand | Shared kernel/tables and current fixed slot reservations | Core, planar bridge and callbacks: 1,845 normal words in reserved DDR2 |
| Admission migration | Replace bespoke profile-capacity policy with generated physical resource constraints after the storage design is proven | Retain native DSP admission; add validated memory admission without a singleton policy |
| Required proof | Preserve baseline simultaneous capacity without Atmosphere, independent captures, and processing correctness/timing after relocation | Independent histories, native stereo binding, transport/lifecycle behavior and measured DSP cost |

These sizes describe existing implementations **[verified offline]**, not a
final shared layout. See [resource limits](resource-limits.md) and
[Atmosphere integration evidence](research/features/microlooper-integration.md).

The implemented Atmosphere-only placement leaves NAM's model stream and fixed
workspaces untouched. There is no need to relocate them merely to fit Atmosphere's
resident code. Any later NAM storage migration still needs independent ownership,
processing-correctness and timing proof.

## Implementation sequence and acceptance

1. **Compile and validate one declaration.** Express Atmosphere's existing metadata,
   callbacks and resources through the shared build module. Read back the final
   native tables and reject inconsistent IDs, types, mappings, sizes and hooks.
   Keep the existing experimental artifact as a comparison, not a compliant
   release. This step need not introduce runtime resource changes.
2. **Establish the common storage layout.** Prove a layout that fits resident
   code with baseline NAM3/NAM2 capacity and supplies real instance reservations.
   Exercise exact fit, exhaustion, alignment, dirty storage and repeated reuse.
   Do this before widening eligibility or removing physical-capacity guards.
3. **Migrate NAM and install common admission.** Derive policy from both
   declarations. Cover construction routes, whole-preset validation, native
   status handling, either insertion order, replacement, bypass, removal and
   stale browser results. Remove superseded bespoke policy once the shared
   mechanism owns every applicable path.
4. **Qualify lifecycle and hardware.** Verify boot, native stereo lanes,
   publication/quiescence, independent state and measured worst-case DSP load.
   Confirm visible graying and restored availability on the HX Stomp with stock
   effects and admitted custom combinations.

The smallest decisive admission checks are the same final graph reached by
different edit orders; a boundary that fits exactly and one that exceeds it;
replacement that reuses storage and replacement that requires overlap; and
removal followed by an otherwise refused addition. Multiple Atmosphere instances
should be exercised wherever the measured resource budget permits them, without
adding a special policy to force or prohibit that configuration.

This sequence has two workstreams for independent work after the declaration contract
is settled: build/schema generation and storage-layout proof. Runtime admission
and final linking depend on the proven storage results. Hardware qualification
depends on both. Do not enable a partially integrated resource policy merely to
make those tasks run in parallel.

## Open integration work

The contract is concrete enough to implement. These facts still need proof
before it can produce a user-testable firmware:

- The exact native reservation source and lifetime used by admission, including
  the outer reservation acquisition/reclamation and any shared pool.
- Hardware boot and fetch timing for the Atmosphere-only external layout, whose
  resident and partition fit are verified offline with baseline NAM capacity.
- Complete serialized graph publication, retirement and control-target timing.
- Physical stereo sample binding, worst-case DSP costs and visible browser
  behavior on hardware.

There is no new global allocator, code overlay system, runtime plugin loader,
general control language or transport protocol in this proposal. Add one only
if the first two effects demonstrate that the native-compatible contract cannot
meet their required behavior without it.
