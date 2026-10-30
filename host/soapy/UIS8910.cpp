#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <SoapySDR/Device.hpp>
#include <SoapySDR/Registry.hpp>
#include <SoapySDR/Formats.hpp>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <cmath>
#include "RxQueue.hpp"
#include "routes.hpp"
#include "../common/RfAuto.hpp"
extern "C" {
#include "../windows/sdr_session.h"
}

class UIS8910 final:public SoapySDR::Device {
    std::string port,format="CF32";
    uint32_t band=5,frequency=881500000,gain=40,bw=0;
    bool configured=false,automatic=true;
    std::atomic<bool> active{false};
    std::atomic<bool> cancel{false},done{true};
    std::thread thread;
    std::mutex apiLock;
    mutable std::mutex queueLock;
    std::condition_variable changed;
    RxQueue queue;
    uint32_t error=0;
    sdr_session_result result{};
    const Route &route(uint32_t selected) const {
        for(const auto &r:routes)if(r.band==selected)return r;
        throw std::runtime_error("Unknown software RF route");
    }
    static void rxOnly(int direction,size_t channel) {
        if(direction!=SOAPY_SDR_RX || channel)throw std::runtime_error("Single RX channel only");
    }
    void check(SoapySDR::Stream *s) const {
        if(!configured || s!=reinterpret_cast<const SoapySDR::Stream *>(this))throw std::runtime_error("Invalid stream");
    }
    static int stopped(void *p){return static_cast<UIS8910 *>(p)->cancel.load();}
    static int consume(const void *p,uint32_t n,void *context) {
        auto self=static_cast<UIS8910 *>(context);
        // STOP/drain bytes belong to the native session's separate discard
        // counter. Do not fill an unread queue during synchronous teardown.
        if(self->cancel.load())return 1;
        std::lock_guard<std::mutex> lock(self->queueLock);
        self->queue.push(p,n);self->changed.notify_all();return 0;
    }
    void worker() {
        sdr_usb *usb=nullptr;sdr_control *control=nullptr;
        wchar_t path[2048],com[40];uint32_t e=sdr_usb_find(path,2048);
        if(!e)e=sdr_usb_open(&usb,path,{65536,32,0});
        if(!e && !MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,port.c_str(),-1,com,40))e=ERROR_INVALID_PARAMETER;
        if(!e)e=sdr_control_open(&control,com,1000);
        uint32_t selected=band;
        if(!e && automatic) {
            char info[SDR_CONTROL_MAX_PAYLOAD];uint32_t bytes=sizeof(info);
            e=sdr_control_request(control,1,nullptr,0,info,&bytes);
            if(!e)e=sdr_session_auto_route(info,bytes,frequency,band,bw,1,&selected);
        }
        if(!e)e=sdr_session_receive_bw(usb,control,selected,frequency,gain,bw,0,consume,this,stopped,this,&result);
        sdr_control_close(control);sdr_usb_close(usb);
        {std::lock_guard<std::mutex> lock(queueLock);error=e;done=true;}
        changed.notify_all();
    }
    int start() {
        if(active)return 0;
        {std::lock_guard<std::mutex> lock(queueLock);queue.reset();result={};error=0;done=false;cancel=false;}
        active=true;thread=std::thread(&UIS8910::worker,this);
        std::unique_lock<std::mutex> lock(queueLock);
        bool ready=changed.wait_for(lock,std::chrono::seconds(10),[this]{return queue.pairs() || done.load();});
        if(ready && queue.pairs())return 0;
        lock.unlock();stop();return SOAPY_SDR_STREAM_ERROR;
    }
    int stop() {
        if(!active)return 0;
        cancel=true;if(thread.joinable())thread.join();active=false;
        return error?SOAPY_SDR_STREAM_ERROR:0;
    }
    void change(const std::function<void()> &fn) {
        std::lock_guard<std::mutex> lock(apiLock);bool restart=active;
        if(restart && stop())throw std::runtime_error("Previous capture failed to drain; no reconfiguration");
        fn();
        if(restart && start())throw std::runtime_error("Reconfigured capture did not start");
    }
