#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../../host/windows/sdr_session.h"
static volatile LONG started,stopped,keepalives;
static int mode,ready_called,consumer_calls;
static uint32_t configured_bw;
static uint32_t fake_elapsed;
static DWORD receive_thread;
uint32_t sdr_control_request(sdr_control *c,uint32_t op,const void *p,uint32_t n,void *out,uint32_t *bytes)
{
    (void)c;(void)p;assert(op==1 && !n);
    const char *info="{\"firmware\":\"uis8910-sdr-bw0-usb-v1\",\"raw_usb\":true,\"raw_usb_abi\":1,\"bw0_usb\":true,\"bw0_status_operation\":44,\"bw0_start_operation\":45,\"bw0_stop_operation\":46,\"bw0_config_operation\":47,\"bw0_recovery_status_operation\":48,\"bw0_rf_profiles\":[5]}";
    if(mode==4) info="{}";
    char text[512];strcpy(text,info);
    if(mode>=5 && mode!=6) strcpy(text+strlen(text)-1,",\"bw0_bandwidth_indices\":[0,1],\"bw0_config_abi\":2}");
    if(mode==15) strcpy(text+strlen(info)-1,",\"bw0_bandwidth_indices\":[0,1,2],\"bw0_config_abi\":2}");
    if(mode>=11 && mode!=12) strcpy(text+strlen(text)-1,",\"bw0_until_stop\":true,\"bw0_keepalive_operation\":49,\"bw0_lease_timeout_ms\":5000}");
    assert(*bytes>=strlen(text));*bytes=(uint32_t)strlen(text);memcpy(out,text,*bytes);return 0;
}
uint32_t sdr_control_configure(sdr_control *c,uint32_t b,uint32_t f,uint32_t g)
{ (void)c;assert(mode!=4);assert(b==5 && f==881500000 && g==40);return 0; }
uint32_t sdr_control_configure_bw(sdr_control *c,uint32_t b,uint32_t f,uint32_t g,uint32_t bw)
{ assert(mode!=6 && mode!=16);configured_bw=bw;return sdr_control_configure(c,b,f,g); }
uint32_t sdr_control_start(sdr_control *c,uint32_t duration,uint32_t *epoch)
{
    (void)c;assert(duration==(mode>=11?0u:mode>=9?5000u:100u));assert(ready_called);
    assert(GetCurrentThreadId()!=receive_thread);
    InterlockedExchange(&started,1);*epoch=mode==3?0:7;
    return mode==3?ERROR_TIMEOUT:0;
}
uint32_t sdr_control_stop(sdr_control *c)
{ (void)c;assert(GetCurrentThreadId()!=receive_thread);InterlockedExchange(&stopped,1);return 0; }
uint32_t sdr_control_keepalive(sdr_control *c)
{ (void)c;assert(GetCurrentThreadId()!=receive_thread);InterlockedIncrement(&keepalives);return mode==13?ERROR_TIMEOUT:0; }
uint32_t sdr_control_status(sdr_control *c,uint32_t w[48])
{
    (void)c;memset(w,0,192);w[40]=(5<<8)|(mode==7?0:configured_bw<<4);w[45]=40;w[47]=881500000;
    w[9]=mode==8?1920000:1920000u<<configured_bw;
    w[5]=started?7:0;w[3]=started?(stopped || mode==0 || mode==5 || mode==14?4:3):0;w[37]=w[3]==4;
    if((mode==9 || mode==10) && started) {
        fake_elapsed+=400;w[46]=fake_elapsed;w[22]=fake_elapsed*(7680u<<configured_bw);
        if(mode==10 && fake_elapsed==1600) w[22]=0;
        if(fake_elapsed>=5000) { w[3]=4;w[37]=1; }
    }
    return 0;
}
uint32_t sdr_control_recovery(sdr_control *c,uint32_t w[24])
{ (void)c;memset(w,0,96);w[2]=started?7:0;return 0; }
uint32_t sdr_usb_receive_controlled(sdr_usb *u,uint32_t d,sdr_usb_consumer consumer,void *ctx,
    struct sdr_usb_stats *stats,sdr_usb_ready ready,void *rctx,sdr_usb_stop_requested stop,void *sctx)
{
    (void)u;assert(d==0);memset(stats,0,sizeof(*stats));receive_thread=GetCurrentThreadId();
    if(mode==2) return stats->win32_error=ERROR_GEN_FAILURE;
    ready_called=1;ready(rctx);
    ULONGLONG deadline=GetTickCount64()+6000;
    while(!stop(sctx)) {
        if(mode==15 && started) { char bytes[4]={0};assert(!consumer(bytes,4,ctx));stats->bytes+=4; }
        if((mode==1 || mode==11) && started) { char bytes[4]={0};assert(!consumer(bytes,4,ctx));stats->bytes+=4; }
        assert(GetTickCount64()<deadline);Sleep(1);
    }
    return 0;
}
static int consume(const void *p,uint32_t n,void *ctx)
{ (void)p;(void)n;(void)ctx;++consumer_calls;return 1; }
int main(void)
{
    for(mode=0;mode<17;++mode) {
        started=stopped=keepalives=0;ready_called=consumer_calls=0;
        configured_bw=0;
        fake_elapsed=0;
        struct sdr_session_result r;
        struct sdr_session_telemetry t;
        uint32_t e=mode<5?sdr_session_receive((sdr_usb *)1,(sdr_control *)1,5,881500000,40,100,consume,NULL,NULL,NULL,&r):
            mode<9?sdr_session_receive_bw((sdr_usb *)1,(sdr_control *)1,5,881500000,40,1,100,consume,NULL,NULL,NULL,&r):
            sdr_session_receive_observed((sdr_usb *)1,(sdr_control *)1,5,881500000,40,mode>=15?2:1,mode>=11?0:5000,consume,NULL,NULL,NULL,&r,&t);
        /* A finite source can self-drain while its service lease stays held.
         * The public receive API must still STOP before returning success. */
        if(mode==0) { assert(!e && r.device_drained && stopped); }
        if(mode==1) { assert(!e && r.device_drained && stopped && consumer_calls==1); }
        if(mode==2) { assert(e==ERROR_GEN_FAILURE && !started && !stopped); }
        if(mode==3) { assert(e==ERROR_TIMEOUT && stopped && r.device_drained); }
        if(mode==4) { assert(e && !started && !stopped); }
        if(mode==5) { assert(!e && r.device_drained && stopped && configured_bw==1); }
        if(mode>=6 && mode<=8) { assert(e && !started && !stopped); }
        if(mode==11) { assert(!e && r.device_drained && stopped && consumer_calls==1); }
        if(mode==12) { assert(e==ERROR_NOT_SUPPORTED && !started && !stopped); }
        if(mode==13) { assert(e==ERROR_TIMEOUT && keepalives && stopped && r.device_drained); }
        if(mode==14) { assert(e==ERROR_OPERATION_ABORTED && keepalives && r.device_drained); }
        if(mode==15) { assert(!e && r.device_drained && stopped && consumer_calls==1 && configured_bw==2); }
        if(mode==16) { assert(e==ERROR_NOT_SUPPORTED && !started && !stopped); }
        if(mode==9 || mode==10) {
            assert(!e && r.device_drained && stopped && t.points>=3 && t.first_ms>=500 && t.last_ms<4750);
            if(mode==9) {
                assert(!t.counter_invalid && t.minimum_window_bytes_per_second==15360000.0);
                assert((t.last_bytes-t.first_bytes)*1000/(t.last_ms-t.first_ms)==15360000);
            } else assert(t.counter_invalid);
        }
    }
    puts("seventeen native session cases passed");return 0;
}
