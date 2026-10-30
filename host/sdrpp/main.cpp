#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <thread>
#include <cmath>
#include <cstdarg>
#include <cstdio>
#include <module.h>
#include <core.h>
#include <signal_path/source.h>
#include <imgui.h>
#include <gui/smgui.h>
#include <gui/tuner.h>
#include "../soapy/RxQueue.hpp"
#include "routes.hpp"
#include "../common/RfAuto.hpp"
#include "CoreFft.hpp"
extern "C" {
#include "../windows/sdr_session.h"
}
namespace sigpath { SDRPP_EXPORT SourceManager sourceManager; }
using Clock=std::chrono::steady_clock;
static std::filesystem::path root;
SDRPP_MOD_INFO {"uis8910_source","UIS8910 native USB RX","UIS8910DM",1,0,0,1};

class UIS8910Source final:public ModuleManager::Instance {
    struct Config {uint32_t band=5,frequency=881500000,gain=40,bw=0;bool automatic=true,fftPacing=true;std::string port="COM9";};
    Config requested;
    std::atomic<uint64_t> revision{1};
    uint64_t sessionRevision=0;
    std::atomic<bool> cancel{true},finished{true};
    bool running=false,enabled=true,tuneAllowed=true;
    std::thread captureThread,decodeThread;
    std::mutex mutex;
    std::condition_variable ready;
    Clock::time_point changedAt=Clock::now();
    uint32_t sessionFrequency=0,appliedFrequency=0,sessionBand=0,appliedBand=0;
    uint32_t sessionGain=0,appliedGain=0,sessionBw=0,appliedBw=0;
    uint64_t appliedRevision=0;
    RxQueue queue;
    dsp::stream<dsp::complex_t> stream;
    SourceManager::SourceHandler handler{};
    uint32_t error=0;
    uint64_t pairs=0,totalHostBytes=0,totalDropped=0,totalDrain=0,retuneDiscardedPairs=0;
    uint64_t totalRecoveries=0,totalGaps=0,sessions=0;
    uint32_t lastEpoch=0,lastDrained=0;
    char com[32]="COM9";
    std::string message="Stopped";
    Clock::time_point lastReport{};
    FftPacer fftPacer;

    void updateFftPacing(bool stopping=false) {
        // Server mode bypasses IQFrontEnd; it is deliberately not initialized.
        if(core::args["server"].b())return;
        if(!fftPacer.core.object && !fftPacer.core.bind(GetModuleHandleW(L"sdrpp_core.dll")))return;
        int size=65536;double userRate=20;
        core::configManager.acquire();
        try {
            size=core::configManager.conf.value("fftSize",65536);
            userRate=core::configManager.conf.value("fftRate",20.0);
        }catch(...){core::configManager.release();if(stopping)fftPacer.restore();return;}
        core::configManager.release();
        if(stopping){fftPacer.restore(userRate);return;}
        Config c;{std::lock_guard<std::mutex> lock(mutex);c=requested;}
        fftPacer.update(running && !finished && c.fftPacing && c.bw>=2,size,userRate);
    }

