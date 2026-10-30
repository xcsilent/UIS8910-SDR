#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned char inbound[32768],written[32768],expected[8192];
static DWORD inbound_bytes,inbound_at,written_bytes,expected_bytes;
static ULONGLONG clock_ms;
static unsigned empty_before_data,idle_yields;
static VOID WINAPI test_sleep(DWORD milliseconds)
{ assert(milliseconds==1);++idle_yields;clock_ms+=milliseconds; }
static BOOL WINAPI test_read(HANDLE file,LPVOID buffer,DWORD size,LPDWORD actual,LPOVERLAPPED ov)
{
    assert(file==(HANDLE)1 && !ov);
    if(empty_before_data) { --empty_before_data;*actual=0;return TRUE; }
    DWORD bytes=inbound_bytes-inbound_at;
    if(bytes>size) bytes=size;
    if(bytes>7) bytes=7;
    if(bytes) { memcpy(buffer,inbound+inbound_at,bytes);inbound_at+=bytes;clock_ms+=1; }
    else clock_ms+=500;
    *actual=bytes;return TRUE;
}
static BOOL WINAPI test_write(HANDLE file,LPCVOID buffer,DWORD size,LPDWORD actual,LPOVERLAPPED ov)
{
    assert(file==(HANDLE)1 && !ov);
    DWORD bytes=size<3?size:3;
    assert(written_bytes+bytes<=sizeof(written));
    memcpy(written+written_bytes,buffer,bytes);written_bytes+=bytes;
    clock_ms+=1;*actual=bytes;return TRUE;
}
static ULONGLONG WINAPI test_clock(void) { return clock_ms; }
#define ReadFile test_read
#define Sleep test_sleep
#define WriteFile test_write
#define GetTickCount64 test_clock
#include "../../host/windows/sdr_control.c"

static DWORD load(const char *path,unsigned char *out,DWORD capacity)
{
    FILE *file=fopen(path,"rb");assert(file);
    size_t bytes=fread(out,1,capacity,file);assert(!ferror(file) && feof(file));
    fclose(file);return (DWORD)bytes;
}
int main(int argc,char **argv)
{
    assert(argc==4);
    unsigned mode=(unsigned)strtoul(argv[1],NULL,10);
    if(mode==16)empty_before_data=3;
    inbound_bytes=load(argv[2],inbound,sizeof(inbound));
    expected_bytes=load(argv[3],expected,sizeof(expected));
    struct sdr_control control={0};control.file=(HANDLE)1;control.sequence=0x1234;control.timeout_ms=1000;
    unsigned char response[4096]={0};uint32_t size=sizeof(response),error,epoch=0,words48[48],words24[24];
    if(mode==2) error=sdr_control_configure(&control,5,881600000,20);
    else if(mode==13) error=sdr_control_configure_bw(&control,5,881600000,20,1);
    else if(mode==17) error=sdr_control_configure_bw(&control,5,881600000,20,2);
    else if(mode==3) { error=sdr_control_start(&control,1000,&epoch);assert(epoch==7); }
    else if(mode==14) { error=sdr_control_start(&control,0,&epoch);assert(epoch==7); }
    else if(mode==15) error=sdr_control_keepalive(&control);
    else if(mode==4) {
        error=sdr_control_status(&control,words48);
        assert(words48[0]==0x31574353u && words48[1]==1 && words48[22]==8000 && words48[47]==881600000);
    } else if(mode==5) {
        error=sdr_control_recovery(&control,words24);
        assert(words24[0]==0x31524353u && words24[1]==1 && words24[4]==2);
    } else if(mode==6) error=sdr_control_stop(&control);
    else if(mode==10) { size=1;error=sdr_control_request(&control,1,NULL,0,response,&size); }
    else if(mode==11 || mode==12) {
        error=sdr_control_request(&control,mode==11?2:43,NULL,0,response,&size);
        assert(error==ERROR_INVALID_PARAMETER && !written_bytes && !size);
        puts("passed: unsupported mutation rejected before I/O");return 0;
    } else error=sdr_control_request(&control,1,NULL,0,response,&size);
    if(mode==7) {
        assert(error==ERROR_TIMEOUT && !size && written_bytes==expected_bytes*3);
        for(unsigned i=0;i<3;++i) assert(!memcmp(written+i*expected_bytes,expected,expected_bytes));
    } else {
        assert(written_bytes==expected_bytes && !memcmp(written,expected,expected_bytes));
        if(mode==8) assert(error==(SDR_CONTROL_DEVICE_ERROR|5u) && !size);
        else if(mode==10) assert(error==ERROR_INSUFFICIENT_BUFFER && !size);
        else {
            assert(!error);
            if(mode==1 || mode==9 || mode==16) assert(size==14 && !memcmp(response,"{\"protocol\":1}",14));
            if(mode==16)assert(idle_yields==3 && !empty_before_data);
        }
    }
    puts("passed: native Windows control framing, partial I/O and typed service calls");return 0;
}
