// SPDX-License-Identifier: GPL-3.0-or-later
#include "glasshouse/reference.h"
#include <cstdio>
#include <cstdlib>
#include <random>

using namespace glasshouse;
int checks = 0;
void Check(bool condition, const char *message) {
    ++checks;
    if (!condition) { std::fprintf(stderr, "FAIL: %s\n", message); std::exit(1); }
}
float Render(Engine &e, float amplitude, float right = -1.0f, float hz = 440.0f, int samples = 96000) {
    double sum = 0;
    for (int i = 0; i < samples; ++i) {
        const float sine = std::sin(2.0f * kPi * hz * i / 48000.0f);
        float l, r;
        e.Process(amplitude * sine, (right < 0 ? amplitude : right) * sine, l, r);
        Check(std::isfinite(l) && std::isfinite(r), "audio must remain finite");
        if (i > samples / 2) sum += l * l;
    }
    return std::sqrt(sum / (samples / 2 - 1)) * std::sqrt(2.0);
}
Settings Neutral() {
    Settings s;
    s.knob[0][0] = 0.125f; // -12 dBFS threshold
    s.knob[0][1] = 0.0f;
    s.knob[0][2] = 0.5f; // unity wet
    s.knob[0][3] = 0.0f;
    s.knob[0][4] = 0.5f;
    s.knob[0][5] = 0;
    s.toggle[1][0] = 0;
    return s;
}
Engine Configured(Settings s) { Engine e; e.Init(48000, s); e.SetBypass(false); return e; }

void SagTransitionTests() {
    // Constant input removes waveform slope: a step here is a switching click.
    for (float attack : {0.0f, 0.5f, 1.0f}) {
        for (float sensitivity : {0.5f, 1.0f}) {
            for (float wet : {0.5f, 1.0f}) {
                Settings s;
                s.knob[0][0] = sensitivity;
                s.knob[0][1] = 0;
                s.knob[0][2] = wet;
                s.knob[0][3] = attack;
                auto e = Configured(s);
                float l = 0, r = 0;
                for (int i = 0; i < 48000; ++i) e.Process(0.2f, 0.2f, l, r);
                const float baseline = l;
                for (bool active : {true, false}) {
                    e.SetSag(active);
                    float maximum_step = 0;
                    for (int i = 0; i < 192000; ++i) {
                        const float previous = l;
                        e.Process(0.2f, 0.2f, l, r);
                        maximum_step = std::fmax(maximum_step, std::fabs(l - previous));
                    }
                    std::printf("Sag %s, Attack %.1f, Sensitivity %.1f, Wet %.1f: max step %.6f\n",
                                active ? "on" : "off", attack, sensitivity, wet, maximum_step);
                    Check(maximum_step < baseline * 0.01f,
                          "sag engagement and release must not abruptly step audio gain");
                    Check(active ? l < baseline * 0.01f : l > baseline * 0.98f,
                          "smoothed sag must still collapse and restore the wet signal");
                }
            }
        }
    }
}

void CompressionStabilityTests() {
    // Hardware listening exposed a watery sustain near noon Dynamics. A steady
    // tone isolates gain oscillation from the beating of real guitar strings.
    for (float dynamics : {0.49f, 0.5f, 0.51f, 0.6f, 0.75f}) {
        for (float attack : {0.25f, 0.5f, 0.75f}) {
            Settings s;
            s.knob[0][0] = 0.5f;
            s.knob[0][1] = dynamics;
            s.knob[0][3] = attack;
            auto e = Configured(s);
            float minimum = 100, maximum = 0;
            for (int i = 0; i < 240000; ++i) {
                const float x = 0.2f * std::sin(2.0 * 3.141592653589793 * 110.0 * i / 48000.0);
                float l, r;
                e.Process(x, x, l, r);
                if (i >= 192000) {
                    minimum = std::fmin(minimum, e.Reduction());
                    maximum = std::fmax(maximum, e.Reduction());
                }
            }
            std::printf("Dynamics %.2f, attack %.2f: steady gain swing %.4f dB\n",
                        dynamics, attack, maximum - minimum);
            Check(minimum > 10, "stability must retain strong compression");
            Check(maximum - minimum < 0.05f, "steady tone must not cause compressor gain wobble");
        }
    }
    float reduction[2];
    for (int side = 0; side < 2; ++side) {
        Settings s;
        s.knob[0][0] = 0.5f;
        s.knob[0][1] = side ? 0.501f : 0.499f;
        auto e = Configured(s);
        for (int i = 0; i < 240000; ++i) { float l, r; e.Process(0.2f, 0.2f, l, r); }
        reduction[side] = e.Reduction();
    }
    Check(std::fabs(reduction[1] - reduction[0]) < 0.1f,
          "Dynamics must not jump in compression ratio at noon");
}

