#include "bw0_usb_service.h"
#include "cp_usb_8910.h"
#include "rf_profile.h"
#include "raw_usb_function.h"
#include "debug_shared.h"
#include "bw0_service_blob.h"
#include "iot_os.h"
#include "osi_api.h"
#include "usb_segment_profile.h"
#include "sample_rate.h"
uint64_t sdr_usb_profile_clock(void){return osiUpTimeUS();}

static struct cp_usb_8910 capture;
static struct sdr_bw0_backend backend;
static volatile uint32_t *mailbox;
static struct sdr_udc *controller;
static struct sdr_usb_ep *endpoint;
static osiSemaphore_t *wake;
static uint32_t installed,busy,queued,stop_requested,epoch,duration_ms,phase,error,started_ms,elapsed_ms,active_elapsed_ms;
static uint32_t frequency_hz=881500000u,gain_index=40u;
static uint32_t rf_band=5u;
static uint32_t bandwidth_index;
static uint32_t reported_sample_rate(void)
{
#if defined(SDR_EXPERIMENTAL_PRE_SWITCH) && SDR_EXPERIMENTAL_PRE_SWITCH
    if(bandwidth_index>=5u) return 0u;
#elif defined(SDR_EXPERIMENTAL_BW5_PRE_SELECTOR)
    if(bandwidth_index==5u) return 0u; /* Unknown hardware timing in this experiment. */
#endif
    return sdr_nominal_sample_rate(bandwidth_index);
}
/* Per user START, cumulative across internal full-ring recovery epochs.
 * Only fully drained epochs are folded; their callbacks can no longer run. */
