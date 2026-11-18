// SPDX-License-Identifier: GPL-3.0-or-later
// Binary little-endian command stream; the audio algorithm is the pinned source.
#include "glasshouse/reference.h"
#include <cstdio>
#include <cstdint>
#include <cstdlib>

template<class T> bool Read(T &value) {
    return std::fread(&value, sizeof(value), 1, stdin) == 1;
}
bool Settings(glasshouse::Settings &s) {
    for (auto &page : s.knob) for (float &v : page) if (!Read(v)) return false;
    for (auto &page : s.toggle) for (auto &v : page) {
        uint32_t raw;
        if (!Read(raw) || raw > 2) return false;
        v = static_cast<uint8_t>(raw);
    }
    return s.Valid();
}
bool Write(float a, float b) {
    return std::fwrite(&a, sizeof(a), 1, stdout) == 1
        && std::fwrite(&b, sizeof(b), 1, stdout) == 1;
}
int main() {
    glasshouse::Engine engine;
    engine.Init(48000);
    uint32_t command;
    while (Read(command)) {
        if (command == 0 || command == 1) {
            float rate = 48000;
            glasshouse::Settings settings;
            if ((command == 0 && (!Read(rate) || rate != 48000)) || !Settings(settings)) return 2;
            if (command == 0) engine.Init(rate, settings);
            else engine.SetSettings(settings);
        } else if (command >= 2 && command <= 4) {
            uint32_t value;
            if (!Read(value) || value > 1) return 2;
            if (command == 2) engine.SetBypass(!value);
            if (command == 3) engine.SetAux(value);
            if (command == 4) engine.SetSag(value);
        } else if (command == 5) {
            uint32_t frames;
            if (!Read(frames) || frames > 10000000) return 2;
            for (uint32_t frame = 0; frame < frames; ++frame) {
                float left, right, out_left, out_right;
                if (!Read(left) || !Read(right) || !std::isfinite(left) || !std::isfinite(right)) return 2;
                engine.Process(left, right, out_left, out_right);
                if (!Write(out_left, out_right)) return 3;
            }
        } else if (command == 6) {
            if (!Write(engine.Reduction(), engine.Swell())) return 3;
        } else return 2;
    }
    return std::ferror(stdin) || std::fflush(stdout) != 0 ? 3 : 0;
}
