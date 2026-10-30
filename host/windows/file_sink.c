#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0602
#include <windows.h>
#include <stdlib.h>
#include <string.h>
#include "file_sink.h"

struct sdr_file_sink {
    HANDLE file,thread;
    CRITICAL_SECTION lock;
    CONDITION_VARIABLE ready;
    unsigned char *buffer;
    uint32_t *length;
    /* count includes the slot owned by WriteFile. partial belongs exclusively
     * to the producer at write, and is never visible to the writer. */
    uint32_t block_bytes,blocks,read,write,count,partial,stopping,aborting;
    struct sdr_file_stats stats;
};
/* Called with lock held, including during close to flush the last short slot. */
static void publish_partial(sdr_file_sink *s)
{
    if(!s->partial) return;
    s->length[s->write]=s->partial;
    s->write=(s->write+1u)%s->blocks; ++s->count; s->partial=0;
    WakeConditionVariable(&s->ready);
}
static DWORD WINAPI writer(void *context)
{
    sdr_file_sink *s=context;
    for(;;) {
        EnterCriticalSection(&s->lock);
        while(!s->count && !s->stopping && !s->stats.error)
            SleepConditionVariableCS(&s->ready,&s->lock,INFINITE);
        if(s->aborting || s->stats.error || (!s->count && s->stopping)) {
            LeaveCriticalSection(&s->lock); return 0;
        }
        uint32_t slot=s->read,bytes=s->length[slot];
        LeaveCriticalSection(&s->lock);
        DWORD actual=0;
        BOOL done=WriteFile(s->file,s->buffer+(size_t)slot*s->block_bytes,bytes,&actual,NULL);
        DWORD error=done?0:GetLastError();
        if(actual>bytes) { actual=0; error=ERROR_INVALID_DATA; }
        else if(done && actual!=bytes) error=ERROR_WRITE_FAULT;
        EnterCriticalSection(&s->lock);
        s->stats.written_bytes+=actual;
        if(error && !s->stats.error) s->stats.error=error;
        s->read=(slot+1u)%s->blocks; --s->count;
        LeaveCriticalSection(&s->lock);
    }
}
uint32_t sdr_file_sink_open(sdr_file_sink **result,const char *path,uint32_t block_bytes,uint32_t blocks)
{
    if(!result) return ERROR_INVALID_PARAMETER;
    *result=NULL;
    if(!path || !block_bytes || block_bytes>4u*1024u*1024u || blocks<2u || blocks>256u ||
       (uint64_t)block_bytes*blocks>256u*1024u*1024u) return ERROR_INVALID_PARAMETER;
    sdr_file_sink *s=calloc(1,sizeof(*s));
    if(!s) return ERROR_NOT_ENOUGH_MEMORY;
    s->buffer=malloc((size_t)block_bytes*blocks); s->length=calloc(blocks,sizeof(*s->length));
    if(!s->buffer || !s->length) { free(s->length);free(s->buffer);free(s);return ERROR_NOT_ENOUGH_MEMORY; }
    s->file=CreateFileA(path,GENERIC_WRITE,FILE_SHARE_READ,NULL,CREATE_NEW,
        FILE_ATTRIBUTE_NORMAL|FILE_FLAG_SEQUENTIAL_SCAN,NULL);
    if(s->file==INVALID_HANDLE_VALUE) {
        DWORD error=GetLastError();free(s->length);free(s->buffer);free(s);return error;
    }
    s->block_bytes=block_bytes; s->blocks=blocks;
    InitializeCriticalSection(&s->lock); InitializeConditionVariable(&s->ready);
    s->thread=CreateThread(NULL,0,writer,s,0,NULL);
    if(!s->thread) {
        DWORD error=GetLastError();CloseHandle(s->file);DeleteCriticalSection(&s->lock);
        free(s->length);free(s->buffer);free(s);return error;
    }
    *result=s;return 0;
}
int sdr_file_sink_push(sdr_file_sink *s,const void *data,uint32_t bytes)
{
    if(!s) return 1;
    EnterCriticalSection(&s->lock);
    if(!data || !bytes || bytes>s->block_bytes) {
        if(!s->stats.error) s->stats.error=ERROR_INVALID_PARAMETER;
        WakeConditionVariable(&s->ready);LeaveCriticalSection(&s->lock);return 1;
    }
    if(s->stats.error || s->stopping) { LeaveCriticalSection(&s->lock);return 1; }
    if(bytes>s->block_bytes-s->partial) publish_partial(s);
    if(s->count==s->blocks) {
        s->stats.dropped_bytes+=bytes; ++s->stats.queue_full_events;
    } else {
        uint32_t slot=s->write;
        memcpy(s->buffer+(size_t)slot*s->block_bytes+s->partial,data,bytes);
        s->partial+=bytes;
        s->stats.queued_bytes+=bytes;
        uint32_t occupied=s->count+1u;
        if(occupied>s->stats.high_water_blocks) s->stats.high_water_blocks=occupied;
        if(s->partial==s->block_bytes) publish_partial(s);
    }
    LeaveCriticalSection(&s->lock);return 0;
}
static uint64_t ticks(FILETIME t)
{ return ((uint64_t)t.dwHighDateTime<<32)|t.dwLowDateTime; }
uint32_t sdr_file_sink_error(sdr_file_sink *s)
{
    if(!s) return 0;
    EnterCriticalSection(&s->lock);DWORD error=s->stats.error;LeaveCriticalSection(&s->lock);
    return error;
}
uint32_t sdr_file_sink_close(sdr_file_sink **handle,struct sdr_file_stats *stats,uint32_t drain_ms)
{
    if(!handle || !*handle || !stats || drain_ms>60000u) return ERROR_INVALID_PARAMETER;
    sdr_file_sink *s=*handle;
    LARGE_INTEGER frequency,begun,ended;
    QueryPerformanceFrequency(&frequency);QueryPerformanceCounter(&begun);
    EnterCriticalSection(&s->lock);
    publish_partial(s);s->stopping=1;WakeConditionVariable(&s->ready);
    LeaveCriticalSection(&s->lock);
    DWORD wait=WaitForSingleObject(s->thread,drain_ms);
    if(wait!=WAIT_OBJECT_0) {
        DWORD error=wait==WAIT_TIMEOUT?ERROR_TIMEOUT:GetLastError();
        EnterCriticalSection(&s->lock);
        s->aborting=1;if(!s->stats.error) s->stats.error=error;
        WakeConditionVariable(&s->ready);LeaveCriticalSection(&s->lock);
        CancelSynchronousIo(s->thread);
        wait=WaitForSingleObject(s->thread,1000);
    }
    QueryPerformanceCounter(&ended);
    FILETIME created,exited,kernel,user;
    EnterCriticalSection(&s->lock);
    s->stats.pending_blocks=s->count;
    s->stats.drain_seconds=(double)(ended.QuadPart-begun.QuadPart)/frequency.QuadPart;
    if(GetThreadTimes(s->thread,&created,&exited,&kernel,&user))
        s->stats.writer_cpu_seconds=(ticks(kernel)+ticks(user))*1e-7;
    *stats=s->stats;LeaveCriticalSection(&s->lock);
    if(wait!=WAIT_OBJECT_0) return stats->error?stats->error:ERROR_TIMEOUT;
    DWORD error=stats->error;
    if(!CloseHandle(s->file) && !error) error=GetLastError();
    CloseHandle(s->thread);DeleteCriticalSection(&s->lock);
    free(s->length);free(s->buffer);free(s);*handle=NULL;
    stats->error=error;return error;
}