static uint32_t totals[12],folded_epoch,epoch_base,full_counted_epoch;
static uint32_t full_stops,recovery_attempts,recoveries,gap_pending,gap_target,recovery_cancelled;
static uint32_t gap_started_ms,last_gap_ms,max_gap_ms;
static uint64_t gap_total_ms;
static void session_counts(uint32_t out[12])
{
    const struct cp_usb_stream *s=&capture.stream;
    const uint32_t live[12]={s->ring.stats.submitted,s->ring.stats.completed,
        s->ring.stats.usb_failures,s->usb.rejected,s->usb.callback_errors,
        s->ring.stats.stop_drops,(uint32_t)s->ring.stats.completed_bytes,
        (uint32_t)(s->ring.stats.completed_bytes>>32),s->bridge.claimed,
        s->bridge.released,s->commands,capture.snapshot_misses};
    uint32_t include=capture.capture_epoch!=folded_epoch;
    for(unsigned i=0;i<12;++i) out[i]=totals[i]+(include?live[i]:0u);
    uint64_t bytes=((uint64_t)totals[7]<<32)|totals[6];
    if(include) bytes+=s->ring.stats.completed_bytes;
    out[6]=(uint32_t)bytes; out[7]=(uint32_t)(bytes>>32);
}
static uint32_t session_elapsed(uint32_t now)
{ return capture.session_clock_started?now-capture.session_started_ms:0u; }
static uint32_t gap_ready(void)
{ return gap_pending && capture.capture_epoch==gap_target && capture.opened && capture.epoch_started; }
static void request_stop(void *context)
{
    (void)context;
    uint32_t key=osiEnterCritical(); stop_requested=1; osiExitCritical(key);
    cp_usb_8910_stop(&capture);
    if(wake) osiSemaphoreRelease(wake);
}
static int launch(void *context)
{
    (void)context;
    if(stop_requested || cp_usb_8910_session_expired(&capture,(uint32_t)osiUpTime())) return 0;
    return backend.launch(backend.context);
}
static void worker(void *argument)
{
    (void)argument;
    for(;;) {
        osiSemaphoreAcquire(wake);
        uint32_t key=osiEnterCritical();
        uint32_t start=queued; queued=0;
        osiExitCritical(key);
        if(!start) {
            /* A fault may retain CP/UDC ownership after the run deadline.
             * Observe late STOP proof without launching another producer.
             */
            if(busy && capture.prepared && capture.stream.phase==CP_USB_FAULT)
                cp_usb_8910_tick(&capture);
            continue;
        }
        phase=2; started_ms=(uint32_t)osiUpTime();
        uint32_t restarting=capture.stream.phase==CP_USB_DRAINED;
        error=stop_requested?DBG_BUSY:restarting?0:backend.prepare(backend.context,
            sdr_bw0_resident_blob,sizeof(sdr_bw0_resident_blob),
            sdr_bw0_control_blob,sizeof(sdr_bw0_control_blob),
            SDR_BW0_CONTROL_ENTRY_OFFSET,SDR_BW0_GENERATION,
            sdr_rf_channel(rf_band,frequency_hz),gain_index,frequency_hz/100u,bandwidth_index);
        if(!error) {
            /* The CP service has not been launched yet. Initialize both
             * mailbox owner lines only while no producer can write them.
             */
            if(!restarting) {
                for(unsigned i=0;i<16;++i) mailbox[i]=0;
                osiDCacheClean((const void *)mailbox,64); dbg_cache_barrier();
            }
            phase=3;
            for(;;) {
                key=osiEnterCritical();
                uint32_t before_ms=session_elapsed((uint32_t)osiUpTime());
                if(cp_usb_8910_session_expired(&capture,(uint32_t)osiUpTime())) capture.stop_requested=1;
                if(gap_pending && (stop_requested || capture.stop_requested || (duration_ms && before_ms>=duration_ms))) {
                    ++recovery_cancelled; gap_pending=0; active_elapsed_ms=before_ms; phase=4;
                    osiExitCritical(key); break;
                }
                osiExitCritical(key);
                uint32_t previous_epoch=capture.capture_epoch;
                uint32_t remaining=duration_ms-session_elapsed((uint32_t)osiUpTime());
                /* First launch has no session clock yet. Later runs share
                 * one wall-clock deadline, including recovery intervals. */
                if(remaining>duration_ms) remaining=1u;
                uint32_t result=restarting?
                    cp_usb_8910_restart_bw(&capture,controller,endpoint,duration_ms?(remaining?remaining:1u):0u,
                        frequency_hz/100u,gain_index,sdr_rf_channel(rf_band,frequency_hz),bandwidth_index):
                    cp_usb_8910_run(&capture,&(struct cp_usb_8910_launch){
                        controller,endpoint,mailbox,duration_ms,launch,0});
                key=osiEnterCritical();
                uint32_t now=(uint32_t)osiUpTime();
                active_elapsed_ms=session_elapsed(now);
                error=capture.run_error?capture.run_error:capture.stream.error;
                if(restarting && capture.capture_epoch==previous_epoch && !error &&
                   !stop_requested && !capture.stop_requested) error=DBG_NOT_READY;
                if(gap_ready()) {
                    last_gap_ms=capture.stream.started_ms-gap_started_ms;
                    if(last_gap_ms>max_gap_ms) max_gap_ms=last_gap_ms;
                    gap_total_ms+=last_gap_ms; ++recoveries; gap_pending=0;
                }
                if(capture.epoch_started && (capture.last_snapshot.flags&2u) && full_counted_epoch!=capture.capture_epoch) {
                    ++full_stops; full_counted_epoch=capture.capture_epoch;
                }
                uint32_t recover=result==CP_USB_DRAINED && !error &&
                    (capture.last_snapshot.flags&2u) && !stop_requested && !capture.stop_requested &&
                    (!duration_ms || active_elapsed_ms<duration_ms);
                if(recover) {
                    uint32_t combined[12]; session_counts(combined);
                    for(unsigned i=0;i<12;++i) totals[i]=combined[i];
                    folded_epoch=capture.capture_epoch;
                    gap_started_ms=capture.source_stop_seen?capture.source_stop_seen_ms:now;
                    gap_target=capture.capture_epoch+1u; gap_pending=1;
                    ++recovery_attempts;
                } else phase=result==CP_USB_DRAINED && !error?4:5;
                if(!recover && result==CP_USB_DRAINED && gap_pending) {
                    gap_pending=0; ++recovery_cancelled;
                }
                osiExitCritical(key);
                if(!recover) break;
                /* Requests/callbacks and all CP slots are drained. Keep the
                 * exclusive endpoint and held CP; rearm without modem reset. */
                restarting=1;
            }
        } else phase=5;
        elapsed_ms=(uint32_t)osiUpTime()-started_ms;
        /* Do not confuse USB drain with returning the held RF/CP context.
         * Keep monitor ownership after any accepted/uncertain launch.
         */
        if(!capture.stream.usb.opened && !capture.mailbox.pending &&
            (!capture.launch_attempted || !capture.launch_result || capture.stream.cp_stopped)) {
            sdr_raw_capture_release();
            if(!capture.launch_attempted || !capture.launch_result) busy=0;
        }
        if(busy && capture.stream.phase==CP_USB_FAULT) {
            /* Bounded run has returned, but callbacks and CP may be late.
             * This persistent context remains alive; poll at low rate.
             */
            while(capture.stream.usb.opened || capture.mailbox.pending) {
                cp_usb_8910_tick(&capture);
                osiSemaphoreTryAcquire(wake,10);
            }
            if(capture.stream.cp_stopped) sdr_raw_capture_release();
        }
    }
}
int sdr_bw0_install(volatile uint32_t *lines,struct sdr_bw0_backend operations)
{
    if(installed || !lines || !operations.prepare || !operations.launch) return -1;
    backend=operations; mailbox=lines;
    wake=osiSemaphoreCreate(1,0);
    if(!wake) return -1;
    if(!iot_os_create_task(worker,0,8192,1,OPENAT_OS_CREATE_DEFAULT,"sdr_bw0")) {
        osiSemaphoreDelete(wake); wake=0; return -1;
    }
    installed=1; return 0;
}
int sdr_bw0_busy(void) { return busy!=0; }
uint32_t sdr_bw0_control(uint32_t op,const uint8_t *input,uint32_t size,uint8_t *output,uint32_t *output_size)
{
    *output_size=0;
#if defined(SDR_EXPERIMENTAL_FEM_OVERRIDE) && SDR_EXPERIMENTAL_FEM_OVERRIDE
    if(op==SDR_BW0_FEM_OVERRIDE) {
        if(size && (size!=8u || dbg_u32(input)!=1u))return DBG_BAD_REQUEST;
        if(size && dbg_u32(input+4)>2u)return DBG_RANGE;
        uint32_t key=osiEnterCritical();
        if(!installed){osiExitCritical(key);return DBG_NOT_READY;}
        /* First capture always uses the baseline. Diagnostic overrides are
         * selectable only after a completed/drained reusable capture. */
        if(size && (queued || phase!=4u || capture.stream.phase!=CP_USB_DRAINED ||
            !capture.stream.cp_stopped || capture.stream.usb.opened ||
            capture.mailbox.pending || capture.mailbox.fault)) {
            osiExitCritical(key);return DBG_BUSY;
        }
        if(size)capture.fem_override_mode=dbg_u32(input+4);
        uint32_t words[4]={0x314d4546u,1u,capture.fem_override_mode,epoch};
        for(unsigned i=0;i<4u;++i)dbg_put32(output+4u*i,words[i]);
        *output_size=sizeof(words);osiExitCritical(key);return DBG_OK;
    }
#endif
#if defined(SDR_BW0_LOSSY_SCRATCH) && SDR_BW0_LOSSY_SCRATCH
    if(op==SDR_BW0_SCRATCH_DROPS) {
        if(size)return DBG_BAD_REQUEST;
        uint32_t key=osiEnterCritical(),drops;
        if(!installed || queued || phase!=4 || !cp_usb_8910_final_scratch_drops(&capture,&drops)) {
            osiExitCritical(key);return DBG_BUSY;
        }
        dbg_put32(output,0x31504453u);dbg_put32(output+4,1u);
        dbg_put32(output+8,epoch);dbg_put32(output+12,drops);
        osiExitCritical(key);*output_size=16;return DBG_OK;
    }
#endif
    if(op==SDR_BW0_SEGMENTS) {
        if(size==4 && dbg_u32(input)==3u) {
            uint32_t key=osiEnterCritical();
            if(!installed){osiExitCritical(key);return DBG_NOT_READY;}
#if SDR_USB_SEGMENT_PROFILE
            uint32_t words[USB_REFILL_WORDS];usb_refill_words(words);
            words[3]=epoch;words[4]=phase;
            for(unsigned i=0;i<USB_REFILL_WORDS;++i)dbg_put32(output+4*i,words[i]);
            osiExitCritical(key);*output_size=sizeof(words);return DBG_OK;
#else
            osiExitCritical(key);return DBG_UNSUPPORTED;
#endif
        }
        /* Separate request and response ABI. ABI1 remains byte-for-byte
         * compatible, including its two reserved words. Counters belong to
         * the current/last adapter open, not necessarily the whole session. */
        if(size==4 && dbg_u32(input)==2) {
            uint32_t key=osiEnterCritical();
            if(!installed){osiExitCritical(key);return DBG_NOT_READY;}
#if SDR_USB_SEGMENT_PROFILE
            const struct usb_queue_observer *q=&capture.stream.usb.queue_observer;
            uint32_t words[]={0x31515055u,1u,(uint32_t)usb_segment_profile_enabled(),epoch,phase,
                q->accepted,q->completions,q->empty_completions,q->synchronous,q->rejected,q->cancelled,
                q->gap_count,(uint32_t)q->gap_total_us,(uint32_t)(q->gap_total_us>>32),q->gap_max_us,q->gap_open};
            for(unsigned i=0;i<sizeof(words)/sizeof(words[0]);++i)dbg_put32(output+4*i,words[i]);
            osiExitCritical(key);*output_size=sizeof(words);return DBG_OK;
#else
            osiExitCritical(key);return DBG_UNSUPPORTED;
#endif
        }
        if(size && (size!=8 || dbg_u32(input)!=1))return DBG_BAD_REQUEST;
        uint32_t key=osiEnterCritical();
        if(!installed){osiExitCritical(key);return DBG_NOT_READY;}
        if(size) {
            if(queued || phase==2 || phase==3 || (busy && capture.stream.phase!=CP_USB_DRAINED)) {
                osiExitCritical(key);return DBG_BUSY;
            }
            if(!usb_segment_profile_configure(dbg_u32(input+4))){osiExitCritical(key);return DBG_RANGE;}
        }
        uint32_t words[USB_PROFILE_WORDS];usb_segment_profile_words(words);
        words[36]=epoch;words[37]=phase;
        for(unsigned i=0;i<USB_PROFILE_WORDS;++i)dbg_put32(output+4*i,words[i]);
        osiExitCritical(key);*output_size=sizeof(words);return DBG_OK;
    }
    if(op==SDR_BW0_SCHEDULER) {
        uint32_t extended=size>=4 && dbg_u32(input)==2u;
        if(size && !((size==12 && dbg_u32(input)==1u) ||
            (extended && (size==4 || (size==12 && !dbg_u32(input+4) && !dbg_u32(input+8))))))return DBG_BAD_REQUEST;
        uint32_t key=osiEnterCritical();
        if(!installed) {osiExitCritical(key);return DBG_NOT_READY;}
        if(size==12) {
            if(queued || phase==2 || phase==3 || (busy && capture.stream.phase!=CP_USB_DRAINED)) {
                osiExitCritical(key);return DBG_BUSY;
            }
            if(extended)cp_usb_scheduler_automatic(&capture.scheduler);
            else if(!cp_usb_scheduler_configure(&capture.scheduler,dbg_u32(input+4),dbg_u32(input+8))) {
                osiExitCritical(key);return DBG_RANGE;
            }
        }
        uint32_t words[34];cp_usb_scheduler_words(&capture.scheduler,words);
        words[30]=epoch;words[31]=phase;
        if(extended) {words[1]=2;words[32]=capture.scheduler.manual_override;words[33]=capture.scheduler.bandwidth_index;}
        uint32_t count=extended?34u:32u;
        for(unsigned i=0;i<count;++i)dbg_put32(output+4*i,words[i]);
        osiExitCritical(key);*output_size=count*4u;return DBG_OK;
    }
    if(op==SDR_BW0_KEEPALIVE) {
        if(size) return DBG_BAD_REQUEST;
        uint32_t key=osiEnterCritical();
        if(!SDR_BW0_CONTINUOUS || !capture.session_lease_enabled || phase<1 || phase>3 ||
           stop_requested || capture.stop_requested || cp_usb_8910_session_expired(&capture,(uint32_t)osiUpTime())) {
            osiExitCritical(key); return DBG_BUSY;
        }
        capture.session_control_ms=(uint32_t)osiUpTime();
        osiExitCritical(key); return DBG_OK;
    }
    if(op==SDR_BW0_CONFIG) {
        uint32_t version=size>=4?dbg_u32(input):0;
        if(!((size==16 && version==1) || (size==20 && version==2))) return DBG_BAD_REQUEST;
        uint32_t bw=version==2?dbg_u32(input+16):0;
#if defined(SDR_EXPERIMENTAL_PRE_SWITCH) && SDR_EXPERIMENTAL_PRE_SWITCH
        if(bw>7u) return DBG_RANGE;
#else
        if(bw>SDR_BW0_MAX_BW) return DBG_RANGE;
#endif
        uint32_t band=dbg_u32(input+4);
        uint32_t hz=dbg_u32(input+8),gain=dbg_u32(input+12);
        if(!sdr_rf_channel(band,hz) || gain>124u) return DBG_RANGE;
#if defined(SDR_EXPERIMENTAL_FEM_OVERRIDE) && SDR_EXPERIMENTAL_FEM_OVERRIDE
        if(capture.fem_override_mode && band!=5u && band!=8u)return DBG_RANGE;
#endif
        uint32_t key=osiEnterCritical();
        if(!installed) { osiExitCritical(key); return DBG_NOT_READY; }
        if(queued || phase==2 || phase==3 || (busy && capture.stream.phase!=CP_USB_DRAINED)) {
            osiExitCritical(key); return DBG_BUSY;
        }
        frequency_hz=hz; gain_index=gain; rf_band=band; bandwidth_index=bw;
        osiExitCritical(key); return DBG_OK;
    }
    if(op==SDR_BW0_STOP) {
        if(size) return DBG_BAD_REQUEST;
        request_stop(0); return DBG_OK;
    }
    if(op==SDR_BW0_RECOVERY_STATUS) {
        if(size) return DBG_BAD_REQUEST;
        uint32_t key=osiEnterCritical(),now=(uint32_t)osiUpTime();
        uint32_t ready=gap_ready();
        uint32_t gap=ready?capture.stream.started_ms-gap_started_ms:last_gap_ms;
        uint64_t total=gap_total_ms+(ready?gap:0u);
        uint32_t words[SDR_BW0_RECOVERY_WORDS]={0x31524353u,1,epoch,
            capture.capture_epoch-epoch_base,full_stops,recovery_attempts,recoveries+ready,
            gap_pending && !ready,(uint32_t)total,(uint32_t)(total>>32),gap,
            gap>max_gap_ms?gap:max_gap_ms,gap_pending && !ready?now-gap_started_ms:0u,
            phase==3?session_elapsed(now):active_elapsed_ms,duration_ms,
            stop_requested || capture.stop_requested,1,0,capture.session_clock_started,
            capture.capture_epoch,recovery_cancelled,capture.lease_expired,capture.session_lease_enabled};
        for(unsigned i=0;i<SDR_BW0_RECOVERY_WORDS;++i) dbg_put32(output+4*i,words[i]);
        osiExitCritical(key); *output_size=sizeof(words); return DBG_OK;
    }
    if(op==SDR_BW0_STATUS) {
        if(size) return DBG_BAD_REQUEST;
        uint32_t key=osiEnterCritical();
        const struct cp_usb_stream *s=&capture.stream;
        uint32_t count[12]; session_counts(count);
        uint32_t words[SDR_BW0_WORDS]={0x31574353u,1,installed,phase,error,epoch,duration_ms,
            phase==2 || phase==3?(uint32_t)osiUpTime()-started_ms:elapsed_ms,2,reported_sample_rate(),4,12,
            s->phase,s->error,capture.run_error,busy,
            count[0],count[1],count[2],count[3],count[4],count[5],count[6],count[7],
            count[8],count[9],capture.mailbox.pending,count[10],
            s->stop_requested,s->stop_accepted,s->cp_stopped,count[11],
            capture.last_snapshot.phase,capture.last_snapshot.error,
            capture.last_snapshot.published,capture.last_snapshot.released,
            capture.last_snapshot.flags,capture.last_snapshot.dma_idle,
            capture.launch_attempted,capture.launch_result,(rf_band<<8)|(bandwidth_index<<4)};
        uint8_t raw_status[128]; uint32_t raw_bytes=0;
        if(sdr_raw_control(SDR_RAW_STATUS,0,0,raw_status,&raw_bytes)==DBG_OK && raw_bytes==128) {
            words[41]=dbg_u32(raw_status+8); words[42]=dbg_u32(raw_status+12);
            words[43]=dbg_u32(raw_status+16); words[44]=dbg_u32(raw_status+20);
        } else words[41]=DBG_NOT_READY;
        words[45]=gain_index;
        words[46]=phase==3?session_elapsed((uint32_t)osiUpTime()):active_elapsed_ms;
        words[47]=frequency_hz;
        for(unsigned i=0;i<SDR_BW0_WORDS;++i) dbg_put32(output+4*i,words[i]);
        osiExitCritical(key); *output_size=sizeof(words); return DBG_OK;
    }
    if(op!=SDR_BW0_START) return DBG_UNSUPPORTED;
    if(size!=16 || dbg_u32(input)!=1 || dbg_u32(input+8) || dbg_u32(input+12)) return DBG_BAD_REQUEST;
    uint32_t ms=dbg_u32(input+4);
    if((ms<100 && !(SDR_BW0_CONTINUOUS && !ms)) || ms>60000) return DBG_RANGE;
    uint32_t key=osiEnterCritical();
    if(!installed) { osiExitCritical(key); return DBG_NOT_READY; }
    uint32_t restart=(phase==4 || (phase==5 && error==DBG_BUSY)) && capture.stream.phase==CP_USB_DRAINED &&
        capture.stream.cp_stopped && !capture.stream.usb.opened && !capture.mailbox.pending &&
        !capture.mailbox.fault;
#if defined(SDR_EXPERIMENTAL_PRE_SWITCH) && SDR_EXPERIMENTAL_PRE_SWITCH
    if(bandwidth_index>=5u && ms>2000u) { osiExitCritical(key); return DBG_RANGE; }
    if(bandwidth_index>5u && !restart) { osiExitCritical(key); return DBG_NOT_READY; }
#endif
    if((busy || capture.launch_attempted) && !restart) { osiExitCritical(key); return DBG_BUSY; }
    if(epoch==UINT32_MAX) { osiExitCritical(key); return DBG_BUSY; }
    if(!sdr_raw_capture_acquire(&controller,&endpoint,request_stop,0)) {
        osiExitCritical(key); return DBG_NOT_READY;
    }
    busy=1; queued=1; stop_requested=0; capture.stop_requested=0;
    capture.session_clock_started=0; capture.session_duration_ms=ms;
    capture.session_lease_enabled=!ms; capture.session_control_ms=(uint32_t)osiUpTime(); capture.lease_expired=0;
    for(unsigned i=0;i<12;++i) totals[i]=0;
    folded_epoch=epoch_base=full_counted_epoch=capture.capture_epoch;
    full_stops=recovery_attempts=recoveries=gap_pending=last_gap_ms=max_gap_ms=recovery_cancelled=0;
    gap_total_ms=0;
    cp_usb_scheduler_begin(&capture.scheduler,bandwidth_index);
    usb_segment_profile_reset();
    duration_ms=ms; error=0; phase=1; elapsed_ms=active_elapsed_ms=0; ++epoch;
    dbg_put32(output,epoch); *output_size=4;
    osiExitCritical(key); osiSemaphoreRelease(wake); return DBG_OK;
}
