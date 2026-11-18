// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "settings.h"

namespace glasshouse {
constexpr float kPi = 3.14159265358979323846f;
inline float Follow(float state, float target, float attack, float release) {
    return target + (state - target) * (target > state ? attack : release);
}
inline float Pole(float seconds, float rate) { return std::exp(-1.0f / (seconds * rate)); }

// Trapezoidal one-pole integrator. Stable under coefficient modulation.
struct OnePole {
    float z = 0;
    float Low(float x, float g) {
        const float v = (x - z) * g / (1.0f + g);
        const float y = v + z;
        z = y + v;
        return y;
    }
};

// Symmetric soft clipping, with first-order antiderivative antialiasing.
// f(x)=x/(1+abs(x)); integral F(x)=abs(x)-log(1+abs(x)).
struct SoftClip {
    float previous = 0;
    static float Integral(float x) { const float a = std::fabs(x); return a - std::log1p(a); }
    float Process(float x) {
        const float d = x - previous;
        const float y = std::fabs(d) < 0.001f
            ? (0.5f * (x + previous)) / (1.0f + std::fabs(0.5f * (x + previous)))
            : (Integral(x) - Integral(previous)) / d;
        previous = x;
        return y;
    }
};

struct Channel {
    OnePole sidechain, pre, post, eq;
    SoftClip clip;
    float envelope = 0, slow = 0, reduction = 0;
    float spring = 0, velocity = 0, activity = 0, gate = 1, swell = 1;
    float sag_gain = 1;
    float attack = 0, release = 0, filter_g = 0;
    bool manual_dip = false;
};

class Engine {
public:
    void Init(float rate, const Settings &initial = Settings{}) {
        params_ = initial;
        for (auto &c : channel_) c = {};
        phase_ = ramp_phase_ = bypass_mix_ = sag_mix_ = 0;
        control_counter_ = 0;
        bypassed_ = true;
        aux_ = sag_ = false;
        rate_ = rate;
        smooth_ = Pole(0.008f, rate_);
        sag_smooth_ = Pole(0.05f, rate_);
        det_attack_ = Pole(0.001f, rate_);
        det_release_ = Pole(0.03f, rate_);
        slow_coeff_ = Pole(0.2f, rate_);
        gate_attack_ = Pole(0.002f, rate_);
        eq_g_ = std::tan(kPi * 950.0f / rate_);
        for (int i = 0; i < 6; ++i) smooth_knob_[i] = params_.knob[0][i];
        SetSettings(params_);
    }
    void SetSettings(const Settings &s) {
        params_ = s;
        attack_seconds_ = LogRange(s.knob[0][3], 0.0005f, 0.3f);
        release_seconds_ = s.toggle[0][0] == 0 ? 0.05f
            : (s.toggle[0][0] == 2 ? 1.5f : LogRange(s.knob[1][4], 0.05f, 1.5f));
        attack_coeff_ = Pole(attack_seconds_, rate_);
        release_coeff_ = Pole(release_seconds_, rate_);
        gate_release_ = Pole(LogRange(s.knob[1][1], 0.02f, 1.5f), rate_);
        gate_threshold_ = DbGain(Mix(-80.0f, -30.0f, s.knob[1][0]));
        swell_in_step_ = 1.0f / (LogRange(s.knob[1][2], 0.01f, 4.0f) * rate_);
        swell_out_step_ = 1.0f / (LogRange(s.knob[1][3], 0.01f, 4.0f) * rate_);
        sc_g_ = std::tan(kPi * LogRange(s.knob[1][5], 20.0f, 1200.0f) / rate_);
        motion_hz_ = LogRange(1.0f - s.knob[0][3], 0.08f, 12.0f);
        ramp_hz_ = LogRange(s.knob[2][1], 0.03f, 8.0f);
        emphasis_ = s.toggle[1][2] * 0.5f; // 0, +3.5, +6 dB high-frequency emphasis
    }
    void SetBypass(bool bypass) {
        if (bypassed_ && !bypass) ramp_phase_ = 0;
        bypassed_ = bypass;
    }
    bool Bypassed() const { return bypassed_; }
    void SetAux(bool active) {
        if (active && !aux_ && params_.toggle[2][1] == 1)
            for (auto &c : channel_) c.manual_dip = true;
        aux_ = active;
    }
    void SetSag(bool active) { sag_ = active; }
    float Reduction() const { return std::fmax(channel_[0].reduction, channel_[1].reduction); }
    float Swell() const { return channel_[0].swell; }
#ifdef GLASSHOUSE_DIAGNOSTICS
    float DiagnosticAttackSeconds() const {
        const float coefficient = channel_[0].attack;
        return coefficient > 0 && coefficient < 1 ? -1.0f / (rate_ * std::log(coefficient)) : 0;
    }
    float DiagnosticReleaseSeconds() const {
        const float coefficient = channel_[0].release;
        return coefficient > 0 && coefficient < 1 ? -1.0f / (rate_ * std::log(coefficient)) : 0;
    }
#endif

