#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <vector>
#include <stdexcept>

/* Call under the adapter's queue mutex. Raw byte fragments are joined before
 * publishing whole complex pairs. Overload drops complete pairs only. */
class RxQueue {
    std::vector<unsigned char> bytes;
    size_t head=0,count=0,tailBytes=0;
    unsigned char tail[4]={};
    void append(const unsigned char *p,size_t n) {
        if(n>bytes.size()-count) {dropped+=n;overflow=true;return;}
        size_t at=(head+count)%bytes.size(),first=std::min(n,bytes.size()-at);
        std::memcpy(bytes.data()+at,p,first);
        if(n>first) std::memcpy(bytes.data(),p+first,n-first);
        count+=n;
    }
public:
    uint64_t received=0,dropped=0;
    bool overflow=false;
    explicit RxQueue(size_t capacity=4u*1024u*1024u):bytes(capacity) {
        if(!capacity || capacity%4) throw std::invalid_argument("queue capacity must be whole complex pairs");
    }
    void reset(){head=count=tailBytes=0;received=dropped=0;overflow=false;}
    size_t pairs() const{return count/4;}
    size_t partialBytes() const{return tailBytes;}
    void push(const void *input,size_t n) {
        auto p=static_cast<const unsigned char *>(input);received+=n;
        if(tailBytes) {
            size_t k=std::min(4-tailBytes,n);std::memcpy(tail+tailBytes,p,k);
            p+=k;n-=k;tailBytes+=k;
            if(tailBytes==4){append(tail,4);tailBytes=0;}
        }
        size_t complete=n&~size_t(3);if(complete)append(p,complete);
        p+=complete;n-=complete;
        if(n){std::memcpy(tail,p,n);tailBytes=n;}
    }
    /* Full-scale2048 preserves the signed12 values in CS16. Conjugation is
     * performed after widening, so raw-2048 becomes+2048 without overflow. */
    size_t read(void *output,size_t requested,bool floating) {
        size_t n=std::min(requested,pairs());
        auto f=static_cast<float *>(output);auto s=static_cast<int16_t *>(output);
        for(size_t i=0;i<n;++i) {
            unsigned char p[4];for(unsigned j=0;j<4;++j)p[j]=bytes[(head+4*i+j)%bytes.size()];
            int a=(int(p[0])|(int(p[1])<<8))>>4,b=(int(p[2])|(int(p[3])<<8))>>4;
            a=a>=2048?a-4096:a;b=b>=2048?b-4096:b;
            if(floating){f[2*i]=a/2048.0f;f[2*i+1]=-b/2048.0f;}
            else{s[2*i]=int16_t(a);s[2*i+1]=int16_t(-b);}
        }
        head=(head+4*n)%bytes.size();count-=4*n;return n;
    }
};
