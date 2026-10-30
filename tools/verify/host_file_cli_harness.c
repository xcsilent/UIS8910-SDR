#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include "../../host/windows/sdr_usb.h"
#include "../../host/windows/sdr_session.h"
static int controlled;
static uint32_t configured_bw;
static uint32_t capture_duration;
static volatile LONG produced,started;
static volatile LONG fake_stopped;
static BOOL WINAPI console_stop(DWORD);
uint32_t sdr_control_open(sdr_control **s,const wchar_t *port,uint32_t timeout)
{ assert(!wcscmp(port,L"COM99") && timeout);controlled=1;*s=(sdr_control *)1;return 0; }
void sdr_control_close(sdr_control *s) { (void)s; }
uint32_t sdr_control_request(sdr_control *c,uint32_t op,const void *p,uint32_t n,void *out,uint32_t *bytes)
{
    (void)c;(void)p;assert(op==1 && !n);
    const char *info="{\"firmware\":\"uis8910-sdr-bw0-usb-v1\",\"raw_usb\":true,\"raw_usb_abi\":1,\"bw0_usb\":true,\"bw0_status_operation\":44,\"bw0_start_operation\":45,\"bw0_stop_operation\":46,\"bw0_config_operation\":47,\"bw0_recovery_status_operation\":48,\"bw0_rf_profiles\":[5]}";
    char text[1024];strcpy(text,info);
    strcpy(text+strlen(text)-1,",\"bw0_bandwidth_indices\":[0,1,2],\"bw0_config_abi\":2}");
    strcpy(text+strlen(text)-1,",\"bw0_until_stop\":true,\"bw0_keepalive_operation\":49,\"bw0_lease_timeout_ms\":5000}");
    assert(*bytes>=strlen(text));*bytes=(uint32_t)strlen(text);memcpy(out,text,*bytes);return 0;
}
uint32_t sdr_control_configure(sdr_control *c,uint32_t b,uint32_t f,uint32_t g)
{ (void)c;assert(b==5 && f==881500000 && g==40);return 0; }
uint32_t sdr_control_configure_bw(sdr_control *c,uint32_t b,uint32_t f,uint32_t g,uint32_t bw)
{ configured_bw=bw;return sdr_control_configure(c,b,f,g); }
uint32_t sdr_control_start(sdr_control *c,uint32_t duration,uint32_t *epoch)
{ (void)c;capture_duration=duration;*epoch=7;InterlockedExchange(&started,1);return 0; }
uint32_t sdr_control_stop(sdr_control *c) { (void)c;InterlockedExchange(&fake_stopped,1);return 0; }
uint32_t sdr_control_keepalive(sdr_control *c) { (void)c;return 0; }
uint32_t sdr_control_status(sdr_control *c,uint32_t w[48])
{
    (void)c;memset(w,0,192);w[40]=(5<<8)|(configured_bw<<4);w[45]=40;w[47]=881500000;w[9]=1920000u<<configured_bw;
    w[0]=0x31574353;w[1]=1;w[8]=2;w[10]=4;w[11]=12;w[46]=produced?capture_duration:0;
    w[30]=produced?1:0;w[32]=produced?30:0;
    w[5]=started?7:0;w[3]=started?((capture_duration?produced:fake_stopped)?4:3):0;w[37]=w[3]==4;w[22]=produced?1024:0;return 0;
}
uint32_t sdr_control_recovery(sdr_control *c,uint32_t w[24])
{ (void)c;memset(w,0,96);w[0]=0x31524353;w[1]=1;w[2]=started?7:0;return 0; }
uint32_t sdr_usb_find(wchar_t *path,uint32_t characters)
{ assert(characters>4);wcscpy(path,L"fake");return 0; }
uint32_t sdr_usb_open(sdr_usb **s,const wchar_t *path,struct sdr_usb_options options)
{ (void)path;(void)options;*s=(sdr_usb *)1;return 0; }
void sdr_usb_close(sdr_usb *s) { assert(s==(sdr_usb *)1); }
uint32_t sdr_usb_receive_controlled(sdr_usb *s,uint32_t duration,sdr_usb_consumer consumer,
    void *context,struct sdr_usb_stats *stats,sdr_usb_ready ready,void *ready_context,
    sdr_usb_stop_requested stop,void *stop_context)
{
    (void)s;(void)duration;(void)stop;(void)stop_context;
    unsigned char data[512];
    if(ready) ready(ready_context);
    ULONGLONG deadline=GetTickCount64()+3000;
    if(controlled) while(!InterlockedCompareExchange(&started,0,0)) { assert(GetTickCount64()<deadline);Sleep(1); }
    for(unsigned i=0;i<2;++i) {
        for(unsigned j=0;j<512;++j) data[j]=(unsigned char)(i+j);
        stats->bytes+=512;++stats->completions;
        if(consumer && consumer(data,512,context)) break;
    }
    InterlockedExchange(&produced,1);
    if(controlled && !capture_duration) console_stop(CTRL_BREAK_EVENT);
    if(controlled) while(!stop(stop_context)) { assert(GetTickCount64()<deadline);Sleep(1); }
    stats->pipe_id=0x86;return 0;
}
#include "../../host/windows/sdr_receive.c"