    void Process(float left, float right, float &out_left, float &out_right) {
        // Remap knobs and filter coefficients at 3 kHz; envelope and gain stay audio rate.
        const bool control_tick = control_counter_++ % 16 == 0;
        // Footswitch/MIDI sag changes must not step the ratio or limiter ceiling.
        const float sag_target = sag_ ? 1.0f : 0.0f;
        sag_mix_ = sag_target + sag_smooth_ * (sag_mix_ - sag_target);
        // A cable's right input is never inferred from signal amplitude.
        const bool sidechain = params_.toggle[2][0] == 2;
        const bool mono = params_.toggle[2][0] != 1;
        const float audio[2] = {left, mono ? left : right};
        const float detector[2] = {sidechain ? right : audio[0], sidechain ? right : audio[1]};
        const bool spread = params_.toggle[2][2] == 2;
        const bool volume_spread = spread && params_.toggle[1][1] != 0;
        const bool eq_spread = spread && params_.toggle[1][1] != 2;
        const bool independent = params_.toggle[2][2] == 1 || volume_spread;
        const float depth = params_.knob[2][0];

        phase_ += motion_hz_ / rate_;
        if (phase_ >= 1.0f) phase_ -= 1.0f;
        ramp_phase_ += ramp_hz_ / rate_;
        if (params_.toggle[3][0] == 2 && ramp_phase_ >= 1.0f) ramp_phase_ -= 1.0f;
        else if (params_.toggle[3][0] != 2) ramp_phase_ = Clamp(ramp_phase_);
        float ramp = params_.toggle[3][0] == 2
            ? 1.0f - std::fabs(2.0f * (ramp_phase_ - std::floor(ramp_phase_)) - 1.0f)
            : Clamp(ramp_phase_);
        if (params_.toggle[3][2] == 1) ramp = 0.5f - 0.5f * std::cos(kPi * ramp);
        if (params_.toggle[3][2] == 2) ramp = ramp >= 0.5f ? 1.0f : 0.0f;
        if (params_.toggle[3][1] == 1) ramp = 1.0f - ramp;
        float knob[6];
        for (int i = 0; i < 6; ++i) {
            float target = params_.knob[0][i];
            if (params_.toggle[3][0] != 0) {
                const float range = params_.knob[3][i];
                const float mod = params_.toggle[3][1] == 2
                    ? Clamp(target + range * (2.0f * ramp - 1.0f))
                    : Mix(target * (1.0f - range), target, ramp);
                target = mod;
            }
            smooth_knob_[i] = target + smooth_ * (smooth_knob_[i] - target);
            knob[i] = smooth_knob_[i];
        }
        if (control_tick) {
            threshold = DbGain(Mix(-6.0f, -54.0f, knob[0]));
            dynamics = Mix(knob[1], 1.0f, sag_mix_);
            ratio = dynamics < 0.5f ? LogRange(dynamics * 2.0f, 1.0f, 20.0f)
                : LogRange((dynamics - 0.5f) * 4.0f, 20.0f, 100.0f);
            sag_amount = Clamp((dynamics - 0.75f) * 4.0f);
            attack_scale = LogRange(knob[3], 0.0005f, 0.3f) / attack_seconds_;
            for (int ch = 0; ch < 2; ++ch) {
                volume_motion_[ch] = std::sin(2.0f * kPi * phase_ + (volume_spread ? ch * kPi * depth : 0));
                eq_motion_[ch] = std::sin(2.0f * kPi * phase_ + (eq_spread ? ch * kPi * depth : 0));
                pan_motion_[ch] = std::sin(2.0f * kPi * phase_ + ch * kPi);
            }
        }
        const float wet_gain = knob[2] * knob[2] * 4.0f;
        const float dry_gain = knob[5] * knob[5] * 4.0f;
        float sensed[2];
        for (int ch = 0; ch < 2; ++ch) {
            auto &c = channel_[ch];
            const float sc_low = c.sidechain.Low(detector[ch], sc_g_);
            const float sc = params_.knob[1][5] < 0.005f ? detector[ch] : detector[ch] - sc_low;
            sensed[ch] = std::fabs(sc);
        }
        if (!independent) sensed[0] = sensed[1] = std::fmax(sensed[0], sensed[1]);
        float output[2];
        for (int ch = 0; ch < 2; ++ch) {
            auto &c = channel_[ch];
            c.envelope = Follow(c.envelope, sensed[ch], det_attack_, det_release_);
            c.slow = Follow(c.slow, sensed[ch], slow_coeff_, slow_coeff_);
            const bool triggered = c.envelope > threshold;
            c.activity = Follow(c.activity, triggered ? 1.0f : 0.0f, attack_coeff_, release_coeff_);
            float x = audio[ch];
            const float pre_low = c.pre.Low(x, eq_g_);
            x += emphasis_ * (x - pre_low);

            // Derive gain from the input detector. Feeding delayed, compressed
            // audio back through (R-1) made high ratios oscillate on held notes.
            // The feedforward law retains the steady-state R:1 transfer curve.
            float target_db = std::fmax(0.0f, GainDb(c.envelope / threshold)) * (1.0f - 1.0f / ratio);
            target_db = Clamp(target_db, 0.0f, 72.0f);
            if (params_.knob[2][3] > 0.5f)
                target_db *= 0.5f + 0.5f * volume_motion_[ch];

            const unsigned env_mode = params_.toggle[1][0];
            const float transient = Clamp(c.envelope / (c.slow + 1.0e-6f) - 1.0f, 0.0f, 5.0f);
            if (control_tick) {
                c.attack = (env_mode == 2 || attack_scale != 1.0f)
                    ? Pole(attack_seconds_ * attack_scale / (env_mode == 2 ? 1.0f + transient * 3.0f : 1.0f), rate_)
                    : attack_coeff_;
                c.release = env_mode != 0
                    ? Pole(release_seconds_ / (1.0f + transient * 2.0f), rate_) : release_coeff_;
            }
            c.reduction = Follow(c.reduction, target_db, c.attack, c.release);
            float gr = c.reduction;
            if (params_.toggle[0][2] != 1) {
                const bool wild = params_.toggle[0][2] == 2;
                const float frequency = wild ? 11.0f : 3.0f;
                const float omega = 2.0f * kPi * frequency;
                const float damping = wild ? 0.12f : 0.38f;
                const float target = Clamp(c.reduction / 24.0f);
                c.velocity += (omega * omega * (target - c.spring)
                    - 2.0f * damping * omega * c.velocity) / rate_;
                c.spring += c.velocity / rate_;
                gr += (c.spring - target) * (wild ? 14.0f : 5.0f);
            }
            gr = Clamp(gr, 0.0f, 72.0f);
            const float sag_gain = 1.0f / (1.0f + sag_amount * 6.0f * std::pow(c.envelope / threshold, 2.0f));
            // The nonlinear sag curve can turn a tiny depth change into a large
            // gain jump. Smooth the resulting gain as well as the sag control.
            c.sag_gain = sag_gain + sag_smooth_ * (c.sag_gain - sag_gain);
            x *= DbGain(-gr) * c.sag_gain;
            // Exact inverse of pre-emphasis for unity gain / static compression.
            const float post_g = eq_g_ / (1.0f + emphasis_);
            const float post_low = c.post.Low(x, post_g);
            x = post_low + (x - post_low) / (1.0f + emphasis_);

            float eq = (knob[4] - 0.5f) * 2.0f;
            if (std::fabs(eq) < 0.025f) eq = 0;
            if (params_.toggle[0][1] == 0) eq *= 1.0f - c.activity;
            if (params_.toggle[0][1] == 2)
                eq *= 1.0f - 0.65f * c.activity * (0.5f + 0.5f * eq_motion_[ch]);
            if (control_tick) {
                const float cutoff = eq < 0 ? LogRange(1.0f + eq, 220.0f, 18000.0f)
                                           : LogRange(eq, 25.0f, 2200.0f);
                c.filter_g = std::tan(kPi * cutoff / rate_);
            }
            const float eq_low = c.eq.Low(x, c.filter_g);
            const float filtered = eq < 0 ? eq_low : x - eq_low;
            x = Mix(x, filtered, Clamp(std::fabs(eq) * 8.0f));
            if (eq_spread) x *= 1.0f - depth * c.activity * 0.45f
                * (1.0f + pan_motion_[ch]);

            c.gate = Follow(c.gate, c.envelope >= gate_threshold_ ? 1.0f : 0.0f,
                            gate_attack_, gate_release_);
            const bool manual = params_.toggle[2][1] == 1;
            const bool auto_swell = params_.toggle[2][1] == 2 || (aux_ && !manual);
            const float swell_target = manual ? (aux_ || c.manual_dip ? 0.0f : 1.0f)
                                             : (auto_swell ? (triggered ? 1.0f : 0.0f) : 1.0f);
            const float spread_scale = volume_spread ? 1.0f + ch * depth : 1.0f;
            c.swell += Clamp(swell_target - c.swell, -swell_out_step_ / spread_scale,
                            swell_in_step_ / spread_scale);
            if (c.swell <= 0.0f) c.manual_dip = false;
            float y = (x * wet_gain + audio[ch] * dry_gain) * c.swell;
            if (params_.knob[2][2] > 0.5f) y *= c.gate;
            if (params_.knob[2][4] > 0.5f) {
                const float ceiling = DbGain(Mix(-3.0f, -30.0f, knob[0]));
                y = ceiling * c.clip.Process(y / ceiling);
            } else {
                // Final sample-peak limiter; no lookahead delay on the dry branch.
                const float ceiling = Mix(0.98f, 0.75f, dynamics);
                y = Clamp(y, -ceiling, ceiling);
            }
            output[ch] = y;
        }
        bypass_mix_ = (bypassed_ ? 0.0f : 1.0f) + smooth_ * (bypass_mix_ - (bypassed_ ? 0.0f : 1.0f));
        if (std::fabs(bypass_mix_ - (bypassed_ ? 0.0f : 1.0f)) < 0.00005f)
            bypass_mix_ = bypassed_ ? 0.0f : 1.0f;
        out_left = Mix(audio[0], output[0], bypass_mix_);
        out_right = Mix(audio[1], output[1], bypass_mix_);
    }
private:
    // No dynamic memory, delays, logging or hardware access on the audio path.
    Settings params_;
    Channel channel_[2];
    float rate_ = 48000, phase_ = 0, ramp_phase_ = 0, bypass_mix_ = 0, sag_mix_ = 0;
    float smooth_ = 0, sag_smooth_ = 0, det_attack_ = 0, det_release_ = 0, slow_coeff_ = 0, gate_attack_ = 0;
    float attack_seconds_ = 0.01f, release_seconds_ = 0.65f, attack_coeff_ = 0, release_coeff_ = 0;
    float gate_release_ = 0, gate_threshold_ = 0, swell_in_step_ = 0, swell_out_step_ = 0;
    float sc_g_ = 0, eq_g_ = 0, motion_hz_ = 1, ramp_hz_ = 1, emphasis_ = 0;
    float smooth_knob_[6] = {};
    unsigned control_counter_ = 0;
    float threshold = 0.1f, dynamics = 0, ratio = 1, sag_amount = 0, attack_scale = 1;
    float volume_motion_[2] = {}, eq_motion_[2] = {}, pan_motion_[2] = {};
    bool bypassed_ = true, aux_ = false, sag_ = false;
};
} // namespace glasshouse
