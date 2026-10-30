#pragma once
#include <windows.h>
#include <algorithm>
#include <cmath>

// Opaque Win64 member-call adapter for the pinned, hash-checked SDR++ core.
// The object is the core's exported real IQFrontEnd; no size/layout is copied.
// Signatures match iq_frontend.h; Win64 passes this as the first argument.
struct CoreFft {
    void *object=nullptr;
    using Set=void(*)(void *,double);
    using Get=double(*)(void *);
    Set set=nullptr;Get get=nullptr;
    bool bind(HMODULE module) {
        if(!module)return false;
        object=reinterpret_cast<void *>(GetProcAddress(module,"iqFrontEnd"));
        set=reinterpret_cast<Set>(GetProcAddress(module,"?setFFTRate@IQFrontEnd@@QEAAXN@Z"));
        get=reinterpret_cast<Get>(GetProcAddress(module,"?getEffectiveSamplerate@IQFrontEnd@@QEAANXZ"));
        if(object && set && get)return true;
        object=nullptr;set=nullptr;get=nullptr;return false;
    }
    static double pacedRate(double sampleRate,int fftSize,double userRate) {
        if(!std::isfinite(sampleRate) || sampleRate<=0 || fftSize<256 || fftSize>1048576 ||
            !std::isfinite(userRate) || userRate<1 || userRate>10000)return 0;
        // Avoid turning tiny FFTs into an unbounded callback workload.
        return std::max(userRate,sampleRate/std::max(fftSize,8192));
    }
};

struct FftPacer {
    CoreFft core;
    bool active=false;
    double rate=0,userRate=20,lastFs=0;
    int lastSize=0;
    void restore(double configuredRate=0) {
        if(std::isfinite(configuredRate) && configuredRate>=1 && configuredRate<=10000)userRate=configuredRate;
        if(active)core.set(core.object,userRate);
        active=false;rate=0;lastSize=0;lastFs=0;
    }
    bool update(bool enabled,int size,double configuredRate) {
        double fs=core.get(core.object);
        double wanted=CoreFft::pacedRate(fs,size,configuredRate);
        if(!enabled || !wanted){restore(configuredRate);return false;}
        bool changed=!active || size!=lastSize || fs!=lastFs || configuredRate!=userRate || wanted!=rate;
        userRate=configuredRate;lastSize=size;lastFs=fs;rate=wanted;
        if(changed)core.set(core.object,rate);
        active=true;return true;
    }
};
