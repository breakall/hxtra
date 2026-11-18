// SPDX-License-Identifier: GPL-3.0-or-later
// Deterministic controls at16-sample boundaries; oracle uses the same module as desktop tests.
#include "microlooper/reference.h"
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <memory>
int main(int argc, char** argv) {
    if(argc != 6 && argc != 7 && argc != 8) return 2;
    const int channels=argc == 8 ? std::atoi(argv[7]) : 2;
    if(channels != 1 && channels != 2) return 2;
    auto engine=std::make_unique<microlooper::Reference>(); engine->Init();
    microlooper::Parameters p;
    p.mode=microlooper::Mode(std::atoi(argv[1])); p.clock=std::strtof(argv[2],nullptr);
    p.modify=std::strtof(argv[3],nullptr); p.length=.63f;p.mix=.8f;engine->Configure(p);
    int capture=std::atoi(argv[4]), playback=std::atoi(argv[5]);
    const bool changes=argc >= 7 && std::strcmp(argv[6],"changes")==0;
    const bool shrink=argc >= 7 && std::strcmp(argv[6],"shrink")==0;
    const bool stale=argc >= 7 && std::strcmp(argv[6],"stale")==0;
    if(shrink) {p.length=1;engine->Configure(p);}
    bool old_dub_level=false;
    auto dub_level=[&](bool level) {
        // A raw parameter is a level, not a same-value setter event.
        if(level!=old_dub_level) {old_dub_level=level;engine->SetOverdub(level);}
    };
    for(int i=0;i<capture+playback;++i) {
        if(i==capture)engine->SetPlaying(true);
        if(!shrink && !stale) {
            if(i==capture+64)engine->SetOverdub(true);
            if(i==capture+128)engine->SetOverdub(false);
        }
        if(shrink && i==capture+23008) {p.length=.0000374f;engine->Configure(p);}
        if(stale) {
            if(i==32 || i==capture+32 || i==capture+96 || i==capture+112 || i==capture+208) dub_level(true);
            if(i==capture+64 || i==capture+192) dub_level(false);
            if(i==capture+128)engine->SetPlaying(false);
            if(i==capture+160)engine->SetPlaying(true);
        }
        if(changes) {
            if(i==capture+32) {p.length=.05f;engine->Configure(p);}
            if(i==capture+80) {p.mode=microlooper::Mode((std::atoi(argv[1])+1)%3);engine->Configure(p);}
            if(i==capture+128) {p.clock=1-p.clock;engine->Configure(p);}
            if(i==capture+160)engine->SetPlaying(false);
            if(i==capture+192)engine->SetPlaying(true);
        }
        microlooper::Stereo in{float((i*37)%127-63)/256.f,float((i*19)%113-56)/256.f};
        if(stale) in=i<capture ? microlooper::Stereo{} : microlooper::Stereo{.25f,.125f};
        if(channels == 1) in.r=0;
        auto out=engine->ProcessStereo(in);
        if(std::fwrite(&out,sizeof(out),1,stdout)!=1)return 3;
    }
}
