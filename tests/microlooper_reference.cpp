// SPDX-License-Identifier: GPL-3.0-or-later
#include "microlooper/reference.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <memory>

using microlooper::Parameters;
using microlooper::Mode;
using microlooper::Stereo;
using Engine = microlooper::Reference;

[[maybe_unused]] static Stereo Input(int i) {
    return {.3f * std::sin(.113f + 6.2831853f * 137.2f * i / 48000),
            .2f * std::sin(.317f + 6.2831853f * 193.7f * i / 48000)};
}
static void Finite(Stereo out) {
    assert(std::isfinite(out.l) && std::isfinite(out.r));
    assert(std::fabs(out.l) <= 1 && std::fabs(out.r) <= 1);
}
static Stereo TraceInput(int i) {
    // Integer-derived, exactly representable float32 input: no platform libm
    // sine differences in the golden traces.
    auto channel = [](uint32_t x) {
        x ^= x >> 16; x *= 0x7feb352du; x ^= x >> 15;
        x *= 0x846ca68bu; x ^= x >> 16;
        return float(int32_t(x >> 8) - 0x800000) / 33554432.f;
    };
    return {channel(uint32_t(i)), channel(uint32_t(i) ^ 0x9e3779b9u)};
}
static void Trace() {
    auto e = std::make_unique<Engine>();
    for(int mode = 0; mode < 3; ++mode) for(int clock = 0; clock < 5; ++clock)
    for(int speed = 0; speed < 8; ++speed) {
        e->Init(); Parameters p;
        p.mode = Mode(mode); p.clock = 1.f - clock * .25f;
        p.modify = (speed + .5f) / 8; p.mix = .8f; p.length = .63f;
        e->Configure(p);
        for(int i = 0; i < 31729; ++i) e->ProcessStereo(TraceInput(i));
        e->SetPlaying(true);
        for(int i = 0; i < 8192; ++i) {
            if(i == 1024) e->SetOverdub(true);
            if(i == 3072) e->SetOverdub(false);
            if(i == 4096) e->SetPlaying(true); // duplicate write must be a no-op
            const Stereo out = e->ProcessStereo(i < 6144 ? TraceInput(i + 31729) : Stereo{});
            Finite(out);
            assert(std::fwrite(&out, sizeof(out), 1, stdout) == 1);
        }
        e->SetPlaying(false);
        for(int i = 0; i < 193; ++i) e->ProcessStereo(TraceInput(i + 40921));
        e->SetPlaying(true); // partial recapture must not contain old history
        for(int i = 0; i < 512; ++i) {
            const Stereo out = e->ProcessStereo({});
            assert(std::fwrite(&out, sizeof(out), 1, stdout) == 1);
        }
    }
}

static Stereo EnvelopeShortening() {
    auto e = std::make_unique<Engine>(); e->Init(); Parameters p;
    p.mix = 1; p.mode = Mode::Envelope; p.modify = 1; p.length = 1;
    e->Configure(p);
    for(int i = 0; i < 24000; ++i) e->ProcessStereo({.2f, .1f});
    e->SetPlaying(true);
    for(int i = 0; i < 10000; ++i) e->ProcessStereo({.1f, .1f});
    p.length = 0; e->Configure(p);
    e->ProcessStereo({.1f, .1f}); // reconstruction returns the previous held tick
    return e->ProcessStereo({.1f, .1f});
}

