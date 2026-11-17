# Permanent external code placement for the Atmosphere

2026-11-15. Scope: fitting Atmosphere alongside the existing NAM3 or NAM2 plus GR
profiles without changing NAM sources, slot storage, arithmetic or runtime
ownership. This proves a bounded resident placement and emitted instruction
encoding offline; native stereo binding, boot and real-time timing remain
hardware gates. Status tags follow [the conventions](../conventions.md).

The all-external implementation below is a historical placement proof. The
current build keeps cold setup/callbacks external and moves the repeated
processing into proven internal gaps. See the
[split planner](../../../tools/sharc/microlooper_split.py) and
[hardware optimization results](microlooper-hardware-log.md#internal-hot-code-optimization).

## External ISA is supported directly

**[verified offline: manufacturer documentation]** The ADSP-21469 executes
traditional ISA48 instructions from external bank 0 at logical instruction
addresses `0x200000..0x5fffff`. It does not require a VISA rewrite. Source:
[ADSP-21467/21469 data sheet Rev B, page 7](https://www.analog.com/media/en/technical-documentation/data-sheets/ADSP-21467_21469.pdf).

**[verified offline: manufacturer documentation]** External ISA address `P`
occupies physical 16-bit locations `3*P..3*P+2`, with the least significant
parcel first. Normal 32-bit data address `D` occupies physical locations
`2*D..2*D+1`. Thus a code reservation starting at an even instruction address
can be emitted as an ordinary normal-data boot record at `D=3*P/2`. This is a
physical alias, not the internal Block 3 address conversion. The final three
ISA addresses at the ISA/VISA transition are excluded. Sources:
[ADSP-214xx Hardware Reference Rev 1.1, pages 4-45 through 4-49 and 4-95](https://www.analog.com/media/en/dsp-documentation/processor-manuals/ADSP-214xx_hwr_rev1.1.pdf).

**[implemented / verified offline]**
[microlooper_placement.py](../../../tools/sharc/microlooper_placement.py)
assembles code at its final external ISA address and packs its little-endian
48-bit instructions into one normal 32-bit `INIT_LDATA` record. The existing
boot path already uses this record form for NAM's DDR2 tables. No new loader
opcode, runtime copy, mutable overlay or global capture buffer is introduced.
The helper rejects insufficient reservations, aliased boot writes, runtime
claims, noncontiguous sections and unsupported external initializer forms.
Source: the helper and the existing
[boot-record writers](../../../tools/kit_patch_amp.py).

## Ownership and placement

**[verified offline: source and guarded native setup]** Existing NAM owns
DDR2 `0x324500..0x324ce6` for shared tone tables and gain values. Its layout
reserves no further state before `DDR2_END=0x328000`. The relocated native
Heap 6 ends at `0x324497`, and native Heap 4 begins at `0x328000`. Sources:
[NAM layout and runtime claims](../../../tools/sharc/nam_multi.py),
[existing heap relocation](../../../tools/kit_patch_amp.py), and the historical
[native heap map](../KIT_HEAP_USE.md). The helper reads the actual supplied
image's heap setup rather than relying on these constants alone.

**[verified offline: guarded original instructions]**
`require_native_reservation(records)` pins Heap 4's start/end/clear literals at
SW addresses `0x17884b`, `0x178855`, `0x17885e`, and moved Heap 6's corresponding
literals at `0x1788b6`, `0x1788c0`, `0x1788c9`. It reconstructs instructions by
SW address from parsed records, so equivalent zero-data compaction cannot shift
the check to the wrong bytes. The high-first INIT16 parcel interpretation is
explicit, as in the existing [native allocation replay](../../../tools/sharc/microlooper_allocation.py).
Changing any of the six literals refuses placement. The caller must also
verify the selected NAM image and preserve its complete linked/runtime claims.

**[verified offline: assembled current sources]** Atmosphere's core, planar bridge
and callbacks contain 1,093, 101 and 33 instructions respectively. Individual
section padding gives 1,230 instruction locations, occupying 1,845 normal
words. The core's six-instruction reduction shares constants across adjacent
parameter clamps; NAM is unchanged.

| Address space | Atmosphere resident extent |
| --- | --- |
| Normal 32-bit DDR2 storage | `0x324ce7..0x32541c` |
| Logical 48-bit ISA instructions | `0x21889a..0x218d68` |
| External physical 16-bit words | `0x6499ce..0x64a838` |

All ends are exclusive. The alignment word after NAM's table is left alone.
This storage is permanently resident while Atmosphere support is installed; its
removal from a preset does not reclaim code. Each Atmosphere instance still receives
its own native DM and SDRAM history. The placement uses no internal NAM slot
storage and creates no new NAM/Atmosphere shared-workspace capacity rule.

**[verified offline: image accounting]** With the existing equivalent zero-data
encoding, NAM3 plus click and the current Atmosphere code/registry projects to
520,552 Entry 2 bytes, leaving 3,736 bytes. NAM2 plus GR and click projects to
524,272 bytes, leaving 16 bytes under the 524,288-byte limit. These are DSP
layout calculations from assembled profile images; the complete builder must
check its final image again. The former 1,099-instruction core exceeded the
second profile's limit by 20 bytes; external RAM availability alone did not
solve that independent partition constraint.

## Verification and remaining gates

**[verified offline]** The placement suite passes 32 tests, including independent
documented alias/packing values, exact-fit/exhaustion and boot/runtime collision
checks, all six native heap-literal mutations, and actual baseline NAM2/NAM3
boot images. Tests reconstruct instructions from the emitted normal-data bytes
and exercise the full Atmosphere engine at the final external address through
capture, overdub, parameter/mode changes and transport for all three modes,
with separate and in-place buffers. Output and private memory match the internal
reference exactly. Every original resident code block and NAM table remains in
the linked fixture. Source:
[test_microlooper_placement.py](../../../tests/test_microlooper_placement.py).

The stock fixture is `HX_Stomp_v3.80.0_0x103966115.hxf`, MD5
`a2cd8f4ae56f49415380270ebc484bf1`. Reproduce the focused checks with:

```sh
HX_STOMP_HXF=/path/to/HX_Stomp_v3.80.0_0x103966115.hxf .venv/bin/python -m pytest tests/test_microlooper_placement.py -q
```

**[remaining limits]** The simulator does not model external fetch stalls,
instruction-cache collisions or contention with NAM's DMA. Native dispatch,
publication and physical stereo lanes still need complete integration and
hardware acceptance. The manufacturer describes automatic instruction caching
for external fetches, but that does not establish a usable Atmosphere DSP percentage.
Source: the Hardware Reference pages 4-49 through 4-52. Measure the final engine
before selecting its native admission cost or declaring the image ready for
user testing.

## Integrated declaration and build checkpoint

**[implemented / verified offline, 2026-11-15]**
[Atmosphere's declaration](../../../tools/microlooper_definition.py) now owns model
identity, typed parameter defaults, separate state indices/public slots, hidden
transport restore policy, instance payload and callback symbols. The shared
[model compiler](../../../tools/effect_model.py) generates and reads back native
model/state/control structures. Its first supported graph is the existing
direct-control single-primitive mono/stereo FX host; it does not implement a
general runtime memory ledger. Existing Atmosphere native input/restore handling
continues to enforce transport semantics.

The [integrated linker](../../../tools/patch_microlooper_build.py) requires an
exact unchanged NAM2/NAM3 code and data profile, checks the native heap setup,
then places Atmosphere in the reservation above. It does not install NAM's former
capacity wrapper. Link tests exercise both baseline profiles, final packed audio
instructions, original native C calls into final external init/control entries,
and rejection of memory collisions and partition overflow. The default build
continues to match its pinned MD5 `195682572258a3347d94ca7610a697b8`.

The complete all-standard-web-features plus Atmosphere build at
`build/HX_Stomp_v3.80.0_HXtra.hxf` has MD5
`5698d12ba91646e21bd382d90ec920c8`; its report confirms NAM2, 524272 Entry 2
bytes and 16 bytes free. All archive integrity checks pass. Native DSP cost
7500 is still an explicit unmeasured experimental value, not a hardware timing
measurement. Fingerprints of all 13 existing NAM-named source/test files are
unchanged from the start of this implementation task.

Regression checks: **782 passed, 2 skipped in 125.33 seconds**. These cover all
Atmosphere suites, the shared declaration and default firmware builds. The two skips
are missing HX Stomp XL / HX Effects fixtures. Documentation checks also pass.
No device access, installation, RAM run, flash, commit or push was performed.