void AudioTests() {
    auto s = Neutral();
    auto e = Configured(s);
    const float unity = Render(e, 0.2f);
    std::printf("unity amplitude: %f\n", unity);
    Check(std::fabs(unity - 0.2f) < 0.003f, "unity dynamics and EQ must preserve amplitude");
    for (unsigned emphasis = 0; emphasis < 3; ++emphasis) {
        s.toggle[1][2] = emphasis;
        for (float hz : {80.0f, 1000.0f, 7000.0f}) {
            e = Configured(s);
            Check(std::fabs(Render(e, 0.1f, -1, hz) - 0.1f) < 0.003f, "emphasis pair must cancel at unity gain");
        }
    }
    s = Neutral();
    s.knob[0][1] = std::log(4.0f) / std::log(20.0f) * 0.5f;
    e = Configured(s);
    const float compressed = Render(e, 0.8f);
    std::printf("4:1 compressor: 0.800 input -> %.3f output peak-equivalent\n", compressed);
    // Peak envelope has a finite release; expect near the 4:1 static curve, not exact sample RMS.
    Check(compressed > 0.30f && compressed < 0.45f, "compressor must follow a useful 4:1 law");
    s.knob[0][1] = 0.72f;
    e = Configured(s);
    const float limited = Render(e, 0.8f);
    Check(limited < compressed && limited > 0.20f, "limiting should reduce peaks more than compression");
    s.knob[0][1] = 1.0f;
    e = Configured(s);
    Check(Render(e, 0.8f) < limited * 0.25f, "sag must create additional collapse on loud notes");

    s = Neutral();
    s.toggle[2][0] = 1; // True stereo; preserve channel separation even in bypass.
    e = Configured(s);
    e.SetBypass(true);
    for (int i = 0; i < 4800; ++i) { float l, r; e.Process(0.25f, -0.4f, l, r); }
    float l, r;
    e.Process(0.25f, -0.4f, l, r);
    Check(std::fabs(l - 0.25f) < 1.0e-6f && std::fabs(r + 0.4f) < 1.0e-6f,
          "stereo bypass must preserve independent channels");
    s = Neutral(); s.toggle[2][0] = 1; s.knob[0][1] = 0.35f;
    e = Configured(s);
    double energy_l = 0, energy_r = 0;
    for (int i = 0; i < 144000; ++i) {
        const float wave = std::sin(2 * kPi * 440 * i / 48000);
        e.Process(0.15f * wave, 0.8f * wave, l, r);
        if (i > 96000) { energy_l += l * l; energy_r += r * r; }
    }
    Check(std::fabs(std::sqrt(energy_l / energy_r) - 0.15f / 0.8f) < 0.002f,
          "linked compression must preserve stereo balance");
    s = Neutral(); s.toggle[2][0] = 2; s.knob[0][1] = 0.7f;
    e = Configured(s);
    const float no_key = Render(e, 0.2f, 0);
    e = Configured(s);
    const float keyed = Render(e, 0.2f, 0.9f);
    Check(keyed < no_key * 0.5f, "right-input key must duck left audio");

    s = Neutral(); s.knob[0][2] = 0; s.knob[0][5] = 0.5f;
    s.knob[2][4] = 1; s.knob[0][0] = 0.8f;
    e = Configured(s);
    Check(Render(e, 0.3f) < 0.1f, "Dusty must also affect dry-only mix");
    s = Neutral(); s.knob[2][2] = 1; s.knob[1][0] = 0.6f;
    e = Configured(s);
    Check(Render(e, 0.0001f, -1, 440, 240000) < 1.0e-6f, "gate must mute sustained subthreshold input");
    s = Neutral(); s.toggle[2][1] = 1;
    e = Configured(s);
    Render(e, 0.2f);
    e.SetAux(true);
    Check(Render(e, 0.2f) < 1.0e-6f, "manual swell must mute while held");
    e.SetAux(false);
    Check(Render(e, 0.2f, -1, 440, 240000) > 0.19f, "manual swell must return on release");
    // A one-millisecond tap must finish its dip and create a full swell after release.
    e.SetAux(true);
    for (int i = 0; i < 48; ++i) e.Process(0.2f, 0.2f, l, r);
    e.SetAux(false);
    float minimum = 1;
    for (int i = 0; i < 48000; ++i) { e.Process(0.2f, 0.2f, l, r); minimum = std::fmin(minimum, l); }
    Check(minimum < 0.001f, "short manual tap must complete a swell dip");

    s = Neutral(); s.knob[0][4] = 0.0f;
    e = Configured(s); const float dark_low = Render(e, 0.1f, -1, 80);
    e = Configured(s); const float dark_high = Render(e, 0.1f, -1, 7000);
    Check(dark_high < dark_low * 0.1f, "dark EQ must attenuate treble");
    s.knob[0][4] = 1;
    e = Configured(s); const float bright_low = Render(e, 0.1f, -1, 80);
    e = Configured(s); const float bright_high = Render(e, 0.1f, -1, 7000);
    Check(bright_low < bright_high * 0.1f, "bright EQ must attenuate bass");
    s = Neutral(); s.knob[3][2] = 1; s.toggle[3][0] = 2; s.knob[2][1] = 0.8f;
    e = Configured(s);
    float quiet = 1, loud = 0;
    for (int i = 0; i < 144000; ++i) {
        e.Process(0.1f, 0.1f, l, r);
        if (i > 48000) { quiet = std::fmin(quiet, l); loud = std::fmax(loud, l); }
    }
    Check(quiet < 0.005f && loud > 0.09f, "bounce automation must traverse wet level repeatedly");

    // Repeated automated mode switches, opposing stereo samples and silence.
    std::mt19937 random(7251);
    std::uniform_real_distribution<float> unit(0, 1), audio(-1, 1);
    e.Init(48000);
    e.SetBypass(false);
    for (int block = 0; block < 300; ++block) {
        for (auto &page : s.knob) for (auto &v : page) v = unit(random);
        for (auto &page : s.toggle) for (auto &v : page) v = random() % 3;
        e.SetSettings(s);
        for (int sample = 0; sample < 480; ++sample) {
            e.Process(block % 3 ? audio(random) : 0, audio(random), l, r);
            Check(std::isfinite(l) && std::isfinite(r) && std::fabs(l) <= 1.01f && std::fabs(r) <= 1.01f,
                  "randomized mode changes must remain finite and bounded");
        }
    }
    std::printf("Audio: unity, emphasis, compression, limiting, sag, stereo, sidechain, drive, gate, swells, randomized stability pass\n");
}

int main() { SagTransitionTests(); CompressionStabilityTests(); AudioTests(); std::printf("PASS (%d checks)\n", checks); }
