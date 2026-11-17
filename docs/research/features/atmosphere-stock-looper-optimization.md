# Stock looper lessons for Atmosphere optimization

2026-11-17. Read-only investigation of the user's HX Stomp 3.80.0 firmware,
MD5 `a2cd8f4ae56f49415380270ebc484bf1`. No hardware access, firmware mutation,
installation, commit or push occurred. Status follows
[the research conventions](../conventions.md).

## Findings that affect the next candidate

**[verified offline: stock metadata and selected instruction encodings]** Stock
looper processing runs from internal instruction memory. Atmosphere currently
executes its entire 1091-instruction audio core from DDR2. Prioritize moving the
most frequently executed read/interpolation code into proven internal space;
measure that candidate before changing its arithmetic. This is a testable
optimization direction, not proof that placement alone explains the whole
69.8% hardware peak.

**[verified offline: manufacturer documentation]** The ADSP-214xx external
instruction cache holds only 32 instruction/address pairs in 16 two-way sets;
the low four address bits select a set. Internal execution instead uses that
cache to resolve instruction/PM-data conflicts. A long external sample loop
cannot be assumed to remain cached. Repeatedly needed instructions sharing a
set can displace one another. Sources: ADI
[Hardware Reference rev1.1, pp4-22..4-24](https://www.analog.com/media/en/dsp-documentation/processor-manuals/ADSP-214xx_hwr_rev1.1.pdf),
and [Programming Reference rev2.4, pp4-79..4-88](https://www.analog.com/media/en/dsp-documentation/processor-manuals/ADSP-2136x_2137x_214xx_pgr_rev2.4.pdf).

**[verified offline: manufacturer documentation; running state unknown]**
`MODE2.CADIS` bit4 disables both instruction-cache modes; `EXTCADIS` bit6
disables external caching only; `CAFRZ` bit19 freezes cache contents. Read the
running register before attributing cost to any of these settings. Changing a
shared mode register is a separate experiment requiring exact restoration.
Source: the same Programming Reference, pp4-89..4-90 and appendix A-8.

**[inference / candidate]** A small internal hot-function section addresses
external instruction fetch without claiming extra per-instance ring storage,
altering native admission, or reducing the equivalent NAM profile. SIMD and
scratch-state optimizations remain useful, but the stock evidence does not
justify starting with a stereo-to-mono conversion or assuming all stock looper
math is SIMD.

## Native declarations and declared cost

**[verified offline: Entries0,2,3,4]** Entry3 identifies each model and its graph
blob; the blob's root composite identifies primitive members; Entry2's registry
provides their callback pointers and private sizes. Entry0 Table1 supplies the
declared DSP charge. These are static declarations, not measured execution
percentages.

| Native model | Preset ID | Declared units | Composite | Main primitive / process |
| --- | ---: | ---: | --- | --- |
| Six-switch Looper Mono | 152 | 528 | `0x6001c1` | `0x271e`, internal VISA `0x182d07` |
| Six-switch Looper Stereo | 153 | 528 | `0x6001c0` | `0x271f`, internal VISA `0x182d07` |
| One-switch Looper Mono | 504 | 528 | `0x6001c1` | same mono primitive/process |
| One-switch Looper Stereo | 505 | 528 | `0x6001c0` | same stereo primitive/process |
| Shuffling Looper Mono, Victoria | 570 | 800 | `0x6001c3` | `0x9c53`, ISA wrapper `0x8ea1f` |
| Shuffling Looper Stereo, Victoria | 571 | 1200 | `0x6001c2` | `0x9c54`, ISA wrapper `0x8ea25` |
| Shuffling Looper Mono, VIC alias | 616 | 800 | `0x6001c4` | same mono primitive/process |
| Shuffling Looper Stereo, VIC alias | 617 | 1200 | `0x6001c5` | same stereo primitive/process |

The plain mono/stereo registry rows are at `0x200168`/`0x200170`, each declaring
23 private DM words and five private PM words. Their control callback is shared
at external VISA `0x60c964`; initializers are `0x60cb2b`/`0x60cb80`.
Shuffling registry rows `0x2005d0`/`0x2005d8` each declare 238 DM words and no
private PM. Shuffling's apparent six-instruction ISA entry is a C-call adapter:
its mono wrapper enters internal VISA `0x17af90` and stereo wrapper enters
`0x17b035`. Therefore examining only the short ISA wrapper would conceal the
actual processing implementation.

Plain looper graphs each declare one buffer record with encoded length
5,760,000; Shuffling graphs each declare one with length 3,060,736. Primitive
private-SDRAM declarations are zero. Thus the primitive's own DM/PM/SDRAM tuple
does not describe the whole looper's storage: graph-owned buffers matter. This
agrees with the [Cosmos buffer-allocation trace](microlooper-preset-resources.md),
and is not permission to borrow stock looper storage or infer simultaneous
memory availability from a zero private-SDRAM field.

The native cost values cannot be substituted for Atmosphere's budget. Plain
record/playback and native Shuffling do not establish equivalent Envelope,
Stretch, splice, clock, transition or overdub behavior. They demonstrate that
the platform supports much cheaper loop processing, not that this port already
has their processing architecture or timing.

## Concrete processing patterns

**[verified offline: selected encodings round-trip through the assembler]**
The common plain-looper process binds hardware circular-address registers from
its private state: base from DM8, cursor from DM9, length from DM10, and stride
from DM22. These assignments occur at VISA `0x182d0b..0x182d13`; a counted
16-frame loop begins at `0x182e02`.

Selected reads at `0x182e09`/`0x182e0b` access adjacent left/right ring words.
The input reads at `0x182e0d`/`0x182e0e` advance the left pointer and then read
the right channel 15 words beyond the advanced pointer. Outputs use the same
planar relationship at `0x182e29`/`0x182e34`. Ring writes at
`0x182e4d`/`0x182e55` likewise address adjacent channel words. This is a native
example of planar 16-frame stereo processing with an interleaved history ring.
It supports the shape of Atmosphere's observed native contract without proving
every other primitive's audio layout.

The selected native sample calculations use separate scalar registers for the
two channels. No SIMD enable is established in this bounded loop trace. The
Shuffling mono/stereo entry bodies pass a sample count of 16/32 to a shared copy
routine at `0x8c69f`; their C adapters pass the input pointer, output pointer
and instance descriptor through native C arguments. This is evidence for shared
helpers and channel-dependent counts, not a recovered Shuffling algorithm.

**[candidate / behavior proof required]** Atmosphere can eventually process the
native planar input/output directly and remove its interleave/deinterleave
scratch copies. The current bridge's copies and register spills are only a
small part of the instruction-count total, so this is secondary to hot-code
placement. Hardware circular addressing may reduce repeated integer wrap work,
but a fractional interpolating read over a cropped splice is not equivalent to
ordinary full-ring wrapping. Preserve interpolation, splice and partial-history
semantics in the reference comparisons before adopting that technique.

## Evidence boundaries and reproduction

The repository's existing [loader parser](../../../tools/sharc/microlooper_adapter.py),
[bounded VISA decoder](../../../tools/sharc/microlooper_visa.py),
[native registry helper](../../../tools/sharc/cosmos_echo_trace.py) and
[assembler](../../../tools/sharc/sasm.py) were used. Internal INIT16 uses the
project's established high-first parcel interpretation; external VISA uses
low-first parcels. Twenty selected native instruction facts were independently
re-encoded and required exact equality with their decoded stock instructions.
No complete native looper execution, exhaustive control-flow recovery, native
CPU timing or SIMD speedup is claimed here. Unsupported instruction classes in
the exploratory formatter remain unknown and are not used as evidence.

REA's advertised native target architectures do not include SHARC; no
ARM decompilation was substituted for the SHARC process. No REA binary session
was opened and none needs closing. The supported repository decoder and
assembler provide the bounded observations above; a general native looper
decompilation remains outside this trace.

Ignored local evidence under `build/optimization-probes/stock-looper/` contains
`metadata.json`, `bounded-process-decode.json`,
`validated-observations.json` and the exploratory `trace.py`. The tracked note
contains addresses and derived facts, not proprietary firmware images or a
whole disassembly. Mode-register observations and candidate hardware timings
must be supplied by the orchestrator's separate RAM tests.

The orchestrator subsequently observed live `MODE2=0x42000020`: CADIS(bit4),
EXTCADIS(bit6) and CAFRZ(bit19) are all clear. The external cache is enabled and
not frozen. Controlled code-placement comparisons and their timing evidence
are recorded in the [hardware log](microlooper-hardware-log.md#internal-hot-code-optimization).
