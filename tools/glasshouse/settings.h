// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <cmath>
#include <cstdint>
#include <cstring>

namespace glasshouse {
inline float Clamp(float x, float lo = 0.0f, float hi = 1.0f) {
    return x < lo ? lo : (x > hi ? hi : x);
}
inline float Mix(float a, float b, float t) { return a + t * (b - a); }
inline float DbGain(float db) { return std::exp(db * 0.11512925465f); }
inline float GainDb(float gain) { return 8.685889638f * std::log(std::fmax(gain, 1.0e-12f)); }
inline float LogRange(float x, float lo, float hi) {
    return lo * std::pow(hi / lo, Clamp(x));
}

// Pages: performance, envelope, options, automation. Positions: up=0, middle=1, down=2.
struct Settings {
    float knob[4][6] = {
        {0.42f, 0.25f, 0.5f, 0.48f, 0.5f, 0.0f},
        {0.35f, 0.5f, 0.6f, 0.5f, 0.75f, 0.0f},
        {0.6f, 0.5f, 0.0f, 0.0f, 0.0f, 0.0f},
        {0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f}
    };
    uint8_t toggle[4][3] = {{1, 1, 1}, {1, 1, 0}, {0, 0, 0}, {0, 0, 0}};
    bool Valid() const {
        for (auto &page : knob)
            for (float v : page)
                if (!std::isfinite(v) || v < 0.0f || v > 1.0f) return false;
        for (auto &page : toggle)
            for (auto v : page) if (v > 2) return false;
        return true;
    }
};
static_assert(sizeof(Settings) == 108, "Preset format must remain fixed");

constexpr unsigned kPresets = 127;
struct Bank {
    uint32_t magic = 0x474c5332; // GLS2
    uint32_t version = 2;
    uint32_t valid[4] = {};
    Settings preset[kPresets];
    uint32_t checksum = 0;
    // Runtime construction keeps repeated preset defaults out of scarce internal flash.
    Bank() { for (auto &s : preset) s = Settings{}; }
    bool Has(unsigned slot) const {
        return slot < kPresets && (valid[slot / 32] & (1u << (slot % 32)));
    }
    void Mark(unsigned slot) { if (slot < kPresets) valid[slot / 32] |= 1u << (slot % 32); }
    uint32_t Checksum() const {
        const auto *bytes = reinterpret_cast<const uint8_t *>(this);
        uint32_t h = 2166136261u;
        for (unsigned i = 0; i < sizeof(Bank) - sizeof(checksum); ++i)
            h = (h ^ bytes[i]) * 16777619u;
        return h;
    }
    void Seal() { checksum = Checksum(); }
    bool Valid() const {
        if (magic != 0x474c5332 || version != 2 || (valid[3] & 0x80000000u) || checksum != Checksum())
            return false;
        for (const auto &s : preset) if (!s.Valid()) return false;
        return true;
    }
    bool operator!=(const Bank &other) const { return std::memcmp(this, &other, sizeof(Bank)) != 0; }
};
} // namespace glasshouse