    static const Route *route(uint32_t band) {
        for(const auto &r:routes)if(r.band==band)return &r;
        return nullptr;
    }
    static bool valid(const Config &c) {
        const auto r=route(c.band);
        return r && c.frequency>=r->low && c.frequency<=r->high && c.frequency%100==0 &&
          c.gain<=124 && c.bw<=5 && c.port.size()>3 && c.port.substr(0,3)=="COM" &&
          c.port.find_first_not_of("0123456789",3)==std::string::npos;
    }
    static int stopRequested(void *ctx) {
        auto s=static_cast<UIS8910Source *>(ctx);
        return s->cancel.load() || s->revision.load()!=s->sessionRevision;
    }
    static int consume(const void *bytes,uint32_t length,void *ctx) {
        auto s=static_cast<UIS8910Source *>(ctx);
        if(stopRequested(ctx))return 1;
        std::lock_guard<std::mutex> lock(s->mutex);
        s->appliedFrequency=s->sessionFrequency;
        s->appliedBand=s->sessionBand;
        s->appliedGain=s->sessionGain;s->appliedBw=s->sessionBw;
        s->appliedRevision=s->sessionRevision;
        auto dropped=s->queue.dropped;
        s->queue.push(bytes,length);
        s->totalHostBytes+=length;s->totalDropped+=s->queue.dropped-dropped;
        s->ready.notify_all();return 0;
    }
    void capture() {
        uint32_t transientErrors=0;
        while(!cancel) {
            Config c;
            {std::unique_lock<std::mutex> lock(mutex);
                // UI callbacks only publish requests. Wait for a valid center
                // and120ms quiet before another costly STOP/config/start cycle.
                // Never restart an old route while an invalid center is pending.
                for(;;) {
                    if(cancel)break;
                    if(!tuneAllowed || !valid(requested)) {
                        message="Waiting for a valid RF center; capture drained";
                        ready.wait(lock,[this]{return cancel || (tuneAllowed && valid(requested));});
                        continue;
                    }
                    auto due=changedAt+std::chrono::milliseconds(120);
                    if(Clock::now()>=due)break;
                    ready.wait_until(lock,due);
                }
                if(cancel)break;
                c=requested;sessionRevision=revision.load();retuneDiscardedPairs+=queue.pairs();queue.reset();
                sessionFrequency=c.frequency;
                sessionBand=c.band;
                sessionGain=c.gain;sessionBw=c.bw;
                message="Configuring / receiving";lastDrained=0;
            }
            sdr_usb *usb=nullptr;sdr_control *control=nullptr;sdr_session_result result{};
            wchar_t path[2048],port[32];uint32_t e=0;
            if(!valid(c))e=ERROR_INVALID_PARAMETER;
            if(!e)e=sdr_usb_find(path,2048);
            if(!e)e=sdr_usb_open(&usb,path,{65536,32,0});
            if(!e && !MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,c.port.c_str(),-1,port,32))e=ERROR_INVALID_PARAMETER;
            if(!e)e=sdr_control_open(&control,port,1000);
            if(!e)e=sdr_session_receive_bw(usb,control,c.band,c.frequency,c.gain,c.bw,0,consume,this,stopRequested,this,&result);
            sdr_control_close(control);sdr_usb_close(usb);
            {std::lock_guard<std::mutex> lock(mutex);
                error=e;lastEpoch=result.epoch;lastDrained=result.device_drained;
                totalDrain+=result.discarded_after_consumer_stop;
                totalRecoveries+=result.recovery[4];
                totalGaps+=uint64_t(result.recovery[8])+(uint64_t(result.recovery[9])<<32);
                ++sessions;
                if(!e) transientErrors=0;
                if(e)message="Receive error "+std::to_string(e)+"; stop, check COM / center frequency";
            }
            if(e && !cancel && (e==ERROR_OPERATION_ABORTED || revision.load()!=sessionRevision) &&
                transientErrors++ < 3u) {
                std::lock_guard<std::mutex> lock(mutex);
                message="Retune recovery "+std::to_string(transientErrors)+"/3; reopening capture";
                changedAt=Clock::now();
                ready.notify_all();
                continue;
            }
            if(e || cancel)break;
            // New requests made during drain coalesce into the next configuration.
            // Do not exit on a momentary revision equality: a UI request could
            // arrive immediately after that check and lose its worker.
        }
        finished=true;ready.notify_all();
    }
    void decode() {
        static_assert(sizeof(dsp::complex_t)==2*sizeof(float),"SDR++ complex ABI");
        while(!cancel) {
            size_t count;
            {std::unique_lock<std::mutex> lock(mutex);
                ready.wait(lock,[this]{return cancel || finished || queue.pairs();});
                if(cancel || (!queue.pairs() && finished))break;
                count=queue.read(stream.writeBuf,8192,true);pairs+=count;
            }
            if(!stream.swap(int(count)))break;
        }
    }
    void start() {
        if(running)return;
        {std::lock_guard<std::mutex> lock(mutex);
            if(!tuneAllowed || !valid(requested)){message="Choose a valid center frequency and COM port before Play";return;}
            queue.reset();pairs=totalHostBytes=totalDropped=totalDrain=totalRecoveries=totalGaps=sessions=0;
            retuneDiscardedPairs=0;
            error=lastEpoch=lastDrained=0;
        }
        cancel=false;finished=false;stream.clearWriteStop();running=true;
        updateFftPacing();
        decodeThread=std::thread(&UIS8910Source::decode,this);
        captureThread=std::thread(&UIS8910Source::capture,this);
    }
    void stop() {
        if(!running){updateFftPacing(true);return;}
        cancel=true;stream.stopWriter();ready.notify_all();
        if(captureThread.joinable())captureThread.join();
        if(decodeThread.joinable())decodeThread.join();
        stream.clearWriteStop();running=false;
        updateFftPacing(true);
        {std::lock_guard<std::mutex> lock(mutex);if(!error)message="Stopped / drained";}
        report();save();
    }
    void report() {
        std::lock_guard<std::mutex> lock(mutex);
        json j={{"running",running},{"finished",finished.load()},{"message",message},{"error",error},
            {"decoded_pairs",pairs},{"host_bytes",totalHostBytes},{"queue_dropped_bytes",totalDropped},
            {"queued_pairs",queue.pairs()},{"drain_discarded_bytes",totalDrain},{"device_full_stops",totalRecoveries},
            {"retune_discarded_pairs",retuneDiscardedPairs},
            {"observed_gap_ms",totalGaps},{"completed_sessions",sessions},{"epoch",lastEpoch},
            {"device_drained",lastDrained},{"band",requested.band},{"frequency_hz",requested.frequency},
            {"applied_frequency_hz",appliedFrequency},{"tune_allowed",tuneAllowed},
            {"applied_gain_index",appliedGain},{"applied_bandwidth_index",appliedBw},
            {"applied_revision",appliedRevision},
            {"auto_route",requested.automatic},{"applied_band",appliedBand},
            {"requested_revision",revision.load()},{"session_revision",sessionRevision},
            {"retune_quiet_ms",120},
            {"fft_pacing_enabled",requested.fftPacing},{"fft_pacing_active",fftPacer.active},
            {"fft_rate_setting",fftPacer.rate},{"fft_pacing_server_bypassed",core::args["server"].b()},
            {"gain_index",requested.gain},{"bandwidth_index",requested.bw},{"port",requested.port},
            {"absolute_timestamps",false},{"configuration_scope","requested; may be draining/reconfiguring"}};
        std::ofstream out(root/"uis8910_source_status.json");out<<j.dump(2)<<"\n";
    }
    void save() {
        std::lock_guard<std::mutex> lock(mutex);
        std::ofstream out(root/"uis8910_source_config.json");
        out<<json({{"port",requested.port},{"band",requested.band},{"frequency_hz",requested.frequency},
            {"auto_route",requested.automatic},
            {"fft_pacing",requested.fftPacing},
            {"gain_index",requested.gain},{"bandwidth_index",requested.bw}}).dump(2)<<"\n";
    }
    static void select(void *ctx) {
        auto s=static_cast<UIS8910Source *>(ctx);core::setInputSampleRate(double(sdr_nominal_sample_rate(s->requested.bw)));
    }
    static void tune(double hz,void *ctx) {
        auto s=static_cast<UIS8910Source *>(ctx);
        bool invalid=false;
        {
            std::lock_guard<std::mutex> lock(s->mutex);
            uint32_t f=0,band=s->requested.band;
            invalid=!std::isfinite(hz) || hz<0 || hz>4294967200.0;
            if(!invalid) {
                f=uint32_t(std::round(hz/100)*100);
                if(s->requested.automatic)
                    band=uis8910::autoRoute(routes,f,band,[](uint32_t){return true;});
                const auto r=route(band);
                invalid=!r || hz<r->low || hz>r->high;
            }
            bool changed=s->tuneAllowed!=!invalid;
            s->tuneAllowed=!invalid;
            if(!invalid) {
                if(s->requested.band!=band){s->requested.band=band;changed=true;}
                if(s->requested.frequency!=f){s->requested.frequency=f;changed=true;}
            }
            if(changed){++s->revision;s->changedAt=Clock::now();}
            if(invalid)s->message="Out of RF software range; draining, waiting for valid center";
        }
        s->ready.notify_all();
    }
    static void menu(void *ctx) {static_cast<UIS8910Source *>(ctx)->draw();}
    static void text(const char *format,...) {
        char buffer[512];va_list args;va_start(args,format);
        vsnprintf(buffer,sizeof(buffer),format,args);va_end(args);SmGui::Text(buffer);
    }
    void draw() {
        updateFftPacing();
        bool changed=false;
        if(!running && SmGui::InputText("Control COM",com,sizeof(com))) {
            std::lock_guard<std::mutex> lock(mutex);requested.port=com;changed=true;
        }
        if(running)text("Control: %s",com);
        Config c;{std::lock_guard<std::mutex> lock(mutex);c=requested;}
        int bw=int(c.bw);
        // Change sample rate while stopped so SDR++ can rebuild its DSP safely.
        if(!running && SmGui::Combo("Receive mode",&bw,"BW0: 1.92 Msps\0BW1: 3.84 Msps\0BW2: 7.68 Msps (gaps allowed)\0BW3: 15.36 Msps (gaps allowed)\0BW4: 30.72 Msps (gaps allowed)\0BW5: 30.72 Msps (gaps; filter unverified)\0")) {
            {std::lock_guard<std::mutex> lock(mutex);requested.bw=uint32_t(bw);changed=true;++revision;changedAt=Clock::now();}
            core::setInputSampleRate(double(sdr_nominal_sample_rate(uint32_t(bw))));
        }
        int gain=int(c.gain);
        if(SmGui::SliderInt("Gain index",&gain,0,124)) {
            std::lock_guard<std::mutex> lock(mutex);requested.gain=uint32_t(gain);changed=true;++revision;changedAt=Clock::now();
        }
        bool pacing=c.fftPacing;
        if(SmGui::Checkbox("Wideband FFT pacing",&pacing)) {
            {std::lock_guard<std::mutex> lock(mutex);requested.fftPacing=pacing;changed=true;}
            updateFftPacing();
        }
        if(fftPacer.active)SmGui::Text("FFT uses more received windows; source gaps remain");
        if(changed){ready.notify_all();save();report();}
        {std::lock_guard<std::mutex> lock(mutex);c=requested;}
        if(SmGui::Button("Use configured RF center")) {
            if(core::args["server"].b())sigpath::sourceManager.tune(double(c.frequency));
            else tuner::tune(tuner::TUNER_MODE_IQ_ONLY,"",double(c.frequency));
        }
        const auto r=route(c.band);
        text("RF path: Auto (internal route B%u)",c.band);
        if(r)text("Software range: %.3f - %.3f MHz",r->low/1e6,r->high/1e6);
        text("Requested RF: %.6f MHz",c.frequency/1e6);
        SmGui::Text("12-bit values; float IQ; gain is not calibrated dB");
        {std::lock_guard<std::mutex> lock(mutex);
            text("%s",message.c_str());
            text("Decoded: %llu pairs",static_cast<unsigned long long>(pairs));
            text("Queue drops: %llu bytes",static_cast<unsigned long long>(totalDropped));
            text("Completed-session gaps: %llu ms",static_cast<unsigned long long>(totalGaps));
        }
        if(Clock::now()-lastReport>std::chrono::seconds(1)){report();lastReport=Clock::now();}
    }
