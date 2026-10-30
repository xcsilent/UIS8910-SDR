#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "sdr_control.h"

struct sdr_control {
    HANDLE file;
    uint32_t sequence,timeout_ms,used;
    unsigned char buffer[2u*(SDR_CONTROL_MAX_PAYLOAD+20u)];
};
static uint32_t get32(const unsigned char *p)
{ return p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24); }
static void put32(unsigned char *p,uint32_t v)
{ p[0]=(unsigned char)v;p[1]=(unsigned char)(v>>8);p[2]=(unsigned char)(v>>16);p[3]=(unsigned char)(v>>24); }
static uint32_t crc_update(uint32_t crc,const unsigned char *p,uint32_t bytes)
{
    while(bytes--) {
        crc^=*p++;
        for(unsigned i=0;i<8;++i) crc=(crc>>1)^(0xedb88320u& (0u-(crc&1u)));
    }
    return crc;
}
static void discard(sdr_control *s,uint32_t bytes)
{ s->used-=bytes;memmove(s->buffer,s->buffer+bytes,s->used); }

uint32_t sdr_control_open(sdr_control **result,const wchar_t *port,uint32_t timeout_ms)
{
    if(!result) return ERROR_INVALID_PARAMETER;
    *result=NULL;
    if(!port || wcsncmp(port,L"COM",3) || !port[3] || !timeout_ms || timeout_ms>10000u)
        return ERROR_INVALID_PARAMETER;
    for(const wchar_t *p=port+3;*p;++p) if(*p<L'0' || *p>L'9') return ERROR_INVALID_PARAMETER;
    if(wcslen(port)>32) return ERROR_INVALID_PARAMETER;
    wchar_t path[40];swprintf(path,40,L"\\\\.\\%ls",port);
    sdr_control *s=calloc(1,sizeof(*s));
    if(!s) return ERROR_NOT_ENOUGH_MEMORY;
    s->file=CreateFileW(path,GENERIC_READ|GENERIC_WRITE,0,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    if(s->file==INVALID_HANDLE_VALUE) { DWORD e=GetLastError();free(s);return e; }
    DCB state={0};state.DCBlength=sizeof(state);
    DWORD error=0;
    if(!GetCommState(s->file,&state)) { error=GetLastError();goto failed; }
    state.BaudRate=115200;state.ByteSize=8;state.Parity=NOPARITY;state.StopBits=ONESTOPBIT;
    state.fBinary=TRUE;state.fParity=FALSE;state.fOutxCtsFlow=FALSE;state.fOutxDsrFlow=FALSE;
    state.fDsrSensitivity=FALSE;state.fOutX=FALSE;state.fInX=FALSE;
    state.fNull=FALSE;state.fErrorChar=FALSE;state.fAbortOnError=FALSE;state.fTXContinueOnXoff=TRUE;
    state.fDtrControl=DTR_CONTROL_ENABLE;state.fRtsControl=RTS_CONTROL_ENABLE;
    if(!SetCommState(s->file,&state)) { error=GetLastError();goto failed; }
    /* Return available bytes immediately. The current USB serial driver can
     * turn a positive read-total timeout into about100ms per reply even with
     * a1ms constant. The outer request deadline/retry owns the timeout; idle
     * reads yield below instead of accumulating driver receive waits. */
    COMMTIMEOUTS timeouts={MAXDWORD,0,0,0,timeout_ms};
    if(!SetCommTimeouts(s->file,&timeouts)) { error=GetLastError();goto failed; }
    if(!PurgeComm(s->file,PURGE_RXCLEAR|PURGE_TXCLEAR)) { error=GetLastError();goto failed; }
    LARGE_INTEGER stamp;QueryPerformanceCounter(&stamp);
    s->sequence=(uint32_t)stamp.QuadPart^GetCurrentProcessId();
    s->timeout_ms=timeout_ms;*result=s;return 0;
failed:
    CloseHandle(s->file);free(s);return error;
}
void sdr_control_close(sdr_control *s)
{ if(s) { CloseHandle(s->file);free(s); } }

uint32_t sdr_control_request(sdr_control *s,uint32_t operation,const void *payload,
    uint32_t bytes,void *receive,uint32_t *receive_bytes)
{
    if(!receive_bytes) return ERROR_INVALID_PARAMETER;
    uint32_t capacity=*receive_bytes;*receive_bytes=0;
    if(!s || bytes>SDR_CONTROL_MAX_PAYLOAD || (bytes && !payload) || (capacity && !receive) ||
       !(operation==1 || (operation>=40 && operation<=42) || (operation>=44 && operation<=49))) return ERROR_INVALID_PARAMETER;
    unsigned char request[SDR_CONTROL_MAX_PAYLOAD+20u]={0};
    memcpy(request,"UDG1",4);request[4]=1;request[5]=(unsigned char)operation;
    request[6]=(unsigned char)bytes;request[7]=(unsigned char)(bytes>>8);
    if(!++s->sequence) ++s->sequence;
    put32(request+8,s->sequence);
    if(bytes) memcpy(request+20,payload,bytes);
    uint32_t crc=crc_update(0xffffffffu,request,16);
    put32(request+16,~crc_update(crc,request+20,bytes));
    /* Exactly the same sequence/frame on retry: never duplicate a START by
     * inventing a new transaction after an uncertain response. */
    for(unsigned attempt=0;attempt<3;++attempt) {
        ULONGLONG deadline=GetTickCount64()+s->timeout_ms;
        DWORD sent=0;
        while(sent<bytes+20u) {
            DWORD actual=0;
            if(!WriteFile(s->file,request+sent,bytes+20u-sent,&actual,NULL)) return GetLastError();
            if(!actual || actual>bytes+20u-sent) return ERROR_WRITE_FAULT;
            sent+=actual;
            if(GetTickCount64()>=deadline) return ERROR_TIMEOUT;
        }
        while(GetTickCount64()<deadline) {
            while(s->used>=4) {
                uint32_t at=0;
                while(at+4<=s->used && memcmp(s->buffer+at,"UDG1",4)) ++at;
                if(at) discard(s,at);
                if(s->used<20) break;
                unsigned char *p=s->buffer;
                uint32_t length=p[6]|((uint32_t)p[7]<<8);
                if(p[4]!=1 || length>SDR_CONTROL_MAX_PAYLOAD) { discard(s,1);continue; }
                if(s->used<20u+length) break;
                uint32_t checked=crc_update(0xffffffffu,p,16);
                checked=~crc_update(checked,p+20,length);
                if(checked!=get32(p+16)) { discard(s,1);continue; }
                if(p[5]!=(operation|0x80u) || get32(p+8)!=s->sequence) { discard(s,20u+length);continue; }
                uint32_t status=get32(p+12);
                if(status) { discard(s,20u+length);return SDR_CONTROL_DEVICE_ERROR|status; }
                if(length>capacity) { discard(s,20u+length);return ERROR_INSUFFICIENT_BUFFER; }
                if(length) memcpy(receive,p+20,length);
                *receive_bytes=length;discard(s,20u+length);return 0;
            }
            DWORD actual=0,available=(DWORD)sizeof(s->buffer)-s->used;
            if(!available) return ERROR_INVALID_DATA;
            if(available>1024u) available=1024u;
            if(!ReadFile(s->file,s->buffer+s->used,available,&actual,NULL)) return GetLastError();
            if(actual>available) return ERROR_INVALID_DATA;
            s->used+=actual;
            if(!actual) Sleep(1);
        }
    }
    return ERROR_TIMEOUT;
}
uint32_t sdr_control_configure(sdr_control *s,uint32_t band,uint32_t frequency,uint32_t gain)
{ return sdr_control_configure_bw(s,band,frequency,gain,0); }
uint32_t sdr_control_configure_bw(sdr_control *s,uint32_t band,uint32_t frequency,uint32_t gain,uint32_t bandwidth)
{
    if(!frequency || frequency%100u || gain>124u || bandwidth>SDR_HOST_MAX_BANDWIDTH_INDEX) return ERROR_INVALID_PARAMETER;
    unsigned char payload[20];put32(payload,bandwidth?2:1);put32(payload+4,band);put32(payload+8,frequency);put32(payload+12,gain);
    put32(payload+16,bandwidth);
    uint32_t bytes=0;return sdr_control_request(s,47,payload,bandwidth?20:16,NULL,&bytes);
}
uint32_t sdr_control_start(sdr_control *s,uint32_t duration,uint32_t *epoch)
{
    if(!epoch || (duration && duration<100u) || duration>60000u) return ERROR_INVALID_PARAMETER;
    *epoch=0;unsigned char payload[16]={0},response[4];put32(payload,1);put32(payload+4,duration);
    uint32_t bytes=sizeof(response),error=sdr_control_request(s,45,payload,sizeof(payload),response,&bytes);
    if(error) return error;
    if(bytes!=4 || !get32(response)) return ERROR_INVALID_DATA;
    *epoch=get32(response);return 0;
}
uint32_t sdr_control_stop(sdr_control *s)
{ uint32_t bytes=0;return sdr_control_request(s,46,NULL,0,NULL,&bytes); }
uint32_t sdr_control_keepalive(sdr_control *s)
{ uint32_t bytes=0;return sdr_control_request(s,49,NULL,0,NULL,&bytes); }
static uint32_t words(sdr_control *s,uint32_t op,uint32_t *out,uint32_t count,uint32_t magic)
{
    if(!out) return ERROR_INVALID_PARAMETER;
    memset(out,0,count*4u);unsigned char data[192];uint32_t bytes=count*4u;
    uint32_t error=sdr_control_request(s,op,NULL,0,data,&bytes);
    if(error) return error;
    if(bytes!=count*4u || get32(data)!=magic || get32(data+4)!=1) return ERROR_INVALID_DATA;
    for(uint32_t i=0;i<count;++i) out[i]=get32(data+4*i);
    return 0;
}
uint32_t sdr_control_status(sdr_control *s,uint32_t out[48])
{ return words(s,44,out,48,0x31574353u); }
uint32_t sdr_control_recovery(sdr_control *s,uint32_t out[24])
{ return words(s,48,out,24,0x31524353u); }
