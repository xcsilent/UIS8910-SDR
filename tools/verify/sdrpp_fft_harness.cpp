#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <atomic>
#include <cassert>
#include <cmath>
#include <iostream>
#include <vector>
#include <dsp/stream.h>
#include <dsp/types.h>
#include "../../host/sdrpp/CoreFft.hpp"

struct Output {
    std::vector<float> data=std::vector<float>(65536);
    std::atomic<unsigned> frames{0},badPeak{0};
    static float *acquire(void *p){return static_cast<Output *>(p)->data.data();}
    static void release(void *p){
        auto &o=*static_cast<Output *>(p);
        size_t peak=size_t(std::max_element(o.data.begin(),o.data.end())-o.data.begin());
        double hz=(double(peak)-32768)*30720000/65536;
        if(std::abs(hz-150000)>3000)++o.badPeak;
        ++o.frames;
    }
};
int main(){
    HMODULE module=LoadLibraryW(L"sdrpp_core.dll");assert(module);
    CoreFft fft;assert(fft.bind(module));
    using Init=void(*)(void *,dsp::stream<dsp::complex_t> *,double,bool,int,bool,int,double,int,float *(*)(void *),void(*)(void *),void *);
    using Action=void(*)(void *);
    auto init=reinterpret_cast<Init>(GetProcAddress(module,"?init@IQFrontEnd@@QEAAXPEAV?$stream@Ucomplex_t@dsp@@@dsp@@N_NH1HNW4FFTWindow@1@P6APEAMPEAX@ZP6AX3@Z3@Z"));
    auto start=reinterpret_cast<Action>(GetProcAddress(module,"?start@IQFrontEnd@@QEAAXXZ"));
    auto stop=reinterpret_cast<Action>(GetProcAddress(module,"?stop@IQFrontEnd@@QEAAXXZ"));
    assert(init && start && stop);
    dsp::stream<dsp::complex_t> input;Output output;
    init(fft.object,&input,30720000,false,1,false,65536,20,1,Output::acquire,Output::release,&output);
    auto run=[&](){
        assert(fft.get(fft.object)==30720000);
        output.frames=0;output.badPeak=0;input.clearWriteStop();start(fft.object);
        for(unsigned block=0;block<1024;++block){
            for(unsigned i=0;i<2000;++i){double phase=2*3.141592653589793*150000*(block*2000u+i)/30720000;
                input.writeBuf[i]={float(std::cos(phase)),float(std::sin(phase))};}
            assert(input.swap(2000));
        }
        // Allow the asynchronous core pipeline to finish its complete windows.
        Sleep(250);stop(fft.object);
        assert(!output.badPeak);return output.frames.load();
    };
    fft.set(fft.object,20);
    unsigned baseline=run();
    FftPacer pacing;pacing.core=fft;
    assert(pacing.update(true,65536,20) && pacing.active);
    double rate=pacing.rate;
    assert(rate==468.75 && !CoreFft::pacedRate(0,65536,20));
    unsigned paced=run();
    pacing.restore();assert(!pacing.active && pacing.rate==0);
    unsigned restored=run();
    assert(!pacing.update(false,65536,20));
    assert(pacing.update(true,65536,30));
    assert(!pacing.update(false,65536,30) && !pacing.active);
    unsigned restoredChanged=run();
    assert(baseline==1 && paced==31 && restored==1 && restoredChanged==2);
    std::cout<<"{\"status\":\"passed\",\"actual_core_fft\":true,\"sample_rate_hz\":30720000,\"fft_size\":65536,\"input_pairs_per_run\":2048000,\"baseline_frames\":"<<baseline
        <<",\"paced_frames\":"<<paced<<",\"restored_frames\":"<<restored<<",\"restored_changed_user_rate_frames\":"<<restoredChanged<<",\"paced_rate_setting\":"<<rate<<",\"frequency_axis_verified\":true}\n";
    // Destruct the DLL's global frontend while its input/callbacks still live.
    FreeLibrary(module);
}