public:
    explicit UIS8910Source(const std::string &) {
        try {
            std::ifstream in(root/"uis8910_source_config.json");json j;if(in) {
                in>>j;Config c;c.port=j.value("port",c.port);c.band=j.value("band",c.band);
                c.frequency=j.value("frequency_hz",c.frequency);c.gain=j.value("gain_index",c.gain);
                c.bw=j.value("bandwidth_index",c.bw);
                // The SDR++ user surface is frequency-only.  Migrate old
                // saved manual-route configs to the shared Auto policy.
                c.automatic=true;
                c.fftPacing=j.value("fft_pacing",true);
                if(c.automatic) {
                    auto band=uis8910::autoRoute(routes,c.frequency,c.band,[](uint32_t){return true;});
                    if(band)c.band=band;
                    else c=Config{};
                }
                if(valid(c))requested=c;
            }
        }catch(const std::exception &){message="Invalid saved config; using defaults";}
        strcpy_s(com,requested.port.c_str());
        handler.stream=&stream;handler.ctx=this;handler.menuHandler=menu;handler.selectHandler=select;
        handler.deselectHandler=[](void *p){static_cast<UIS8910Source *>(p)->stop();};
        handler.startHandler=[](void *p){static_cast<UIS8910Source *>(p)->start();};
        handler.stopHandler=[](void *p){static_cast<UIS8910Source *>(p)->stop();};handler.tuneHandler=tune;
        sigpath::sourceManager.registerSource("UIS8910",&handler);
    }
    ~UIS8910Source()override {stop();sigpath::sourceManager.unregisterSource("UIS8910");save();}
    void postInit()override{}
    void enable()override{enabled=true;}
    void disable()override{stop();enabled=false;}
    bool isEnabled()override{return enabled;}
};
MOD_EXPORT void _INIT_() {
    HMODULE module=nullptr;wchar_t path[32768];
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&_INIT_),&module);
    GetModuleFileNameW(module,path,32768);root=std::filesystem::path(path).parent_path().parent_path();
}
MOD_EXPORT ModuleManager::Instance *_CREATE_INSTANCE_(std::string name){return new UIS8910Source(name);}
MOD_EXPORT void _DELETE_INSTANCE_(ModuleManager::Instance *p){delete p;}
MOD_EXPORT void _END_(){}
