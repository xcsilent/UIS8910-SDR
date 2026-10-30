#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#ifdef DBG_HOST_TEST
#include "debug_test_platform.h"
#else
#include "iot_uart.h"
#include "iot_os.h"
#include "osi_api.h"
#endif
#include "debug_shared.h"
#include "cp_agent_blob.h"
#ifdef DBG_ENABLE_RAW_USB
#include "raw_usb_function.h"
#endif
#ifdef DBG_ENABLE_BW0_USB
#include "bw0_usb_service.h"
#include "rf_profiles_info.h"
#include "cp_usb_scheduler.h"
#define DBG_SCHED_STRING_INNER(x) #x
#define DBG_SCHED_STRING(x) DBG_SCHED_STRING_INNER(x)
#endif
#ifdef DBG_RECEIVER_SERVICE
#include "receiver_service_blob.h"
#endif

#define FRAME_HEADER 20u
#if defined(DBG_ENABLE_RX_STREAM) && (!defined(DBG_ENABLE_BULK) || !defined(DBG_ENABLE_ASYNC_CALL))
#error RX streaming requires bulk staging and asynchronous CP submission
#endif
#ifdef DBG_ENABLE_RX_STREAM
#define DBG_STREAM_INFO ",\"rxcapt_ap_stream\":true,\"rxcapt_ap_stream_version\":1"
#ifdef DBG_ENABLE_RX_REUSE
#undef DBG_STREAM_INFO
#define DBG_STREAM_INFO ",\"rxcapt_ap_stream\":true,\"rxcapt_ap_stream_version\":1,\"rxcapt_ap_reuse_stream\":true,\"rxcapt_ap_reuse_version\":1,\"rxcapt_ap_reuse_operation\":34"
#endif
#else
#define DBG_STREAM_INFO ""
#endif
#ifdef DBG_ENABLE_ASYNC_CALL
#define DBG_ASYNC_INFO ",\"cp_call_async\":true"
#else
#define DBG_ASYNC_INFO ",\"cp_call_async\":false"
#endif
#ifdef DBG_ENABLE_BULK
#define DBG_FIRMWARE_NAME "uis8910-debug-v2-bulk"
#define DBG_BULK_INFO ",\"bulk_read\":true,\"bulk_max_bytes\":65536,\"bulk_chunk_bytes\":4080"
#define BULK_LIMIT 65536u
#define BULK_META 16u
#define BULK_CHUNK (DBG_MAX_PAYLOAD-BULK_META)
#else
#define DBG_FIRMWARE_NAME "uis8910-debug-v1"
#define DBG_BULK_INFO ""
#endif
#ifdef DBG_RECEIVER_SERVICE
#undef DBG_FIRMWARE_NAME
#define DBG_FIRMWARE_NAME "uis8910-rxcapt-service-v1"
#define DBG_RX_SERVICE_INFO ",\"rxcapt_resident_preload\":true,\"rxcapt_resident_ready\":%s,\"rxcapt_resident_status\":%lu,\"rxcapt_resident_bytes\":%lu"
#define DBG_RX_SERVICE_VALUES ,receiver_resident_status==DBG_OK?"true":"false",(unsigned long)receiver_resident_status,(unsigned long)sizeof(rxcapt_resident_blob)
#define RXCAPT_RESIDENT_BASE 0x8097b000u
#else
#define DBG_RX_SERVICE_INFO ""
#define DBG_RX_SERVICE_VALUES
#endif
#ifdef DBG_ENABLE_RX_STREAM
#undef DBG_FIRMWARE_NAME
#define DBG_FIRMWARE_NAME "uis8910-rxcapt-stream-v2"
#endif
#ifdef DBG_ENABLE_RX_STREAM_FAST
#if !defined(DBG_ENABLE_RX_STREAM)
#error Fast RX streaming requires RX streaming
#endif
#undef DBG_FIRMWARE_NAME
#define DBG_FIRMWARE_NAME "uis8910-rxcapt-stream-v3"
#define DBG_STREAM_PROFILE_INFO ",\"rxcapt_ap_profile\":true,\"rxcapt_ap_profile_offset\":64,\"rxcapt_ap_profile_bytes\":128"
#else
#define DBG_STREAM_PROFILE_INFO ""
#endif
#ifdef DBG_ENABLE_RAW_USB
#undef DBG_FIRMWARE_NAME
#define DBG_FIRMWARE_NAME "uis8910-sdr-raw-usb-v1"
#define DBG_RAW_INFO ",\"raw_usb\":true,\"raw_usb_abi\":1,\"raw_usb_status_operation\":40,\"raw_usb_start_operation\":41,\"raw_usb_stop_operation\":42,\"raw_usb_source\":\"fixed_ap_buffer_benchmark\""
#else
#define DBG_RAW_INFO ""
#endif
#ifdef DBG_ENABLE_BW0_USB
#undef DBG_FIRMWARE_NAME
#define DBG_FIRMWARE_NAME "uis8910-sdr-bw0-usb-v1"
#if defined(SDR_EXPERIMENTAL_PRE_SWITCH) && SDR_EXPERIMENTAL_PRE_SWITCH
#define DBG_BW_EXPERIMENT_INFO ",\"bw0_experimental_pre_selectors\":[5,6,7],\"bw0_experimental_rf_mode\":5,\"bw0_experimental_rate_known\":false"
#elif defined(SDR_EXPERIMENTAL_BW5_PRE_SELECTOR)
#define DBG_STRING_INNER(x) #x
#define DBG_STRING(x) DBG_STRING_INNER(x)
#define DBG_BW_EXPERIMENT_INFO ",\"bw0_experimental_pre_selector\":" DBG_STRING(SDR_EXPERIMENTAL_BW5_PRE_SELECTOR) ",\"bw0_experimental_rf_mode\":5,\"bw0_experimental_rate_known\":false"
#else
#define DBG_BW_EXPERIMENT_INFO ""
#endif
#if defined(SDR_BW0_LOSSY_SCRATCH) && SDR_BW0_LOSSY_SCRATCH
#define DBG_SCRATCH_INFO ",\"bw0_scratch_drops_operation\":52,\"bw0_scratch_drops_abi\":1"
#else
#define DBG_SCRATCH_INFO ""
#endif
#if defined(SDR_USB_SEGMENT_PROFILE) && SDR_USB_SEGMENT_PROFILE
#define DBG_QUEUE_INFO ",\"bw0_queue_profile_abi\":1,\"bw0_refill_profile_abi\":1"
#else
#define DBG_QUEUE_INFO ""
#endif
#define DBG_BW_INFO ",\"bw0_bandwidth_indices\":" SDR_BW_INDICES_JSON ",\"bw0_config_abi\":2,\"bw0_sample_rate_is_nominal\":true,\"bw0_scheduler_operation\":50,\"bw0_scheduler_abi\":1,\"bw0_scheduler_policy_abi\":2,\"bw0_scheduler_auto_wait_min_bw\":" DBG_SCHED_STRING(CP_USB_SCHEDULER_WIDE_MIN_BW) ",\"bw0_wait_us_is_default\":true,\"bw0_segment_profile_operation\":51,\"bw0_segment_profile_abi\":1" DBG_QUEUE_INFO DBG_SCRATCH_INFO
#if CP_USB_COMBINED_EXCHANGE
#define DBG_EXCHANGE_INFO ",\"bw0_cp_exchange_operation\":14"
#else
#define DBG_EXCHANGE_INFO ""
#endif
#if SDR_BW0_CONTINUOUS
#define DBG_CONTINUOUS_INFO ",\"bw0_until_stop\":true,\"bw0_keepalive_operation\":49,\"bw0_lease_timeout_ms\":5000" DBG_EXCHANGE_INFO
#else
#define DBG_CONTINUOUS_INFO ""
#endif
#if defined(SDR_EXPERIMENTAL_FEM_OVERRIDE) && SDR_EXPERIMENTAL_FEM_OVERRIDE
#define DBG_FEM_INFO ",\"bw0_fem_override_operation\":53,\"bw0_fem_override_abi\":1"
#else
#define DBG_FEM_INFO ""
#endif
#define DBG_BW0_INFO ",\"bw0_usb\":true,\"bw0_status_operation\":44,\"bw0_start_operation\":45,\"bw0_stop_operation\":46,\"bw0_config_operation\":47,\"bw0_recovery_status_operation\":48,\"bw0_rf_profiles\":" SDR_RF_PROFILES_JSON ",\"bw0_wait_policy\":\"notification_or_high_precision_sleep\",\"bw0_wait_us\":250" DBG_BW_INFO DBG_CONTINUOUS_INFO DBG_BW_EXPERIMENT_INFO DBG_FEM_INFO
#else
#define DBG_BW0_INFO ""
#endif
#ifdef DBG_ENABLE_RX_STREAM_BURST
#if !defined(DBG_ENABLE_RX_STREAM_FAST)
#error Burst streaming requires fast RX streaming
#endif
#undef DBG_FIRMWARE_NAME
#define DBG_FIRMWARE_NAME "uis8910-rxcapt-stream-v4"
#undef DBG_STREAM_PROFILE_INFO
#define DBG_STREAM_PROFILE_INFO ",\"rxcapt_ap_profile\":true,\"rxcapt_ap_profile_offset\":64,\"rxcapt_ap_profile_bytes\":128,\"rxcapt_ap_copy_mode_offset\":192"
#endif
static cp_mailbox_t *const mailbox=(cp_mailbox_t *)CP_DEBUG_BASE;
static uint32_t cp_seq=1,cp_pending;
#ifdef DBG_RECEIVER_SERVICE
static uint32_t receiver_resident_status=DBG_NOT_READY;
#endif
#ifdef DBG_HOST_TEST
#define test_ram (*(uint8_t (*)[4096])0x80f10000u)
#else
static uint8_t test_ram[4096] __attribute__((aligned(32)));
#endif
static uint8_t upload[CP_SLOT_SIZE] __attribute__((aligned(32)));
static struct {uint32_t size,entry_offset,generation,received;uint8_t hash[32];bool open,ready;} package;
typedef struct {
 E_AMOPENAT_UART_PORT port;
 uint8_t rx[FRAME_HEADER+DBG_MAX_PAYLOAD],tx[FRAME_HEADER+DBG_MAX_PAYLOAD];
 uint32_t used,last_seq,last_crc,last_op,tx_size;
 int64_t last_byte;
 bool have_reply;
#ifdef DBG_ENABLE_BULK
 bool have_bulk;
 uint32_t bulk_size;
 uint8_t bulk[BULK_LIMIT] __attribute__((aligned(32)));
#endif
} transport_t;
static transport_t channels[2];
extern int debug_load_word(uint32_t address,uint32_t width,uint32_t *value);
extern int debug_store_word(uint32_t address,uint32_t width,uint32_t value);
extern int debug_copy_words(uint32_t address,void *destination,uint32_t words);
extern int debug_copy_words_burst(uint32_t address,void *destination,uint32_t words);