public:
    explicit UIS8910(const SoapySDR::Kwargs &args) {
        auto it=args.find("port");if(it==args.end())throw std::runtime_error("Explicit port=COMn is required");port=it->second;
        if(port.size()<4 || port.substr(0,3)!="COM" || port.find_first_not_of("0123456789",3)!=std::string::npos)
            throw std::runtime_error("Expected port=COMn");
    }
    ~UIS8910()override{stop();}
    std::string getDriverKey()const override{return "uis8910";}
    std::string getHardwareKey()const override{return "UIS8910 raw RX";}
    SoapySDR::Kwargs getHardwareInfo()const override {
        return {{"port",port},{"precision","signed12 in16+16"},{"range_scope","software envelopes; physical boundaries unknown"},
            {"gain_units","index via gain_index setting; dB calibration unknown"},{"continuity","loss/recovery accepted; no absolute timestamps"},
            {"bandwidth_scope","set bw_mode to distinguish BW4/BW5 at the same sample rate; independent filter-width control unavailable"}};
    }
    size_t getNumChannels(const int d)const override{return d==SOAPY_SDR_RX?1:0;}
    bool getFullDuplex(const int,size_t)const override{return false;}
    std::vector<std::string> getStreamFormats(int d,size_t c)const override{rxOnly(d,c);return {"CF32","CS16"};}
    std::string getNativeStreamFormat(int d,size_t c,double &fullScale)const override{rxOnly(d,c);fullScale=2048;return "CS16";}
    SoapySDR::Stream *setupStream(int d,const std::string &f,const std::vector<size_t> &channels,const SoapySDR::Kwargs &)override {
        rxOnly(d,channels.empty()?0:channels[0]);if(channels.size()>1 || (f!="CF32" && f!="CS16"))throw std::runtime_error("Expected CF32/CS16, RX0");
        std::lock_guard<std::mutex> lock(apiLock);if(configured)throw std::runtime_error("Only one stream supported");
        format=f;configured=true;return reinterpret_cast<SoapySDR::Stream *>(this);
    }
    void closeStream(SoapySDR::Stream *s)override{std::lock_guard<std::mutex> lock(apiLock);check(s);stop();configured=false;}
    size_t getStreamMTU(SoapySDR::Stream *s)const override{check(s);return 8192;}
    int activateStream(SoapySDR::Stream *s,int flags,long long,size_t n)override {
        std::lock_guard<std::mutex> lock(apiLock);check(s);if(flags || n)return SOAPY_SDR_NOT_SUPPORTED;return start();
    }
    int deactivateStream(SoapySDR::Stream *s,int flags,long long)override {
        std::lock_guard<std::mutex> lock(apiLock);check(s);if(flags)return SOAPY_SDR_NOT_SUPPORTED;return stop();
    }
    int readStream(SoapySDR::Stream *s,void *const *buffers,size_t n,int &flags,long long &timeNs,long timeoutUs)override {
        check(s);flags=0;timeNs=0;if(!buffers || !buffers[0] || !n)return SOAPY_SDR_STREAM_ERROR;
        std::unique_lock<std::mutex> lock(queueLock);
        if(!active) {
            changed.wait_for(lock,std::chrono::microseconds(std::max(0L,timeoutUs)));
            return SOAPY_SDR_TIMEOUT;
        }
        changed.wait_for(lock,std::chrono::microseconds(std::max(0L,timeoutUs)),[this]{return queue.pairs() || queue.overflow || (active && done.load());});
        if(queue.overflow){queue.overflow=false;return SOAPY_SDR_OVERFLOW;}
        if(queue.pairs())return int(queue.read(buffers[0],std::min(n,size_t(8192)),format=="CF32"));
        return active && done?SOAPY_SDR_STREAM_ERROR:SOAPY_SDR_TIMEOUT;
    }
    std::vector<std::string> listAntennas(int d,size_t c)const override {
        rxOnly(d,c);return {"Auto"};
    }
    std::string getAntenna(int d,size_t c)const override{rxOnly(d,c);return automatic?"Auto":"B"+std::to_string(band);}
    void setAntenna(int d,size_t c,const std::string &name)override {
        rxOnly(d,c);
        if(name=="Auto") {
            uint32_t b=uis8910::autoRoute(routes,frequency,band,[](uint32_t){return true;});
            if(!b)throw std::runtime_error("Current center outside Auto software envelopes");
            change([&]{automatic=true;band=b;});return;
        }
        if(name!="Auto")throw std::runtime_error("Manual RF channel selection is hidden; tune center frequency and Auto selects the route");
    }
    std::vector<std::string> listFrequencies(int d,size_t c)const override{rxOnly(d,c);return {"RF"};}
    double getFrequency(int d,size_t c)const override{rxOnly(d,c);return frequency;}
    double getFrequency(int d,size_t c,const std::string &)const override{return getFrequency(d,c);}
    void setFrequency(int d,size_t c,double f,const SoapySDR::Kwargs &)override {
        rxOnly(d,c);
        if(!std::isfinite(f) || f<=0 || f>4294967200.0 || std::round(f/100)*100!=f)throw std::runtime_error("Invalid frequency or100Hz request grid");
        uint32_t b=automatic?uis8910::autoRoute(routes,uint32_t(f),band,[](uint32_t){return true;}):band;
        if(!b || f<route(b).low || f>route(b).high)throw std::runtime_error("Outside selected software envelopes");
        change([&]{frequency=uint32_t(f);band=b;});
    }
    void setFrequency(int d,size_t c,const std::string &name,double f,const SoapySDR::Kwargs &args)override {
        if(name!="RF")throw std::runtime_error("Unknown frequency element");
        setFrequency(d,c,f,args);
    }
    SoapySDR::RangeList getFrequencyRange(int d,size_t c)const override{
        rxOnly(d,c);if(!automatic){const auto &r=route(band);return {{double(r.low),double(r.high),100}};}
        std::vector<std::pair<uint32_t,uint32_t>> spans;
        for(const auto &r:routes)if(uis8910::autoCandidate(r.band))spans.emplace_back(r.low,r.high);
        std::sort(spans.begin(),spans.end());SoapySDR::RangeList result;
        uint32_t low=0,high=0;
        for(const auto &s:spans){if(!high){low=s.first;high=s.second;}else if(s.first<=high){high=std::max(high,s.second);}else{result.emplace_back(low,high,100);low=s.first;high=s.second;}}
        if(high)result.emplace_back(low,high,100);
        return result;
    }
    SoapySDR::RangeList getFrequencyRange(int d,size_t c,const std::string &)const override{return getFrequencyRange(d,c);}
    double getSampleRate(int d,size_t c)const override{rxOnly(d,c);return double(sdr_nominal_sample_rate(bw));}
    std::vector<double> listSampleRates(int d,size_t c)const override{rxOnly(d,c);return {1920000,3840000,7680000,15360000,30720000};}
    SoapySDR::RangeList getSampleRateRange(int d,size_t c)const override{rxOnly(d,c);return {{1920000,1920000},{3840000,3840000},{7680000,7680000},{15360000,15360000},{30720000,30720000}};}
    void setSampleRate(int d,size_t c,double rate)override {
        rxOnly(d,c);uint32_t selected=0;
        while(selected<=4 && rate!=double(sdr_nominal_sample_rate(selected)))++selected;
        if(selected>4)throw std::runtime_error("Supported nominal rates:1.92/3.84/7.68/15.36/30.72Msps; wideband modes have capture gaps");
        change([&]{if(!(bw==5 && selected==4))bw=selected;});
    }
    double getBandwidth(int d,size_t c)const override{rxOnly(d,c);return 0;}
    SoapySDR::RangeList getBandwidthRange(int d,size_t c)const override{rxOnly(d,c);return {};}
    std::vector<double> listBandwidths(int d,size_t c)const override{rxOnly(d,c);return {};}
    void setBandwidth(int d,size_t c,double width)override {
        rxOnly(d,c);
        // Zero leaves the mode-selected filter unchanged. Measured response
        // brackets are not independently programmable filter settings.
        if(width!=0)throw std::runtime_error("Independent filter bandwidth is unavailable; use bw_mode and a supported nominal sample rate. Bandwidth0 leaves the current mode unchanged.");
    }
    void setGain(int d,size_t c,double value)override{rxOnly(d,c);if(value!=0)throw std::runtime_error("dB gain unknown; use gain_index setting");}
    double getGain(int d,size_t c)const override{rxOnly(d,c);return 0;}
    SoapySDR::Range getGainRange(int d,size_t c)const override{rxOnly(d,c);return {0,0};}
    SoapySDR::ArgInfoList getSettingInfo()const override {
        SoapySDR::ArgInfo gain;gain.key="gain_index";gain.name="Native gain index";gain.value="40";gain.type=SoapySDR::ArgInfo::INT;gain.range={0,124,1};
        gain.description="Not calibrated dB. RF routes use antenna selector; configuration stops/drains/restarts an active stream.";
        SoapySDR::ArgInfo mode;mode.key="bw_mode";mode.name="RX bandwidth mode";mode.value="0";mode.type=SoapySDR::ArgInfo::INT;mode.range={0,5,1};
        mode.description="Native BW0..BW5; BW4 and BW5 both use nominal30.72Msps. Effective passband depends on RF route and measurement conditions; firmware INFO and rate must match.";return {gain,mode};
    }
    void writeSetting(const std::string &key,const std::string &value)override {
        if(key=="bw_mode") {
            if(value.size()!=1 || value[0]<'0' || value[0]>'5')throw std::runtime_error("Expected bw_mode0..5");
            uint32_t mode=uint32_t(value[0]-'0');change([&]{bw=mode;});return;
        }
        if(key!="gain_index" || value.empty() || value.find_first_not_of("0123456789")!=std::string::npos)throw std::runtime_error("Expected gain_index0..124 or bw_mode0..5");
        unsigned long g=std::stoul(value);if(g>124)throw std::runtime_error("gain_index0..124");change([&]{gain=uint32_t(g);});
    }
    std::string readSetting(const std::string &key)const override {
        if(key=="gain_index")return std::to_string(gain);
        if(key=="bw_mode")return std::to_string(bw);
        if(key=="stats") {
            std::lock_guard<std::mutex> lock(queueLock);
            std::string ended=done?"true":"false";
            std::string rf=done?std::to_string(result.recovery[4]):"null";
            std::string gaps=done?std::to_string(uint64_t(result.recovery[8])+(uint64_t(result.recovery[9])<<32)):"null";
            return "{\"host_bytes\":"+std::to_string(queue.received)+",\"queue_dropped_bytes\":"+std::to_string(queue.dropped)+
                ",\"queued_pairs\":"+std::to_string(queue.pairs())+
                ",\"drain_discarded_bytes\":"+(done?std::to_string(result.discarded_after_consumer_stop):"null")+
                ",\"device_drained\":"+(done?std::to_string(result.device_drained):"null")+
                ",\"epoch\":"+(done?std::to_string(result.epoch):"null")+
                ",\"auto_route\":"+(automatic?"true":"false")+",\"band\":"+std::to_string(band)+
                ",\"applied_band\":"+(done?std::to_string(result.status[40]>>8):"null")+",\"frequency_hz\":"+std::to_string(frequency)+
                ",\"gain_index\":"+std::to_string(gain)+",\"bandwidth_index\":"+std::to_string(bw)+
                ",\"terminal\":"+ended+",\"native_error\":"+std::to_string(done?error:0)+
                ",\"device_full_stops\":"+rf+",\"observed_gap_ms\":"+gaps+",\"absolute_timestamps\":false}";
        }
        throw std::runtime_error("Unknown setting");
    }
};
static SoapySDR::KwargsList find(const SoapySDR::Kwargs &args) {
    wchar_t path[2048];if(sdr_usb_find(path,2048))return {};
    SoapySDR::Kwargs k{{"driver","uis8910"},{"label","UIS8910 SDR RX (explicit port required)"}};
    auto p=args.find("port");if(p!=args.end())k["port"]=p->second;return {k};
}
static SoapySDR::Device *make(const SoapySDR::Kwargs &args){return new UIS8910(args);}
static SoapySDR::Registry registration("uis8910",find,make,SOAPY_SDR_ABI_VERSION);
