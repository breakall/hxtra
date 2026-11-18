# Atmosphere

Atmosphere is a mono/stereo micro looper under **Delay > Atmosphere**. It captures
recent input, repeats it in Envelope, Tape or Stretch mode, and supports held
overdubbing. Each instance owns its capture and transport state.

## Controls

| Control | Function |
| --- | --- |
| Mode | Envelope, Tape or Stretch playback |
| Length | Loop window, envelope slice or stretch grain length |
| Modify | Envelope sensitivity, Tape speed/direction or Stretch scan speed |
| Clock | Internal sample rate, in five steps from 48 kHz to 3 kHz |
| Mix | Dry/loop balance |
| Loop | Footswitch input assigned through Controller Assign |

Adding a block creates no footswitch assignment. Select **Loop**, open
**Controller Assign**, choose FS1–FS5, and set **Type = Momentary**,
**Min = Off**, **Max = On**.

- Tap to capture and play; tap again to return to listening.
- Hold for 400 ms during playback to overdub; release ends overdubbing.
- A hold does not also tap. Holding while listening does not capture.

**Bypass Assign** retains its normal behavior. Bypass passes live dry audio and
mutes the loop; enabling restores it. Bypass and Loop may use separate switches.
Momentary/latching applies to the whole footswitch and its other assignments.

Assignments are saved in the native preset format. Parameter changes from knobs,
MIDI or snapshots are not physical footswitch gestures. Preset/graph recreation
starts listening with an empty capture; audio is not stored in presets.

## Build

Atmosphere is selected in command-line builds:

```sh
HX_MICRO_LOOPER=1 HX_MICRO_LOOPER_DSP_COST=2000 HX_MICRO_LOOPER_MONO_DSP_COST=1700 \
HX_GR=1 HX_CLICK=1 HX_LONG_PRESS=1 \
  python3 build.py path/to/HX_Stomp_v3.80.0_0x103966115.hxf
```

The charges are hundredths of a DSP percentage point. This configuration uses
17% for mono and 20% for stereo. The native model browser uses the charges to
gray out effects that would exceed the preset's remaining DSP budget.

| Model | Audio channels | History | Private DM |
| --- | ---: | ---: | ---: |
| Atmosphere Mono | 1 | 24,000 words / 96,000 bytes | 163 words |
| Atmosphere | 2 | 48,000 words / 192,000 bytes | 163 words |

Both store 24,000 frames and share capture duration and control behavior. Stereo
retains independent left/right samples with common loop timing. The native graph
allocates instance state and history for the active preset; executable code is
shared. NAM retains its existing build profile and storage.

## Implementation

`tools/microlooper_definition.py` declares both models, controls, native ports,
private allocations and callbacks. `tools/effect_model.py` compiles those
declarations into matching model, state and control tables. Stereo is model 380,
primitive `0x012e`; mono is model 381, primitive `0x0100`.

Loop is public slot 6, DSP PID 15. Play and Overdub are hidden slots 7/8, DSP
PIDs 10/11. The initializer clears all three inputs and the first-process marker.
Transport writes during construction are ignored. The native delay record has
eight declared controls and its trailing boolean: nine preset values.

`src/m4/microlooper.s` discovers native Controller Assign records for Loop and
feeds their physical press/release events to `microlooper_gesture.s`. It owns
Play/Overdub delivery, retries failed writes and cancels held gestures when
assignment or block ownership changes. Restored parameter levels cannot trigger
capture. The native bypass dispatcher is unchanged.

Controller records are copied under their mutex and used under the graph mutex
after checking a lifecycle epoch. These mutexes are never nested by the adapter.
Binding generations separately distinguish replaced or reused block objects.
The shared input owner composes Loop handling with HXtra's long-press feature.

The SHARC bridge processes 16-frame planar buffers directly. Private word 14 sets
one or two channels; history advances by that width. The core performs bounded
scalar initialization and uses valid-frame counts instead of clearing history.
The build links repeated processing into the existing internal code gap and
places the remaining code in reserved DDR2. Placement checks cover physical
instruction/data aliases, native heaps, NAM storage, metronome and GR neighbors.

## Verification

```sh
python3 tools/verify_atmosphere_candidate.py \
  build/HX_Stomp_v3.80.0_HXtra.hxf --report build/microlooper-build.json
```

The verifier checks archive integrity, model declarations, native callback
records, allocation and physical storage. It executes the built callbacks
through the stock calling convention and compares emitted audio instructions
against the independent C++ reference. Tests cover both widths, all modes,
capture/overdub transitions, memory bounds, register preservation, native preset
serialization, footswitch assignments, snapshots, bypass and graph lifecycles.
