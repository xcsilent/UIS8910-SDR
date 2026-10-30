#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0602
#include <windows.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>

static HANDLE writing,allow_write;
static int mode;
static LONG write_calls;
static BOOL WINAPI controlled_write(HANDLE file,LPCVOID data,DWORD bytes,LPDWORD actual,LPOVERLAPPED overlapped)
{
    InterlockedIncrement(&write_calls);
    if(mode==1) {
        SetEvent(writing);
        assert(WaitForSingleObject(allow_write,10000)==WAIT_OBJECT_0);
    }
    if(mode==2) return WriteFile(file,data,bytes/2,actual,overlapped);
    if(mode==3) { *actual=0;SetLastError(ERROR_DISK_FULL);return FALSE; }
    return WriteFile(file,data,bytes,actual,overlapped);
}
#define WriteFile controlled_write
#include "../../host/windows/file_sink.c"
#undef WriteFile

static void verify_file(const char *path,const unsigned char *expected,DWORD bytes)
{
    HANDLE f=CreateFileA(path,GENERIC_READ,FILE_SHARE_READ,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,NULL);
    assert(f!=INVALID_HANDLE_VALUE);
    LARGE_INTEGER size;assert(GetFileSizeEx(f,&size) && size.QuadPart==bytes);
    unsigned char data[2048];DWORD actual;
    assert(bytes<=sizeof(data) && ReadFile(f,data,bytes,&actual,NULL) && actual==bytes);
    assert(!memcmp(data,expected,bytes));CloseHandle(f);
}
int main(int argc,char **argv)
{
    assert(argc==2);
    char path[MAX_PATH];
    writing=CreateEventW(NULL,TRUE,FALSE,NULL);allow_write=CreateEventW(NULL,TRUE,FALSE,NULL);
    assert(writing && allow_write);
    sdr_file_sink *sink=NULL;struct sdr_file_stats stats;
    assert(sdr_file_sink_open(&sink,"unused",512,1)==ERROR_INVALID_PARAMETER);
    assert(sdr_file_sink_open(&sink,"unused",4*1024*1024,256)==ERROR_INVALID_PARAMETER);
    snprintf(path,sizeof(path),"%s\\ordered.raw",argv[1]);
    assert(!sdr_file_sink_open(&sink,path,512,2));
    unsigned char data[512],expected[1024];
    memset(data,0x11,sizeof(data));memset(expected,0x11,512);memset(expected+512,0x22,512);
    mode=1;
    assert(!sdr_file_sink_push(sink,data,512));
    assert(WaitForSingleObject(writing,5000)==WAIT_OBJECT_0);
    memset(data,0x22,sizeof(data));assert(!sdr_file_sink_push(sink,data,512));
    memset(data,0x33,sizeof(data));assert(!sdr_file_sink_push(sink,data,512));
    /* Writer is blocked; producer returned and both owned blocks stay intact. */
    assert(sink->stats.queued_bytes==1024 && sink->stats.dropped_bytes==512);
    assert(sink->stats.high_water_blocks==2);
    SetEvent(allow_write);
    assert(!sdr_file_sink_close(&sink,&stats,5000) && !sink);
    assert(stats.written_bytes==1024 && stats.queue_full_events==1 && !stats.pending_blocks);
    verify_file(path,expected,1024);
    assert(sdr_file_sink_open(&sink,path,512,2)==ERROR_FILE_EXISTS && !sink);
    verify_file(path,expected,1024);

    mode=0;write_calls=0;snprintf(path,sizeof(path),"%s\\short-blocks.raw",argv[1]);
    assert(!sdr_file_sink_open(&sink,path,512,32));
    unsigned offset=0;
    for(unsigned i=1;i<=32;++i) {
        memset(data,(int)i,i);memset(expected+offset,(int)i,i);offset+=i;
        assert(!sdr_file_sink_push(sink,data,i));
    }
    assert(!sdr_file_sink_close(&sink,&stats,5000));
    assert(stats.written_bytes==528 && !stats.dropped_bytes && write_calls==2);
    verify_file(path,expected,528);

    /* An in-flight full slot stays owned while a second, partially filled
     * producer slot accumulates short inputs. Publishing it fills the queue;
     * drop the next whole input, then flush in order, including the tail. */
    mode=1;write_calls=0;ResetEvent(writing);ResetEvent(allow_write);
    snprintf(path,sizeof(path),"%s\\partial-full.raw",argv[1]);
    assert(!sdr_file_sink_open(&sink,path,512,2));
    memset(data,0x44,512);assert(!sdr_file_sink_push(sink,data,512));
    assert(WaitForSingleObject(writing,5000)==WAIT_OBJECT_0);
    memset(expected,0x44,512);memset(expected+512,0x55,400);
    memset(data,0x55,200);
    assert(!sdr_file_sink_push(sink,data,200));assert(!sdr_file_sink_push(sink,data,200));
    memset(data,0x66,200);assert(!sdr_file_sink_push(sink,data,200));
    assert(sink->stats.queued_bytes==912 && sink->stats.dropped_bytes==200);
    assert(sink->stats.high_water_blocks==2 && sink->count==2 && !sink->partial);
    SetEvent(allow_write);assert(!sdr_file_sink_close(&sink,&stats,5000));
    assert(stats.written_bytes==912 && stats.queue_full_events==1 && write_calls==2);
    verify_file(path,expected,912);

    /* Constant 8-byte short reads become a single full write plus a close tail;
     * ring wrap is exercised after the previous two slots are returned. */
    mode=0;write_calls=0;snprintf(path,sizeof(path),"%s\\batch-wrap.raw",argv[1]);
    assert(!sdr_file_sink_open(&sink,path,512,2));
    for(unsigned i=0;i<128;++i) {
        memset(data,(int)i,8);memset(expected+8*i,(int)i,8);
        assert(!sdr_file_sink_push(sink,data,8));
    }
    for(unsigned i=0;i<5000;++i) {
        EnterCriticalSection(&sink->lock);uint32_t count=sink->count;LeaveCriticalSection(&sink->lock);
        if(!count) break;
        Sleep(1);
    }
    EnterCriticalSection(&sink->lock);assert(!sink->count);LeaveCriticalSection(&sink->lock);
    memset(data,0x77,3);assert(!sdr_file_sink_push(sink,data,3));
    assert(!sdr_file_sink_close(&sink,&stats,5000));
    /* verify_file's expected array is extended by a separate small buffer. */
    unsigned char wrapped[1027];memcpy(wrapped,expected,1024);memset(wrapped+1024,0x77,3);
    assert(stats.written_bytes==1027 && !stats.dropped_bytes && write_calls==3);
    verify_file(path,wrapped,1027);

    mode=2;snprintf(path,sizeof(path),"%s\\partial.raw",argv[1]);
    assert(!sdr_file_sink_open(&sink,path,512,2));assert(!sdr_file_sink_push(sink,data,512));
    assert(sdr_file_sink_close(&sink,&stats,5000)==ERROR_WRITE_FAULT && !sink);
    assert(stats.written_bytes==256 && stats.queued_bytes==512);

    mode=3;snprintf(path,sizeof(path),"%s\\disk-full.raw",argv[1]);
    assert(!sdr_file_sink_open(&sink,path,512,2));assert(!sdr_file_sink_push(sink,data,512));
    assert(sdr_file_sink_close(&sink,&stats,5000)==ERROR_DISK_FULL && !sink && !stats.written_bytes);

    mode=1;ResetEvent(writing);ResetEvent(allow_write);
    snprintf(path,sizeof(path),"%s\\timeout.raw",argv[1]);
    assert(!sdr_file_sink_open(&sink,path,512,2));assert(!sdr_file_sink_push(sink,data,512));
    assert(WaitForSingleObject(writing,5000)==WAIT_OBJECT_0);
    assert(sdr_file_sink_close(&sink,&stats,0)==ERROR_TIMEOUT && sink);
    assert(stats.pending_blocks==1 && sdr_file_sink_error(sink)==ERROR_TIMEOUT);
    assert(sdr_file_sink_push(sink,data,512)==1);
    SetEvent(allow_write);
    assert(sdr_file_sink_close(&sink,&stats,5000)==ERROR_TIMEOUT && !sink);
    assert(!stats.pending_blocks && stats.written_bytes==512);
    CloseHandle(writing);CloseHandle(allow_write);
    puts("file sink passed: owned buffers, short-read batching, partial queue overflow, close tail, ring wrap, ordered writes, no overwrite, partial/error writes, timeout retention and retry cleanup");
    return 0;
}
