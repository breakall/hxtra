// SPDX-License-Identifier: GPL-3.0-or-later
// Looper-only extraction of Atmosphere v0.3.0, firmware/engine.h and engine.cpp.
// Source SHA-256: engine.h de73d92ad04cd35e9af11754363a6da088bb3ab7e5d0177a4a309e7dbfcb4988
// engine.cpp 906e5606cf82c48fa8d2ffe3436427fefad12152025df766cd90657fb58407d1
// Desktop oracle for the SHARC port, not firmware code or a timing estimate.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstddef>

namespace microlooper {
struct Stereo {
    float l = 0, r = 0;
    Stereo operator+(Stereo b) const { return {l + b.l, r + b.r}; }
    Stereo operator-(Stereo b) const { return {l - b.l, r - b.r}; }
    Stereo operator*(float gain) const { return {l * gain, r * gain}; }
};
inline float Clamp(float v, float lo, float hi) { return std::max(lo, std::min(v, hi)); }
inline float Wrap(float p, float size) {
    p = std::fmod(p, size);
    return p < 0 ? p + size : p;
}
inline Stereo Protect(Stereo s) { return {Clamp(s.l, -1, 1), Clamp(s.r, -1, 1)}; }
enum class Mode { Envelope, Tape, Stretch };
struct Parameters {
    float mix = .5f, clock = 1, length = .5f, modify = .75f;
    Mode mode = Mode::Tape;
};

// Each instance owns its history. Configure and transport setters do no allocation.
// Call Init before use. Audio processing is at 48 kHz. Controls are finite values;
// their normalized ranges are clamped. Caller translates switch/snapshot events.
class Reference {
  public:
    static constexpr size_t kLoopFrames = 24000;
    void Init() {
        // Valid counts prevent reading old history; do not clear a large ring
        // in an audio callback. Empty capture initializes only its one frame.
        write_ = recorded_ = loop_start_ = dub_write_ = 0;
        loop_size_ = 1;
        play_ = transport_ = grain_phase_ = env_ = slice_start_ = 0;
        grain_anchor_[0] = grain_anchor_[1] = 0;
        env_held_ = false;
        held_ = previous_ = transition_from_ = {};
        mix_ = effect_gain_ = 0; transition_ = 1;
        divider_ = 1; tick_count_ = 0;
        playing_ = overdub_ = false;
        p_ = Parameters{};
    }
    void Configure(Parameters p) {
        p.mix = Clamp(p.mix, 0, 1); p.clock = Clamp(p.clock, 0, 1);
        p.length = Clamp(p.length, 0, 1); p.modify = Clamp(p.modify, 0, 1);
        if(p.mode != p_.mode) {
            transition_from_ = held_; transition_ = 0; env_held_ = false;
        }
        p_ = p;
        int step = 0;
        for(unsigned d = divider_; d > 1; d >>= 1) ++step;
        const float desired = (1 - p.clock) * 4;
        while(step < 4 && desired > float(step) + .58f) ++step;
        while(step > 0 && desired < float(step) - .58f) --step;
        divider_ = 1u << step;
    }
    void SetPlaying(bool on) {
        if(on == playing_) return;
        transition_from_ = held_; transition_ = 0;
        playing_ = on; overdub_ = false;
        if(on) {
            loop_size_ = std::max(size_t(1), recorded_);
            loop_start_ = (write_ + kLoopFrames - loop_size_) % kLoopFrames;
            if(recorded_ == 0) frames_[loop_start_] = {};
            play_ = transport_ = grain_phase_ = 0;
            grain_anchor_[0] = grain_anchor_[1] = 0;
            dub_write_ = 0; env_held_ = false;
        } else recorded_ = 0;
    }
    void SetOverdub(bool on) { overdub_ = on && playing_; }
    bool Playing() const { return playing_; }
    bool Overdubbing() const { return overdub_; }
    unsigned ClockDivider() const { return divider_; }
    size_t RecordedFrames() const { return recorded_; }
    Stereo ProcessStereo(Stereo input) {
        if(++tick_count_ >= divider_) {
            tick_count_ = 0; previous_ = held_; held_ = Tick(input);
        }
        const float fraction = float(tick_count_) / float(divider_);
        const Stereo processed = previous_ + (held_ - previous_) * fraction;
        mix_ += (p_.mix - mix_) * .002f;
        if(std::fabs(p_.mix - mix_) < .0001f) mix_ = p_.mix;
        const float target = playing_ ? 1.f : 0.f;
        effect_gain_ += (target - effect_gain_) * .002f;
        if(std::fabs(target - effect_gain_) < .0001f) effect_gain_ = target;
        const float amount = mix_ * effect_gain_;
        return Protect(input * (1 - amount) + processed * amount);
    }
  private:
    static float SpliceWidth(float length) { return std::min(240.f, length * .125f); }
    static float SplicedLength(float length) { return length - SpliceWidth(length); }
    Stereo LoopRead(float position, float length) const {
        const float seam = SpliceWidth(length), period = length - seam;
        position = Wrap(position, period);
        auto at = [&](float x) {
            const size_t a = size_t(x);
            const size_t b = a + 1 < size_t(std::ceil(length)) ? a + 1 : 0;
            const Stereo first = frames_[(loop_start_ + a) % kLoopFrames];
            return first + (frames_[(loop_start_ + b) % kLoopFrames] - first) * (x - float(a));
        };
        if(position >= seam) return at(position);
        const float blend = position / seam;
        return at(period + position) * (1 - blend) + at(position) * blend;
    }
    Stereo Loop(Stereo input) {
        if(!playing_) return {};
        const float energy = std::max(std::fabs(input.l), std::fabs(input.r));
        env_ += (energy - env_) * (energy > env_ ? .02f : .0008f);
        const float full = float(loop_size_);
        Stereo result;
        if(p_.mode == Mode::Tape) {
            const float length = std::max(1.f, full * (.02f + .98f * p_.length * p_.length));
            result = LoopRead(play_, length);
            static constexpr float rates[] = {-4, -2, -1, -.5f, .5f, 1, 2, 4};
            play_ = Wrap(play_ + rates[std::min(7, int(p_.modify * 8))], SplicedLength(length));
            transport_ = play_;
        } else if(p_.mode == Mode::Envelope) {
            const float slice = std::min(full, 48 + p_.length * p_.length * (full - 1));
            const float threshold = .25f * std::exp2(-9 * p_.modify);
            const bool detected = env_ > threshold * (env_held_ ? .7f : 1.f);
            if(detected && !env_held_) { slice_start_ = transport_; play_ = 0; }
            env_held_ = detected;
            if(detected) {
                // A shorter LENGTH can put the previous head outside this slice.
                // Wrap before reading/fading, not only after: avoid negative gain.
                play_ = Wrap(play_, slice);
                result = LoopRead(slice_start_ + play_, full);
                const float edge = std::min(32.f, slice * .125f);
                result = result * std::min(1.f, std::min(play_, slice - play_) / edge);
                play_ = Wrap(play_ + 1, slice);
            } else {
                result = LoopRead(transport_, full);
                transport_ = Wrap(transport_ + 1, SplicedLength(full));
            }
        } else {
            const float grain = std::min(full, 96 + p_.length * p_.length * 16000);
            const float speed = p_.modify * 2 - 1;
            const float scan = speed * std::fabs(speed);
            const float phase[] = {grain_phase_, Wrap(grain_phase_ + .5f, 1)};
            for(int g = 0; g < 2; ++g) {
                const float weight = 1 - std::fabs(phase[g] * 2 - 1);
                result = result + LoopRead(grain_anchor_[g] + phase[g] * grain, full) * weight;
            }
            transport_ = Wrap(transport_ + scan, SplicedLength(full));
            const float next = grain_phase_ + 1 / grain;
            if(grain_phase_ < .5f && next >= .5f) grain_anchor_[1] = transport_;
            if(next >= 1) grain_anchor_[0] = transport_;
            grain_phase_ = Wrap(next, 1); play_ = transport_;
        }
        if(overdub_) {
            auto& frame = frames_[(loop_start_ + dub_write_) % kLoopFrames];
            frame = Protect(frame * .9995f + input * .5f);
            dub_write_ = (dub_write_ + 1) % loop_size_;
        }
        return result;
    }
    Stereo Tick(Stereo input) {
        Stereo processed = Loop(input);
        if(!playing_) {
            frames_[write_] = Protect(input); write_ = (write_ + 1) % kLoopFrames;
            recorded_ = std::min(recorded_ + 1, kLoopFrames);
        }
        if(transition_ < 1) {
            transition_ = std::min(1.f, transition_ + 1.f / 240);
            processed = transition_from_ * (1 - transition_) + processed * transition_;
        }
        return processed;
    }
    Parameters p_;
    Stereo frames_[kLoopFrames];
    size_t write_ = 0, recorded_ = 0, loop_start_ = 0, loop_size_ = 1, dub_write_ = 0;
    float play_ = 0, transport_ = 0, grain_phase_ = 0, grain_anchor_[2] = {0, 0};
    float env_ = 0, slice_start_ = 0;
    Stereo held_, previous_, transition_from_;
    float mix_ = 0, effect_gain_ = 0, transition_ = 1;
    unsigned divider_ = 1, tick_count_ = 0;
    bool playing_ = false, overdub_ = false, env_held_ = false;
};
} // namespace microlooper
