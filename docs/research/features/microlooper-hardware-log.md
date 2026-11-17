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