/* AP system atDeviceWrite jumps here. No APPIMG BSS/stub dependency: callable
 * during platform startup before appimg_enter. Suppress only the PC AT device;
 * virtual AT services keep their response path. OpenAT USB writes drvSerial directly. */
__attribute__((used)) int debug_at_write_filter(void *device,const void *data,size_t size) {
 void *pc_device=*(void *volatile *)0x809a7f10;
 if(device==pc_device)return size;
 int (*write_fn)(void *,const void *,size_t)=*(int (**)(void *,const void *,size_t))((uint8_t *)device+12);
 return write_fn?write_fn(device,data,size):0;
}

static void clean(const void *p,size_t n) {osiDCacheClean(p,n);dbg_cache_barrier();}
static void invalidate(const void *p,size_t n) {
 uintptr_t a=(uintptr_t)p&~31u;osiDCacheInvalidate((const void *)a,(((uintptr_t)p+n+31)&~31u)-a);
 dbg_cache_barrier();
}
#ifdef DBG_RECEIVER_SERVICE
static uint32_t preload_receiver_resident(void) {
 if(sizeof(rxcapt_resident_blob)>0x3600u)return DBG_RANGE;
 /* dyn_debug reserves 0x8097b000..0x80980000 for this resident and its
  * private stack/state. Do not touch the CP agent or its three module slots. */
 memcpy((void *)RXCAPT_RESIDENT_BASE,rxcapt_resident_blob,sizeof(rxcapt_resident_blob));
 clean((const void *)RXCAPT_RESIDENT_BASE,sizeof(rxcapt_resident_blob));
 invalidate((const void *)RXCAPT_RESIDENT_BASE,sizeof(rxcapt_resident_blob));
 return memcmp((const void *)RXCAPT_RESIDENT_BASE,rxcapt_resident_blob,
               sizeof(rxcapt_resident_blob))?DBG_DIGEST:DBG_OK;
}
#endif
static int cp_install(void) {
 /* Cold boot reservation must be present, not guessed from unused RAM. */
 const uint8_t *index=(const uint8_t *)0x80000000;
 bool region=false;
 for(unsigned i=0;i<128 && index[i*32];i++) {
  const uint8_t *r=index+i*32;
  if(!memcmp(r,"dyn_debug",10) && dbg_u32(r+20)==CP_DEBUG_BASE &&
     dbg_u32(r+24)==CP_DEBUG_SIZE && dbg_u32(r+28)==1)region=true;
 }
 if(!region)return DBG_BASELINE;
 /* Firmware gateway signature is verified before publishing an entry point. */
 static const uint8_t expected[8]={0x05,0x48,0x01,0x68,0x05,0x4a,0x91,0x42};
 if(memcmp((const void *)0x8041e938,expected,sizeof(expected)))return DBG_BASELINE;
 memset((void *)mailbox,0,sizeof(*mailbox));
 memcpy((void *)CP_AGENT_BASE,cp_agent_blob,sizeof(cp_agent_blob));
 clean((const void *)CP_AGENT_BASE,sizeof(cp_agent_blob));
 clean(mailbox,sizeof(*mailbox));
 mailbox->entry=CP_AGENT_BASE|1;clean(mailbox,32);dbg_barrier();
 mailbox->magic=CP_GATE_MAGIC;clean(mailbox,32);
 return DBG_OK;
}
static uint32_t cp_submit(uint32_t op,uint32_t a,uint32_t n,uint32_t w,uint32_t space,
 uint32_t arg,uint32_t generation,const uint8_t *input,uint32_t *accepted_sequence) {
 invalidate(mailbox,64);
 if(mailbox->magic!=CP_GATE_MAGIC || mailbox->abi!=DBG_VERSION)return DBG_NOT_READY;
 invalidate((const void *)&mailbox->response_seq,64);
 if(cp_pending && mailbox->response_seq!=cp_pending)return DBG_BUSY;
 cp_pending=0;
 if(input) {memcpy((void *)mailbox->data,input,n);clean((const void *)mailbox->data,n);}
 mailbox->command=op;mailbox->address=a;mailbox->length=n;mailbox->width=w;
 mailbox->space=space;mailbox->argument=arg;mailbox->generation=generation;
 clean((const void *)&mailbox->request_seq,64);dbg_barrier();
 if(++cp_seq==0)++cp_seq;
 mailbox->request_seq=cp_seq;clean((const void *)&mailbox->request_seq,64);cp_pending=cp_seq;
 *accepted_sequence=cp_seq;return DBG_OK;
}
static uint32_t cp_request(uint32_t op,uint32_t a,uint32_t n,uint32_t w,uint32_t space,
 uint32_t arg,uint32_t generation,const uint8_t *input,uint8_t *output,uint32_t *out_size) {
 *out_size=0;uint32_t submitted;
 uint32_t status=cp_submit(op,a,n,w,space,arg,generation,input,&submitted);
 if(status!=DBG_OK)return status;
 int64_t start=osiUpTime();
 while(osiUpTime()-start<3000) {
  invalidate((const void *)&mailbox->response_seq,64);
  if(mailbox->response_seq==submitted) {
   cp_pending=0;uint32_t size=mailbox->response_length;
   if(size>CP_TRANSFER_SIZE)return DBG_BAD_REQUEST;
   if(size && output) {invalidate((const void *)mailbox->data,size);memcpy(output,(const void *)mailbox->data,size);}
   *out_size=size;return mailbox->status;
  }
  iot_os_sleep(1);
 }
 return DBG_TIMEOUT;
}
static int ap_access(uint32_t a,uint32_t n,uint32_t width,uint32_t space,int write) {
 if(!n || n>CP_TRANSFER_SIZE || (width!=1 && width!=2 && width!=4) || a%width || n%width)return 0;
 if(space==DBG_RAM) {
  if(dbg_within(a,n,(uint32_t)test_ram,sizeof(test_ram)))return 1;
  if(dbg_within(a,n,0x80989f60,0x5760a0))return 1; /* AP .data/.bss/heap, excluding MMU tables and RAM code */
  /* Active APPIMG / transport / mailbox cannot be destroyed by generic writes. */
  if(!write && dbg_within(a,n,0x80000000,0x970000))return 1;
 }
 if(!write && space==DBG_FLASH && dbg_within(a,n,0x60000000,0x800000))return 1;
 if(!write && space==DBG_ROM && dbg_within(a,n,0x400a0000,0x28000))return 1;
 if(space==DBG_MMIO && width==4 && n==4 &&
    (dbg_within(a,n,0x22000000,0x1000)||dbg_within(a,n,0x25000000,0xc00000)))return 1;
 return 0;
}
#ifdef DBG_ENABLE_BW0_USB
/* Keep the monitor boundary identifiable while debugging the held CP service. */
__attribute__((noinline))
#endif
static uint32_t dispatch(uint32_t op,const uint8_t *p,uint32_t size,uint8_t *out,uint32_t *out_size) {
 uint32_t dummy=0;*out_size=0;
#ifdef DBG_ENABLE_BW0_USB
 if(op==SDR_BW0_STATUS || op==SDR_BW0_START || op==SDR_BW0_STOP || op==SDR_BW0_CONFIG || op==SDR_BW0_RECOVERY_STATUS || op==SDR_BW0_KEEPALIVE || op==SDR_BW0_SCHEDULER || op==SDR_BW0_SEGMENTS || op==SDR_BW0_SCRATCH_DROPS || op==SDR_BW0_FEM_OVERRIDE)
  return sdr_bw0_control(op,p,size,out,out_size);
 if(sdr_bw0_busy() && op!=DBG_INFO && op!=DBG_STATUS && op!=SDR_RAW_STATUS)
  return DBG_BUSY;
#endif
#ifdef DBG_ENABLE_RAW_USB
 if(op==SDR_RAW_STATUS || op==SDR_RAW_START || op==SDR_RAW_STOP)
  return sdr_raw_control(op,p,size,out,out_size);
#endif
 if(op==DBG_INFO) {
  if(size)return DBG_BAD_REQUEST;
  invalidate(mailbox,64);
  int n=snprintf((char *)out,DBG_MAX_PAYLOAD,
   "{\"protocol\":1,\"firmware\":\"" DBG_FIRMWARE_NAME "\",\"cp_baseline_sha256\":\"%s\","
   "\"cp_agent_ready\":%s,\"cp_debug_base\":%lu,\"cp_slot_size\":%lu,\"ap_test_ram\":%lu,"
   "\"ap_test_size\":4096,\"cp_test_ram\":%lu,\"bcpu_rom_cp_address\":1074397184,"
   "\"bcpu_rom_size\":163840,\"max_transfer\":1024,\"vendor_text_patch\":false,"
   "\"iq_capture\":false,\"cp_reload\":false,\"ap_precise_abort_recovery\":true,\"bus_stall_recovery\":false" DBG_ASYNC_INFO DBG_STREAM_INFO DBG_STREAM_PROFILE_INFO DBG_BULK_INFO DBG_RX_SERVICE_INFO DBG_RAW_INFO DBG_BW0_INFO "}",
   CP_BASELINE_SHA,mailbox->abi==DBG_VERSION?"true":"false",(unsigned long)CP_DEBUG_BASE,
   (unsigned long)CP_SLOT_SIZE,(unsigned long)test_ram,(unsigned long)CP_SCRATCH DBG_RX_SERVICE_VALUES);
  if(n<0 || (unsigned)n>=DBG_MAX_PAYLOAD)return DBG_BAD_REQUEST;*out_size=n;return DBG_OK;
 }
 if(op==DBG_STATUS) {
  if(size)return DBG_BAD_REQUEST;invalidate(mailbox,192);
  if(cp_pending && mailbox->response_seq==cp_pending)cp_pending=0;
  uint32_t fields[]={mailbox->abi,mailbox->heartbeat,mailbox->active_entry,mailbox->active_generation,
   mailbox->previous_entry,mailbox->last_result,mailbox->request_seq,mailbox->response_seq,mailbox->status,cp_pending};
  for(unsigned i=0;i<10;i++)dbg_put32(out+i*4,fields[i]);*out_size=40;return DBG_OK;
 }
 if(op==DBG_READ || op==DBG_WRITE) {
  if(size<16)return DBG_BAD_REQUEST;
  uint32_t core=dbg_u32(p),a=dbg_u32(p+4),n=dbg_u32(p+8),w=p[12],space=p[13];
  if(p[14] || p[15] || !n || n>CP_TRANSFER_SIZE || size!=(op==DBG_WRITE?16+n:16))return DBG_BAD_REQUEST;
  if(core==DBG_BCPU)return DBG_UNSUPPORTED; /* use CP ROM window, not a fictitious local alias */
  if(core==DBG_CP)return cp_request(op==DBG_READ?CP_READ:CP_WRITE,a,n,w,space,0,0,
   op==DBG_WRITE?p+16:NULL,out,out_size);
  if(core!=DBG_AP || !ap_access(a,n,w,space,op==DBG_WRITE))return DBG_RANGE;
  if(space==DBG_RAM && op==DBG_READ)invalidate((const void *)a,n);
  for(uint32_t i=0;i<n;i+=w) {
   if(op==DBG_READ) {
    uint32_t v;if(!debug_load_word(a+i,w,&v))return DBG_ACCESS;
    for(uint32_t j=0;j<w;j++)out[i+j]=(uint8_t)(v>>(8*j));
   } else {
    uint32_t v=0;for(uint32_t j=0;j<w;j++)v|=(uint32_t)p[16+i+j]<<(8*j);
    if(!debug_store_word(a+i,w,v))return DBG_ACCESS;
   }
  }
  if(op==DBG_WRITE && space==DBG_RAM)clean((const void *)a,n);
  *out_size=op==DBG_READ?n:0;return DBG_OK;
 }
 if(op==DBG_UPLOAD_BEGIN) {
  /* size, entry offset (Thumb), generation, baseline SHA256, payload SHA256 */
  if(size!=76)return DBG_BAD_REQUEST;
  static const uint8_t baseline[32]={0xbd,0x25,0x92,0x3a,0xa2,0xfd,0x2c,0xde,0x32,0xfa,0xfe,0x59,0x30,0x5b,0x66,0x55,0xa7,0x96,0x45,0xad,0x7f,0xf4,0x47,0xb7,0x4f,0x0f,0xfd,0x42,0x86,0xa0,0x20,0xd1};
  if(memcmp(p+12,baseline,32))return DBG_BASELINE;
  uint32_t n=dbg_u32(p),entry=dbg_u32(p+4);
  if(n<2 || n>CP_SLOT_SIZE || !(entry&1) || (entry&~1u)>n-2)return DBG_RANGE;
  package.size=n;package.entry_offset=entry;package.generation=dbg_u32(p+8);package.received=0;
  memcpy(package.hash,p+44,32);package.open=true;package.ready=false;return DBG_OK;
 }
 if(op==DBG_UPLOAD_DATA) {
  if(size<=4 || !package.open)return DBG_BAD_REQUEST;
  uint32_t off=dbg_u32(p),n=size-4;
  if(off!=package.received)return DBG_SEQUENCE;
  if(n>package.size-package.received)return DBG_RANGE;
  memcpy(upload+off,p+4,n);package.received+=n;return DBG_OK;
 }
 if(op==DBG_UPLOAD_END) {
  if(size || !package.open || package.received!=package.size)return DBG_SEQUENCE;
  uint8_t digest[32];dbg_sha256(upload,package.size,digest);package.open=false;
  if(memcmp(digest,package.hash,32))return DBG_DIGEST;
  package.ready=true;return DBG_OK;
 }
 if(op==DBG_ACTIVATE) {
  if(size || !package.ready)return DBG_NOT_READY;
  invalidate(mailbox,192);
  if(cp_pending && mailbox->response_seq!=cp_pending)return DBG_BUSY;
  uint32_t slot=0,slots[]={CP_SLOT0,CP_SLOT1,CP_SLOT2};
  for(unsigned i=0;i<3;i++) {
   if(!dbg_within(mailbox->active_entry&~1u,2,slots[i],CP_SLOT_SIZE) &&
      !dbg_within(mailbox->previous_entry&~1u,2,slots[i],CP_SLOT_SIZE)) {slot=slots[i];break;}
  }
  if(!slot)return DBG_BUSY;
  /* Keep current and rollback modules intact until CP acknowledges activation. */
  memcpy((void *)slot,upload,package.size);clean((const void *)slot,package.size);
  uint32_t r=cp_request(CP_ACTIVATE,slot+package.entry_offset,0,0,0,0,package.generation,NULL,out,&dummy);
  if(r==DBG_OK)package.ready=false;
  return r;
 }
 if(op==DBG_ROLLBACK) {
  if(size)return DBG_BAD_REQUEST;
  uint32_t r=cp_request(CP_ROLLBACK,0,0,0,0,0,0,NULL,out,&dummy);
  return r;
 }
 if(op==DBG_CALL) {
  if(size!=4)return DBG_BAD_REQUEST;
  return cp_request(CP_CALL,0,0,0,0,dbg_u32(p),0,NULL,out,out_size);
 }
#ifdef DBG_ENABLE_ASYNC_CALL
 if(op==DBG_CALL_ASYNC) {
  if(size!=4)return DBG_BAD_REQUEST;
  uint32_t accepted;
  uint32_t result=cp_submit(CP_CALL,0,0,0,0,dbg_u32(p),0,NULL,&accepted);
  if(result==DBG_OK){dbg_put32(out,accepted);*out_size=4;}
  return result;
 }
#endif
 return DBG_UNSUPPORTED;
}
#ifdef DBG_ENABLE_BW0_USB
#include "../sdr_receiver/rf_profile.h"
static uint32_t bw0_prepare(void *context,const uint8_t *resident,uint32_t resident_bytes,
 const uint8_t *control,uint32_t control_bytes,uint32_t entry_offset,uint32_t generation,
 uint32_t channel,uint32_t gain,uint32_t raw_frequency,uint32_t bandwidth_index) {
 (void)context;
 if(!raw_frequency || !terminal_profile_raw_valid(channel,raw_frequency) || gain>124u || bandwidth_index>SDR_BW0_MAX_BW)
  return DBG_RANGE;
 if(!resident || !control || resident_bytes>0x4000u || !resident_bytes || !control_bytes ||
    control_bytes<2u || control_bytes>CP_SLOT_SIZE || !(entry_offset&1u) || (entry_offset&~1u)>control_bytes-2u)
  return DBG_RANGE;
 invalidate(mailbox,192);
 if(mailbox->abi!=DBG_VERSION) return DBG_NOT_READY;
 if(mailbox->request_seq!=mailbox->response_seq || mailbox->active_entry) return DBG_BUSY;
 /* Fresh, exclusively reserved CP region. Never overwrite a live module. */
 memcpy((void *)CP_SCRATCH,resident,resident_bytes); clean((void *)CP_SCRATCH,resident_bytes);
 memcpy((void *)CP_SLOT0,control,control_bytes); clean((void *)CP_SLOT0,control_bytes);
 uint8_t response[4];uint32_t response_bytes=0;
 uint32_t result=cp_request(CP_ACTIVATE,CP_SLOT0+entry_offset,0,0,0,0,generation,NULL,response,&response_bytes);
 if(result!=DBG_OK)return result;
 result=cp_request(CP_CALL,0,0,0,0,0x1001u,0,NULL,response,&response_bytes);
 if(result!=DBG_OK)return result;
 if(response_bytes!=4 || dbg_u32(response)!=7u)return DBG_BASELINE;
 uint8_t parameters[12]; dbg_put32(parameters,channel); dbg_put32(parameters+4,bandwidth_index); dbg_put32(parameters+8,gain);
 result=cp_request(CP_WRITE,0x8097f90cu,12,4,DBG_RAM,0,0,parameters,response,&response_bytes);
 if(result!=DBG_OK)return result;
 dbg_put32(parameters,raw_frequency);
 return cp_request(CP_WRITE,0x8097f924u,4,4,DBG_RAM,0,0,parameters,response,&response_bytes);
}
static int bw0_launch(void *context) {
 (void)context;uint32_t accepted;
 return cp_submit(CP_CALL,0,0,0,0,0x100bu,0,NULL,&accepted)==DBG_OK?1:0;
}
#endif
static bool send_all(transport_t *t) {
 uint32_t off=0;int64_t start=osiUpTime();
 while(off<t->tx_size && osiUpTime()-start<3000) {
  uint32_t n=iot_uart_write(t->port,t->tx+off,t->tx_size-off);
  if(n>t->tx_size-off)return false;off+=n;if(!n)iot_os_sleep(1);
 }
 return off==t->tx_size;
}
static void encode_reply(transport_t *t,uint32_t seq,uint32_t op,uint32_t status,uint32_t out_size) {
 dbg_put32(t->tx,DBG_MAGIC);t->tx[4]=DBG_VERSION;t->tx[5]=op|0x80;
 t->tx[6]=out_size;t->tx[7]=out_size>>8;dbg_put32(t->tx+8,seq);dbg_put32(t->tx+12,status);
 uint32_t hash=dbg_crc_update(~0u,t->tx,16);hash=dbg_crc_update(hash,t->tx+FRAME_HEADER,out_size);
 dbg_put32(t->tx+16,~hash);t->tx_size=FRAME_HEADER+out_size;
}
#ifdef DBG_ENABLE_BULK
static void send_bulk(transport_t *t,uint32_t seq) {
 for(uint32_t offset=0;offset<t->bulk_size;) {
  uint32_t n=t->bulk_size-offset;if(n>BULK_CHUNK)n=BULK_CHUNK;
  uint8_t *out=t->tx+FRAME_HEADER;
  dbg_put32(out,offset);dbg_put32(out+4,t->bulk_size);dbg_put32(out+8,n);
  dbg_put32(out+12,offset+n==t->bulk_size?1u:0u);
  memcpy(out+BULK_META,t->bulk+offset,n);
  encode_reply(t,seq,DBG_BULK_READ,DBG_OK,BULK_META+n);
  if(!send_all(t))return;
  offset+=n;
 }
}
static uint32_t prepare_bulk(transport_t *t,const uint8_t *p,uint32_t size) {
 t->have_bulk=false;
 if(size!=16)return DBG_BAD_REQUEST;
 uint32_t core=dbg_u32(p),a=dbg_u32(p+4),n=dbg_u32(p+8),w=p[12],space=p[13];
 if(core!=DBG_AP || space!=DBG_RAM)return DBG_UNSUPPORTED;
 if(!n || n>BULK_LIMIT || (w!=1 && w!=2 && w!=4) || a%w || n%w ||
    (uint64_t)a+n>0x100000000ULL)return DBG_RANGE;
 /* Keep the existing read-only ranges. No MMIO, ROM, CP mailbox or writes. */
 for(uint32_t offset=0;offset<n;offset+=CP_TRANSFER_SIZE) {
  uint32_t count=n-offset;if(count>CP_TRANSFER_SIZE)count=CP_TRANSFER_SIZE;
  if(!ap_access(a+offset,count,w,space,0))return DBG_RANGE;
 }
 invalidate((const void *)a,n);
 for(uint32_t offset=0;offset<n;offset+=w) {
  uint32_t value;if(!debug_load_word(a+offset,w,&value))return DBG_ACCESS;
  for(uint32_t byte=0;byte<w;byte++)t->bulk[offset+byte]=value>>(byte*8);
 }
 t->bulk_size=n;t->have_bulk=true;return DBG_OK;
}
#endif
#ifdef DBG_ENABLE_RX_STREAM
#include "ap_rxcapt_stream.inc"
#ifdef DBG_ENABLE_RX_REUSE
#include "ap_rxcapt_reuse.inc"
#endif
#endif
static void handle_frame(transport_t *t,uint32_t seq,uint32_t op,uint32_t crc,uint32_t n) {
 if(t->have_reply && seq==t->last_seq) {
  if(crc==t->last_crc && op==t->last_op) {
#ifdef DBG_ENABLE_BULK
   if(op==DBG_BULK_READ && t->have_bulk)send_bulk(t,seq);else
#endif
   send_all(t);
  }
#ifdef DBG_ENABLE_RX_REUSE
  else if(t->last_op==RXR_OPERATION && t->tx_size<=132u) {
   /* Reject a sequence collision without replacing the cached final END. */
   uint8_t saved[132];uint32_t size=t->tx_size;memcpy(saved,t->tx,size);
   encode_reply(t,seq,op,DBG_SEQUENCE,0);send_all(t);
   memcpy(t->tx,saved,size);t->tx_size=size;
  }
#endif
  return;
 }
#ifdef DBG_ENABLE_BULK
 t->have_bulk=false;
#ifdef DBG_ENABLE_RX_STREAM
#ifdef DBG_ENABLE_RX_REUSE
 if(op==RXR_OPERATION) {
  rxr_request_t request;uint32_t status=rxr_preflight(t,t->rx+FRAME_HEADER,n,&request);
  t->last_seq=seq;t->last_op=op;t->last_crc=crc;t->have_reply=true;
  if(status==DBG_OK)rxr_run(t,seq,&request);
  else {encode_reply(t,seq,op,status,0);send_all(t);}
  return;
 }
#endif
 if(op==DBG_RX_STREAM) {
  uint32_t duration,status=rxs_preflight(t,t->rx+FRAME_HEADER,n,&duration);
  t->last_seq=seq;t->last_op=op;t->last_crc=crc;t->have_reply=true;
  if(status==DBG_OK)rxs_run(t,seq,duration);
  else {encode_reply(t,seq,op,status,0);send_all(t);}
  return;
 }
#endif
 if(op==DBG_BULK_READ) {
  uint32_t status=prepare_bulk(t,t->rx+FRAME_HEADER,n);
  t->last_seq=seq;t->last_op=op;t->last_crc=crc;t->have_reply=true;
  if(status==DBG_OK)send_bulk(t,seq);
  else {encode_reply(t,seq,op,status,0);send_all(t);}
  return;
 }
#endif
 uint32_t out_size,status=dispatch(op,t->rx+FRAME_HEADER,n,t->tx+FRAME_HEADER,&out_size);
 encode_reply(t,seq,op,status,out_size);
 t->last_seq=seq;t->last_op=op;t->last_crc=crc;t->have_reply=true;send_all(t);
}
static void receive_byte(transport_t *t,uint8_t byte) {
 if(t->used>=sizeof(t->rx))t->used=0;
 t->rx[t->used++]=byte;
 while(t->used>=4 && dbg_u32(t->rx)!=DBG_MAGIC) {memmove(t->rx,t->rx+1,--t->used);}
 if(t->used<FRAME_HEADER)return;
 uint32_t n=t->rx[6]|((uint32_t)t->rx[7]<<8);
 if(t->rx[4]!=DBG_VERSION || t->rx[5]&0x80 || n>DBG_MAX_PAYLOAD || dbg_u32(t->rx+12)) {t->used=0;return;}
 if(t->used<FRAME_HEADER+n)return;
 uint32_t crc=dbg_crc_update(~0u,t->rx,16);crc=dbg_crc_update(crc,t->rx+FRAME_HEADER,n);
 if(~crc==dbg_u32(t->rx+16))handle_frame(t,dbg_u32(t->rx+8),t->rx[5],~crc,n);
 t->used=0;
}
static void monitor_task(void *arg) {
 (void)arg;
 int install_status=cp_install();
 (void)install_status;
#ifdef DBG_ENABLE_RAW_USB
 (void)sdr_raw_install();
#endif
#ifdef DBG_ENABLE_BW0_USB
 if(install_status==DBG_OK)
  (void)sdr_bw0_install((volatile uint32_t *)test_ram,(struct sdr_bw0_backend){0,bw0_prepare,bw0_launch});
#endif
#ifdef DBG_RECEIVER_SERVICE
 receiver_resident_status=install_status==DBG_OK?preload_receiver_resident():(uint32_t)install_status;
#endif
 T_AMOPENAT_UART_PARAM cfg;memset(&cfg,0,sizeof(cfg));
 cfg.baud=OPENAT_UART_BAUD_115200;cfg.dataBits=8;cfg.stopBits=1;
 cfg.parity=OPENAT_UART_NO_PARITY;cfg.flowControl=OPENAT_UART_FLOWCONTROL_NONE;
 channels[0].port=OPENAT_UART_USB;channels[1].port=OPENAT_UART_2;
 bool opened[2]={iot_uart_open(channels[0].port,&cfg),false};
#if !defined(DBG_ENABLE_RX_STREAM) && !defined(DBG_ENABLE_RAW_USB)
 opened[1]=iot_uart_open(channels[1].port,&cfg);
#endif
 uint8_t buf[128];
 for(;;) {
  for(unsigned ch=0;ch<2;ch++) {
   if(!opened[ch])continue;
   transport_t *t=&channels[ch];
   if(t->used && osiUpTime()-t->last_byte>1500)t->used=0;
   uint32_t n=iot_uart_read(t->port,buf,sizeof(buf),5);
   if(n>sizeof(buf))n=0;
   for(uint32_t i=0;i<n;i++)receive_byte(t,buf[i]);
   if(n)t->last_byte=osiUpTime();
  }
  iot_os_sleep(1);
 }
}
int appimg_enter(void *arg) {
 (void)arg;return iot_os_create_task(monitor_task,NULL,8192,1,OPENAT_OS_CREATE_DEFAULT,"debug_monitor")?0:-1;
}
void appimg_exit(void) {}
