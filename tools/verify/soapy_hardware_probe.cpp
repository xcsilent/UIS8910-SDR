#include <SoapySDR/Device.hpp>
#include <SoapySDR/Formats.hpp>
#include <chrono>
#include <complex>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <limits>

int main(int argc,char **argv) {
    if(argc<2)return 2;
    SoapySDR::Device *d=nullptr;SoapySDR::Stream *s=nullptr;
    try {
        if(std::string(argv[1])=="--capabilities" || std::string(argv[1])=="--capabilities-lowband") {
            d=SoapySDR::Device::make("driver=uis8910,port=COM999");
            auto require=[](bool condition){if(!condition)throw std::runtime_error("offline capability contract failed");};
            require(d->listAntennas(SOAPY_SDR_RX,0)==std::vector<std::string>({"Auto"}));
            require(d->getAntenna(SOAPY_SDR_RX,0)=="Auto");
            bool manualRejected=false;try{d->setAntenna(SOAPY_SDR_RX,0,"B5");}catch(const std::exception &){manualRejected=true;}
            require(manualRejected);
            d->setAntenna(SOAPY_SDR_RX,0,"Auto");
            if(std::string(argv[1])=="--capabilities-lowband") {
                for(double hz:{700000000.0,800000000.0,823999900.0}) {
                    d->setFrequency(SOAPY_SDR_RX,0,hz);require(d->getFrequency(SOAPY_SDR_RX,0)==hz);
                }
                bool rejected=false;try{d->setFrequency(SOAPY_SDR_RX,0,699999900.0);}catch(const std::exception &){rejected=true;}
                require(rejected);
            }
            for(double hz:{881500000.0,942500000.0,1842500000.0,2000000000.0,2600000000.0}) {
                d->setFrequency(SOAPY_SDR_RX,0,hz);require(d->getFrequency(SOAPY_SDR_RX,0)==hz);
            }
            bool gapRejected=false;try{d->setFrequency(SOAPY_SDR_RX,0,1090000000.0);}catch(const std::exception &){gapRejected=true;}
            require(gapRejected && d->getFrequencyRange(SOAPY_SDR_RX,0).size()==2);
            const auto rates=d->listSampleRates(SOAPY_SDR_RX,0);
            require(rates==std::vector<double>({1920000,3840000,7680000,15360000,30720000}));
            for(double rate:rates){d->setSampleRate(SOAPY_SDR_RX,0,rate);require(d->getSampleRate(SOAPY_SDR_RX,0)==rate);}
            require(d->readSetting("bw_mode")=="4");
            d->writeSetting("bw_mode","5");
            require(d->readSetting("bw_mode")=="5" && d->getSampleRate(SOAPY_SDR_RX,0)==30720000);
            d->setSampleRate(SOAPY_SDR_RX,0,30720000);
            require(d->readSetting("bw_mode")=="5");
            d->setSampleRate(SOAPY_SDR_RX,0,15360000);
            require(d->readSetting("bw_mode")=="3");
            d->writeSetting("bw_mode","4");
            for(const char *mode:{"6","7","05","-1",""}) {
                bool invalid=false;try{d->writeSetting("bw_mode",mode);}catch(const std::exception &){invalid=true;}
                require(invalid && d->readSetting("bw_mode")=="4");
            }
            require(d->getBandwidth(SOAPY_SDR_RX,0)==0 && d->getBandwidthRange(SOAPY_SDR_RX,0).empty());
            d->setBandwidth(SOAPY_SDR_RX,0,0);
            for(double width:{-1.0,1000000.0,1920000.0,std::numeric_limits<double>::quiet_NaN(),std::numeric_limits<double>::infinity()}) {
                bool rejected=false;try{d->setBandwidth(SOAPY_SDR_RX,0,width);}catch(const std::exception &){rejected=true;}
                require(rejected && d->getSampleRate(SOAPY_SDR_RX,0)==30720000);
            }
            bool rejected=false;try{d->setSampleRate(SOAPY_SDR_RX,0,61440000);}catch(const std::exception &){rejected=true;}
            require(rejected && d->getSampleRate(SOAPY_SDR_RX,0)==30720000);
            require(!d->getHardwareInfo().at("bandwidth_scope").empty());
            SoapySDR::Device::unmake(d);d=nullptr;
            std::cout<<"{\"status\":\"passed\",\"device_accessed\":false,\"scope\":\"Soapy API capability contract without activateStream or serial/USB open\",\"BW2_advertised\":true,\"independent_bandwidth_rejected\":true}\n";
            return 0;
        }
        d=SoapySDR::Device::make(std::string("driver=uis8910,port=")+argv[1]);
        bool highBoundary=argc>4 && std::string(argv[4])=="auto-high";
        bool lowerBoundary=argc>4 && std::string(argv[4])=="auto-b3-lower";
        bool automatic=highBoundary || lowerBoundary || (argc>4 && std::string(argv[4])=="auto");
        d->setAntenna(SOAPY_SDR_RX,0,"Auto");d->setFrequency(SOAPY_SDR_RX,0,lowerBoundary?1375000000:(highBoundary?2000000000:881500000));
        d->setSampleRate(SOAPY_SDR_RX,0,argc>3?std::stod(argv[3]):3840000);d->writeSetting("gain_index","40");
        const int requestedMode=argc>5?std::stoi(argv[5]):-1;
        if(requestedMode>=0) {
            d->writeSetting("bw_mode",std::to_string(requestedMode));
            if(d->readSetting("bw_mode")!=std::to_string(requestedMode))throw std::runtime_error("explicit BW mode not retained");
            // Applications may repeat their rate request after a mode setting.
            d->setSampleRate(SOAPY_SDR_RX,0,argc>3?std::stod(argv[3]):3840000);
            if(d->readSetting("bw_mode")!=std::to_string(requestedMode))throw std::runtime_error("sample rate overwrote explicit BW mode");
        }
        std::string format=argc>2?argv[2]:"CF32";
        s=d->setupStream(SOAPY_SDR_RX,format);
        std::vector<std::complex<float>> samples(8192);void *p=samples.data();
        int flags=0;long long timestamp=0;
        if(d->readStream(s,&p,8192,flags,timestamp,1000)!=SOAPY_SDR_TIMEOUT)throw std::runtime_error("inactive read did not time out");
        if(d->activateStream(s))throw std::runtime_error("activate failed");
        auto start=std::chrono::steady_clock::now();uint64_t pairs=0,overflows=0;bool retuned=false;
        while(std::chrono::steady_clock::now()-start<std::chrono::seconds(5)) {
            int n=d->readStream(s,&p,8192,flags,timestamp,250000);
            if(n==SOAPY_SDR_OVERFLOW){++overflows;continue;}
            if(n==SOAPY_SDR_TIMEOUT)continue;
            if(n<0)throw std::runtime_error("read error"+std::to_string(n));
            if(flags&SOAPY_SDR_HAS_TIME)throw std::runtime_error("fabricated timestamps");
            pairs+=n;
            if(!retuned && std::chrono::steady_clock::now()-start>std::chrono::seconds(2)) {
                std::cerr<<"before_retune "<<d->readSetting("stats")<<"\n";
                d->setFrequency(SOAPY_SDR_RX,0,lowerBoundary?1447000000:(highBoundary?1885000000:(automatic?2000000000:881600000)));retuned=true;
            }
        }
        if(d->deactivateStream(s))throw std::runtime_error("deactivate failed");
        if(requestedMode>=0 && d->readSetting("bw_mode")!=std::to_string(requestedMode))throw std::runtime_error("retune overwrote explicit BW mode");
        if(d->readStream(s,&p,8192,flags,timestamp,1000)!=SOAPY_SDR_TIMEOUT)throw std::runtime_error("inactive tail leaked");
        std::string stats=d->readSetting("stats");
        d->closeStream(s);s=nullptr;
        // Same device and a different numeric format/sample rate.
        s=d->setupStream(SOAPY_SDR_RX,format=="CF32"?"CS16":"CF32");
        d->setSampleRate(SOAPY_SDR_RX,0,1920000);d->writeSetting("gain_index","20");
        if(d->activateStream(s))throw std::runtime_error("repeat activate failed");
        int n=d->readStream(s,&p,8192,flags,timestamp,500000);if(n<=0)throw std::runtime_error("repeat read failed");
        if(d->deactivateStream(s))throw std::runtime_error("repeat drain failed");
        std::cout<<"{\"status\":\"passed\",\"format\":\""<<format<<"\",\"read_pairs\":"<<pairs<<",\"overflow_returns\":"<<overflows
          <<",\"active_retune\":"<<(retuned?"true":"false")<<",\"last_session\":"<<stats<<",\"repeat_session\":"<<d->readSetting("stats")<<"}\n";
        d->closeStream(s);s=nullptr;SoapySDR::Device::unmake(d);return 0;
    } catch(const std::exception &e) {
        std::cerr<<e.what()<<std::endl;
        if(d){if(s)d->closeStream(s);SoapySDR::Device::unmake(d);}return 1;
    }
}
