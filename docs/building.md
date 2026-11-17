# Building HXtra

Most people never need this page: the [setup page](https://wisemandenny.github.io/hxtra/web/) does the whole build in your browser. Build from the command line to pick features one by one, to use your own boot picture, or to work on HXtra.

## Requirements

- An **HX Stomp**: HXtra supports the HX Stomp only. `build.py` still builds upstream's NAM A2 Lite for the HX Stomp XL and the HX Effects (on the HX Effects NAM is in Distortion > Mono), untested, with none of HXtra's features.
- Line 6's firmware 3.80.0 for your unit. The build checks the MD5 and refuses any other file:
  - HX Stomp: `HX_Stomp_v3.80.0_0x103966115.hxf`, MD5 `a2cd8f4ae56f49415380270ebc484bf1`. Download it from [line6.com](https://line6.com/software/readeula.html?rid=12906); you need to sign in with a free Line 6 (Helix) account to get the download.
  - HX Stomp XL: `HX_Stomp_XL_v3.80.0_0x103966115.hxf`, MD5 `329e3a26d60d3de1988b6785fa833ee1`
  - HX Effects: `HX_Effects_v3.80.0_0xd97239907.hxf`, MD5 `7c2ebdf1bffb6bcc5f89dda97f91e40c`
- Python 3.10 or newer with `numpy`: `pip install numpy`. To run a build from RAM from the command line, also `pyusb` and `dfu-util`.
- For every feature but the boot screen and real block names, clang: their M4 code is assembled with it at build time. On a Mac, Apple's Command Line Tools (`xcode-select --install`); on Linux or WSL, `apt install clang` (clang 18 gives the same bytes as Apple's). `tools/m4asm.py` takes `HX_CLANG` (a path, or a name on `PATH`) first, then the Command Line Tools' clang, then `clang` on `PATH`. For the boot screen, macOS converts pictures (`sips`) and renders emoji (`swift`); elsewhere give a 320x240 PNG and `--splash-glyph` pictures.
- **Line 6 Updater** to install, and **HX Edit** to import captures.

## Build

```sh
git clone https://github.com/wisemandenny/hxtra.git
cd hxtra
python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf
```

This writes `build/HX_Stomp_v3.80.0_HXtra.hxf` (from the XL's file, `build/HX_Stomp_XL_v3.80.0_HXtra.hxf`; from the HX Effects', `build/HX_Effects_v3.80.0_HXtra.hxf`). It takes about 2 minutes, most of it the kernel check of step 1. The build:

1. Assembles the NAM kernel and runs it in the SHARC simulator, checking every block's output bit for bit against a reference NAM A2 implementation (`src/sharc/nam_a2.asm`). Add `--no-check` to skip this step.
2. Adds NAM A2 Lite in place of Xenomorph Fuzz Mono (preset ID 555): `tools/patch_amp.py remove-model`, `add-fx-model --knobs eq`, `move-folder` (into Amp > NAM) and `ir-title --knob 6` (the IR name in the block title, from the Model knob). These are `build.py`'s `STEPS`; the HX Effects has its own one step, `effects-eq`.
3. On the HX Stomp, adds the HXtra features that are turned on to the main application (`tools/patch_menu.py`, from `tools/features/`).
4. Adds the kernel to the DSP's boot code (`patch_amp.py patch`).
5. Recomputes and verifies every checksum: the container MD5, the archive Fletcher-32 and CRC-32, and the image CRCs.

The build is deterministic. The default HX Stomp build (no switches) has MD5 `e2ef4415d8f8603bf6153665b4785a59`, pinned in `tests/test_firmware.py`.

A default build changes only 5 of the 15 parts of the firmware: the main application, the DSP program, the model list, the DSP graph library and the image store (the boot picture; emoji in the boot text also change the font table). **The bootloader is never touched**, which is what keeps [recovery](https://wisemandenny.github.io/hxtra/web/#recovery) possible.

To add features, set their switches: see [Features](features.md). For example, every feature but the boot picture:

```sh
HX_TUNER=1 HX_BPM=1 HX_DSP_METER=1 HX_BREATHING_LINE=1 HX_LONG_PRESS=1 HX_MORE_SNAPSHOTS=1 HX_CLICK=1 HX_GR=1 HX_TAP_COLOR=1 HX_REAL_NAMES=1 \
  python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf
```

## Build in the browser

The setup page, **[wisemandenny.github.io/hxtra](https://wisemandenny.github.io/hxtra/web/)**, does the same build in the browser, with nothing uploaded: you drop your stock `.hxf` and download `HX_Stomp_v3.80.0_HXtra.hxf`, with every feature on, the Metronome block included, and Real block names if you tick their box. It also runs the build from RAM and converts `.nam` captures, and it reads in 10 languages. It runs `build.py`'s own commands in [Pyodide](https://pyodide.org) (`web/firmware-worker.js`); its builds have the same MD5s as `build.py`'s.

The browser has no clang to assemble the features' M4 code, so each release brings that code made in advance: `tools/m4cache.py` runs the page's features on the stock file and keeps what each module assembled to, in `m4cache.json`, with the MD5 of the build, and `tools/m4asm.py` reads it when `HX_M4_CACHE` names it. The page compares its build with that MD5 and says **Verified**. The page runs `build.py`'s other steps for them too: the Metronome block (`tools/patch_click.py`), and the GR meter's knobs and DSP code (`tools/patch_comp.py`, with NAM on two slots). A copy of the page served from a checkout (`python3 -m http.server`, then `/web/`) has no `m4cache.json` and builds without features, unless you make one: `python3 tools/m4cache.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf -o m4cache.json`.

The page is published only for a release, never from `main`, so it always matches one; see [Releases](../CONTRIBUTING.md#releases).

## Try it first, from RAM

You can run the built firmware from the HX Stomp's memory for one session before you install it. Nothing is written to the HX Stomp, and turning it off and on brings back what is installed. The HX Stomp must have stock 3.80.0 installed. This is how every HXtra change is tested.

Close HX Edit, then:

```sh
python3 tools/hxf_ram.py dfu    # or hold Page Right while you power on
dfu-util -d 1fc9:000c -a 0 -D tools/ramboot/firmware-ramboot.dfu
python3 tools/hxf_ram.py run build/HX_Stomp_v3.80.0_HXtra.hxf --stock HX_Stomp_v3.80.0_0x103966115.hxf
```

The setup page's **Run from RAM** step does the same in Chrome or Edge. Presets and IRs you change during the run are lost at power-off. [RAM_RUN.md](../RAM_RUN.md) explains how it works and its limits.

Then install it with Line 6 Updater, as the [setup page](https://wisemandenny.github.io/hxtra/web/)'s install step says.

## NAM memory profiles

The build retains three simultaneous NAM workspaces normally, or two with GR.
Enabling the development Atmosphere does not change that selection or install
a NAM capacity wrapper. Atmosphere's resident instructions now use a checked external
DDR2 reservation, leaving NAM's kernel, fixed slots and tables unchanged.
Stored User IR and capture slots are unaffected. There is no independent normal
build slot-count override. See the [placement evidence](research/features/microlooper-code-placement.md).

Low-level diagnostic patch functions accept an explicit NAM layout; this does
not expose another normal firmware configuration. The single-slot kernel has
reference/simulator coverage for model replacement and DMA recovery. See the
[implementation plan](microlooper-plan.md) for integration and hardware gates.

## Development Atmosphere build

**Hardware status, 2026-11-17:** the clean mono/stereo build has MD5
`ba4e9a12c9b6dab551be6326b2f70c94`. Atmosphere has separate native mono and stereo
models. Mono is ID 381 (`HD2_AtmosphereMono`); stereo retains ID 380
(`HD2_AtmosphereStereo`) so existing presets keep their identity. The timing
prototype ran on the unit; the final clean RAM upload currently awaits a power
cycle after a temporary loader reconnect failure. Its complete DSP boot entry
is identical to the measured candidate. Internal
hot-code placement and exact compute changes previously reduced the stereo
core's largest observed call from 69.8% to 14.0% of the audio-block interval.
The user previously confirmed
Tape capture, repeating playback, held overdub/release, replacement capture,
Mix and Stretch controls on the pre-optimization image. Independent audio and
state comparisons preserve that algorithm. Hardware
comparisons corrected the UI-context/assignment-manager mix-up, the transport
parameter-space flag and the bridge's rejection of native DDR2 descriptors.
Envelope listening checks, stereo separation, broader timing/resource and
lifecycle acceptance remain pending. The budgets below are experimental hardware-
derived charges, not exhaustive timing or release qualification. No permanent flash has occurred. See
[the hardware log](research/features/microlooper-hardware-log.md).

The shared declaration, native initialization, lifecycle controller and split
internal/external ISA placement are implemented and checked offline. Enable them with
`HX_MICRO_LOOPER=1`; the build retains the ordinary NAM profile and GR/metronome
when selected. This does not yet implement the general memory-admission design. The
feature is default-off and excluded from browser/release selection while hardware
acceptance remains outstanding. HX Edit support remains deferred.

Both variants share timing/capture/control code. Mono processes one native
16-word audio buffer and keeps 24,000 history words (96,000 bytes), while stereo
processes two planes and keeps 48,000 words (192,000 bytes). Capture duration and
Clock behavior are identical. The native framework handles mono routing. Both
use 163 private DM words; no private interleave buffer remains. These allocations
belong to active effect instances; the shared executable is resident in the build.

An explicit `HX_MICRO_LOOPER_DSP_COST` is still required. Set
`HX_MICRO_LOOPER_MONO_DSP_COST` to give mono its separately measured charge;
omitting it uses the explicit stereo charge for both widths. For the current
image with the compressor gain-reduction meter enabled (`HX_GR=1`, ordinary
NAM2 profile), the sample loop and its helpers reside in internal code space:

| Variant | Native DSP charge | Largest observed processing call | Loop history |
| --- | ---: | ---: | ---: |
| Atmosphere Mono | **1700 (17%)** | 19,774/150,000 cycles, **13.18%** | 24,000 words / 96,000 bytes |
| Atmosphere (stereo) | **2000 (20%)** | 24,184/150,000 cycles, **16.12%** | 48,000 words / 192,000 bytes |

The mono maximum covers isolated and mixed-preset sweeps; stereo was measured
with the same stock neighbors. Mono uses about 18% less DSP than the shared
stereo path in these sweeps, not half: timing and control work remains shared.
The shared stereo path is slower than the preceding dedicated stereo core's
14.0% peak, but stays below its 20% charge. Both charges allow headroom above the
sampled maximum and cover all modes, which can change during playback.

Without the compressor meter, the unchanged NAM3 profile fits only the helpers
internally. That placement needs a separate timing qualification for this shared
mono/stereo kernel; do not apply the NAM2 charges to it. The preceding stereo-only
image's 32% helper-layout charge is historical evidence in the
[hardware log](research/features/microlooper-hardware-log.md#internal-hot-code-optimization).
NAM capacity without Atmosphere is unchanged. The active preset's actual blocks
still determine native DSP admission; there is no separate Atmosphere instance
count restriction. General memory admission remains separate work.

```sh
HX_MICRO_LOOPER=1 HX_MICRO_LOOPER_DSP_COST=2000 HX_MICRO_LOOPER_MONO_DSP_COST=1700 \
HX_LONG_PRESS=1 HX_GR=1 HX_CLICK=1 \
  .venv/bin/python build.py /path/to/HX_Stomp_v3.80.0_0x103966115.hxf \
  -o build/HX_Stomp_v3.80.0_HXtra.hxf
```

The build writes `build/microlooper-build.json` with the native callbacks, runtime
manifest verification, resource counts and final HXF MD5. It rejects missing
controls, wrong slot/PID/default or state mappings, changed native heap setup,
overlap through external instruction/data aliases, and partition overflow. The
complete NAM2 + compressor meter + metronome DSP image currently leaves **224 bytes** below the
512 KiB Entry 2 limit. Broader shared-load,
audio cleanliness and native stereo acceptance still require hardware qualification.

Before a RAM comparison, verify the actual built image:

```sh
.venv/bin/python tools/verify_atmosphere_candidate.py \
  build/HX_Stomp_v3.80.0_HXtra.hxf --report build/microlooper-build.json
```

The gate checks archive integrity, partitions, native metadata and callbacks,
private allocation, physical code/data aliases, unchanged NAM/native neighbors,
and emitted audio code against the independent C++ reference. It takes about
three seconds locally. `--allocation-only` takes under a second and explicitly
skips callback/audio execution. Neither mode establishes hardware timing.

On the device, both models are registered under **Delay > Atmosphere**, named
**Atmosphere Mono** and **Atmosphere** (stereo), with Mode, Length, Modify, Clock
and Mix. Assign one ordinary bypass footswitch:
tap on release captures or resumes listening; hold for 400 ms overdubs during
playback until release. A hold does not also tap. Captures are RAM-only and
preset reload starts empty/listening. The controller retains playback across
switch-mode changes when the DSP instance survives, while cancelling Overdub and
disarming any held gesture. Tape tap capture and held overdub/release have been
confirmed by listening; the remaining transport/lifecycle cases still require
on-unit acceptance.

See [integration evidence](research/features/microlooper-integration.md) for the
native-code tests and exact remaining hardware checks. No firmware is installed
by the build command.
