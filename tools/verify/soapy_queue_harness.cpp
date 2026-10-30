#include "../../host/soapy/RxQueue.hpp"
#include <cassert>
#include <iostream>
int main() {
    std::vector<unsigned char> wire;
    for(int a=-2048;a<2048;++a)for(int j=0;j<2;++j) {
        unsigned value=((unsigned(a)&4095)<<4)|15; // unused bits must not affect fields
        wire.push_back(value&255);wire.push_back((value>>8)&255);
    }
    RxQueue q(32768);
    size_t cursor=0;
    for(size_t length=1;cursor<wire.size();length=length%127+1) {
        size_t n=std::min(length,wire.size()-cursor);q.push(wire.data()+cursor,n);cursor+=n;
    }
    assert(q.pairs()==4096 && !q.partialBytes() && !q.dropped);
    int16_t ints[8192];assert(q.read(ints,4096,false)==4096);
    for(int i=0;i<4096;++i){assert(ints[2*i]==i-2048);assert(ints[2*i+1]==2048-i);}
    q.reset();q.push(wire.data(),wire.size());float f[8192];assert(q.read(f,4096,true)==4096);
    for(int i=0;i<4096;++i){assert(f[2*i]==(i-2048)/2048.0f);assert(f[2*i+1]==(2048-i)/2048.0f);}
    RxQueue small(16);small.push(wire.data(),16);small.push(wire.data()+16,1);small.push(wire.data()+17,3);
    assert(small.pairs()==4 && small.dropped==4 && small.overflow && !small.partialBytes());
    assert(small.read(ints,2,false)==2);small.push(wire.data()+20,8);
    assert(small.read(ints,10,false)==4);
    assert(ints[0]==-2046 && ints[2]==-2045 && ints[4]==-2043 && ints[6]==-2042);
    small.reset();small.push(wire.data(),3);assert(!small.pairs() && small.partialBytes()==3);
    small.push(wire.data()+3,1);assert(small.read(ints,1,false)==1 && ints[0]==-2048 && ints[1]==2048);
    std::cout<<"passed:4096signed12 values/unused lowbits, CF32/CS16 conjugation, byte fragmentation, whole-pair drop, wrap, partial-tail joining"<<std::endl;
}
