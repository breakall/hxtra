# Glasshouse

Glasshouse adds **Dynamics > Glasshouse** mono and stereo effects, based on the
original Glasshouse v0.3.2 compressor. It combines feedforward compression,
limiting and sag with EQ, spring motion, swells and automation. Atmosphere
remains a separate Delay effect.

The implementation is verified offline. These checks do not measure HX Stomp
CPU load, hardware startup timing or listening behavior. See the
[implementation plan](GLASSHOUSE_IMPLEMENTATION.md) for current validation.

## Controls

The first two native pages follow the original six knobs. Continuous values use
the normalized range 0..1; 0.5 corresponds to noon.

| Control | Behavior |
| --- | --- |
| Sensitivity | Compression threshold, from −6 to −54 dBFS |
| Dynamics | Increasing compression, then limiting, then sag above 0.75 |
| Wet | Processed level; 0 is silent, 0.5 unity, 1 approximately +12 dB |
| Attack | Nominal 0.5..300 ms; also sets motion frequency |
| EQ | Below 0.5 darkens; 0.5 is flat; above 0.5 removes bass |
| Dry | Direct level; same scale as Wet |

There is no automatic makeup gain. Swell, gate and the output limiter affect
the combined Wet/Dry signal.

Further native pages expose Release, EQ Mode, Physics, gate and swell timing,
detector filtering, adaptive envelopes, emphasis, stereo spread and routing,
drive, and automation. **Aux** and **Sag** can use native Controller Assign;
Bypass Assign controls the effect separately. Momentary Sag rises and falls
through the original 50 ms smoothing stages. Aux behavior follows Swell Mode.
During a live preset, a snapshot changing Aux from Off to On triggers the same
manual dip as a controller edge. Restoring Aux high while constructing a new
block does not trigger a startup dip.

The stereo block's Routing setting selects Mono, Stereo or External Key. With
External Key, left is program audio and right controls the detector; processed
left audio goes to both outputs. The mono block has one input and cannot
receive a separate external key.

Automation exposes a depth for each of the six main controls, a rate, one-shot
or repeating bounce, rise/fall/bipolar range, and linear/cosine/stepped shapes.
One-shot operation restarts when the effect is enabled. Settings use native
presets, snapshots and assignments.

## Build

Use the stock HX Stomp 3.80.0 firmware and select `HX_GLASSHOUSE=1`.
`HX_GLASSHOUSE_DSP_COST` is required; `HX_GLASSHOUSE_MONO_DSP_COST` can specify a
separate mono charge. Charges are hundredths of a DSP percentage point and must
be integers in 1..7500. They are admission settings, not CPU measurements.

```sh
HX_GLASSHOUSE=1 \
HX_GLASSHOUSE_DSP_COST="$GLASSHOUSE_STEREO_COST" \
HX_GLASSHOUSE_MONO_DSP_COST="$GLASSHOUSE_MONO_COST" \
HX_MICRO_LOOPER=1 HX_MICRO_LOOPER_DSP_COST=2000 HX_MICRO_LOOPER_MONO_DSP_COST=1700 \
HX_GR=1 HX_CLICK=1 HX_LONG_PRESS=1 \
  python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf
```

Set the two Glasshouse cost variables explicitly for the intended experiment.
The output is `build/HX_Stomp_v3.80.0_HXtra.hxf`. Keep the generated Glasshouse
and Atmosphere reports with that image when verifying it.

```sh
python3 tools/verify_glasshouse_candidate.py \
  build/HX_Stomp_v3.80.0_HXtra.hxf --report build/glasshouse-build.json
python3 tools/verify_atmosphere_candidate.py \
  build/HX_Stomp_v3.80.0_HXtra.hxf --report build/microlooper-build.json
```

Both commands check the actual final image. The Glasshouse check executes the
emitted startup decoder and native audio instructions against the independent
C++ reference. Simulator instruction counts are not hardware DSP percentages.

## Implementation

The independent [source reference](../tools/glasshouse/PROVENANCE.md) retains the
original engine and settings. Native declarations give both widths their own
model identity and allocate private state per instance. The SHARC engine uses
16-frame planar audio and bounded numerical helpers. The original Hothouse
device drivers, MIDI protocol, preset bank and flashing gestures are not part
of the HX Stomp effect.

Adding Glasshouse also requires a different DSP boot representation to fit the
existing partition. The storage implementation losslessly packs existing
external DSP boot data and restores it before the original DSP application
starts. The partition limit remains enforced. This startup path requires
hardware validation in addition to its encoded-decoder checks.