static void Transport() {
    auto e = std::make_unique<Engine>(); e->Init(); Parameters p; p.mix = 1;
    e->Configure(p);
    for(int i = 0; i < 30000; ++i) {
        Stereo in = Input(i), out = e->ProcessStereo(in);
        assert(out.l == in.l && out.r == in.r); // exact dry while listening
    }
    assert(e->RecordedFrames() == 24000);
    e->SetPlaying(true); assert(e->Playing());
    float peak = 0;
    for(int i = 0; i < 6000; ++i) {
        auto out = e->ProcessStereo({}); peak = std::max(peak, std::fabs(out.l));
    }
    assert(peak > .2f); // input preceding capture is retained with silent input
    e->SetOverdub(true); assert(e->Overdubbing());
    e->SetPlaying(true); assert(e->Overdubbing()); // idempotent write preserves overdub
    e->SetPlaying(false); assert(!e->Playing() && !e->Overdubbing());
    assert(e->RecordedFrames() == 0);
    e->SetOverdub(true); assert(!e->Overdubbing());
    for(int i = 0; i < 100; ++i) e->ProcessStereo({});
    e->SetPlaying(true);
    for(int i = 0; i < 10000; ++i) e->ProcessStereo({}); // settle transition
    for(int i = 0; i < 512; ++i) {
        auto out = e->ProcessStereo({}); assert(out.l == 0 && out.r == 0);
    }
    // Init after a nonzero capture must never expose stale history.
    e->Init(); e->Configure(p); e->SetPlaying(true);
    for(int i = 0; i < 10000; ++i) {
        auto out = e->ProcessStereo({}); assert(out.l == 0 && out.r == 0);
    }
    // Separate instances must keep distinct histories and stereo channels.
    auto other = std::make_unique<Engine>(); other->Init(); other->Configure(p);
    e->Init(); e->Configure(p);
    for(int i = 0; i < 24000; ++i) {
        e->ProcessStereo({.2f, 0}); other->ProcessStereo({0, -.3f});
    }
    e->SetPlaying(true); other->SetPlaying(true);
    for(int i = 0; i < 10000; ++i) {
        auto a = e->ProcessStereo({}), b = other->ProcessStereo({});
        assert(a.r == 0 && b.l == 0);
        if(i > 9000) { assert(std::fabs(a.l - .2f) < .00001f); assert(std::fabs(b.r + .3f) < .00001f); }
    }
}
static void Clock() {
    auto e = std::make_unique<Engine>();
    for(unsigned step = 0; step < 5; ++step) {
        e->Init(); Parameters p; p.clock = 1.f - step * .25f;
        e->Configure(p); assert(e->ClockDivider() == (1u << step));
        for(int i = 0; i < 24000; ++i) e->ProcessStereo({});
        assert(e->RecordedFrames() == 24000 / (1u << step));
    }
    // Pot jitter inside the hysteresis band does not bounce the divider.
    Parameters p; e->Init(); p.clock = .85f; e->Configure(p);
    assert(e->ClockDivider() == 2);
    p.clock = .87f; e->Configure(p); assert(e->ClockDivider() == 2);
    p.clock = .9f; e->Configure(p); assert(e->ClockDivider() == 1);
}
static void Overdub() {
    auto e = std::make_unique<Engine>(); e->Init(); Parameters p; p.mix = 1;
    e->Configure(p);
    for(int i = 0; i < 24000; ++i) e->ProcessStereo({});
    e->SetPlaying(true); e->SetOverdub(true);
    for(int i = 0; i < 24000; ++i) e->ProcessStereo({.4f, -.2f});
    e->SetOverdub(false);
    for(int i = 0; i < 10000; ++i) {
        auto out = e->ProcessStereo({});
        if(i > 9000) { assert(std::fabs(out.l - .2f) < .00001f); assert(std::fabs(out.r + .1f) < .00001f); }
    }
}
static void Splices() {
    auto e = std::make_unique<Engine>(); float worst = 0;
    for(int mode = 0; mode < 3; ++mode) for(int speed = 0; speed < 8; ++speed)
    for(float length : {.4f, 1.f}) {
        e->Init(); Parameters p; p.mix = 1; p.mode = Mode(mode);
        p.length = length; p.modify = (speed + .5f) / 8;
        e->Configure(p);
        for(int i = 0; i < 31729; ++i) e->ProcessStereo(Input(i));
        e->SetPlaying(true); Stereo previous;
        for(int i = 0; i < 72000; ++i) {
            auto out = e->ProcessStereo({}); Finite(out);
            const float jump = std::max(std::fabs(out.l - previous.l), std::fabs(out.r - previous.r));
            if(i > 2000) { worst = std::max(worst, jump); assert(jump < .045f); }
            previous = out;
        }
    }
    std::printf("48 splice mode/speed/length cases; worst jump %.6f\n", worst);
}

int main(int argc, char** argv) {
    static_assert(sizeof(Stereo) == 8, "stereo oracle uses two float32 samples");
    if(argc == 2 && std::strcmp(argv[1], "--trace") == 0) { Trace(); return 0; }
    assert(argc == 2);
    if(std::strcmp(argv[1], "transport") == 0) Transport();
    else if(std::strcmp(argv[1], "clock") == 0) Clock();
    else if(std::strcmp(argv[1], "overdub") == 0) Overdub();
    else if(std::strcmp(argv[1], "splices") == 0) Splices();
    else if(std::strcmp(argv[1], "shorten-envelope") == 0) {
        const auto out = EnvelopeShortening();
        // Shortening must keep output within the recorded sample range.
        assert(out.l >= 0 && out.l <= .20001f && out.r >= 0 && out.r <= .10001f);
    }
    else return 2;
    return 0;
}
