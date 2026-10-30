/* Reusable receiver entry. No CP submission, activation, RF MMIO or reset.
 * Only the existing RAM mailbox and reviewed observation/ring windows are used. */
#include "rxcapt_reuse_protocol.h"

static uint32_t rxr_preflight(transport_t *t,const uint8_t *p,uint32_t n,rxr_request_t *request) {
 if(t!=&channels[0])return DBG_UNSUPPORTED;
 if(n!=24u || dbg_u32(p)!=RXR_VERSION || dbg_u32(p+8u)!=RXS_GENERATION)return DBG_BAD_REQUEST;
 memset(request,0,sizeof(*request));request->duration=dbg_u32(p+4u);
 request->last_command=dbg_u32(p+12u);request->raw=dbg_u32(p+16u);request->stop_pairs=dbg_u32(p+20u);
 if(request->duration<1u || request->duration>180000u || !request->last_command ||
    request->last_command>RXR_SEQUENCE_LIMIT || request->stop_pairs>200000u ||
    (request->raw!=RXR_ANCHOR_RAW && request->raw!=RXR_ANCHOR_RAW+1000u))return DBG_RANGE;
 invalidate(mailbox,192u);
 if(mailbox->active_generation!=RXS_GENERATION ||
    !dbg_within(mailbox->active_entry&~1u,2u,CP_SLOT0,3u*CP_SLOT_SIZE))return DBG_NOT_READY;
 if(!cp_pending || mailbox->request_seq!=cp_pending || mailbox->response_seq==cp_pending ||
    mailbox->command!=CP_CALL || mailbox->argument!=0x100bu)return DBG_BUSY;
 uint32_t progress[16],second[16],state[30],reply[8],frequency[16],trace[24];
 if(!rxs_read_words(RXS_PROGRESS_ADDRESS,progress,16u) ||
    !rxs_read_words(RXS_PROGRESS_ADDRESS,second,16u) ||
    !rxs_read_words((uint32_t)test_ram+32u,reply,8u) ||
    !rxs_read_words(RXR_FREQUENCY_ADDRESS,frequency,16u) ||
    !rxs_read_words(RXR_TRACE_ADDRESS,trace,24u))return DBG_ACCESS;
 if(memcmp(progress,second,sizeof(progress)) || progress[0]!=RXS_PROGRESS_MAGIC ||
    progress[1]!=RXS_GENERATION || (progress[2]&1u) || progress[3]!=30u || progress[4])return DBG_NOT_READY;
 if(!rxs_state(state) || !(state[3]&1u) || state[6]!=state[7] ||
    (state[8]!=1u && state[8]!=2u))return DBG_NOT_READY;
 for(unsigned i=0;i<RXS_SLOTS;i++)if(state[10u+i*3u]&7u)return DBG_NOT_READY;
 if(reply[0]!=RXS_SERVICE_MAGIC || reply[1]!=RXS_GENERATION ||
    reply[2]!=request->last_command || reply[7]!=reply[2] || reply[3]!=10u || reply[4] ||
    reply[5]!=state[6] || reply[6]!=state[8])return DBG_SEQUENCE;
 if(frequency[0]!=0x46525131u || frequency[1]!=RXS_GENERATION || !frequency[2] || frequency[2]>=0x7fffffffu ||
    frequency[3]==request->raw || trace[0]!=0x324e5446u || trace[1]!=1u ||
    trace[2]!=frequency[2] || trace[3]!=frequency[3] || trace[4]!=1u || trace[6] ||
    trace[23]!=trace[2]-1u)return DBG_NOT_READY;
 if(frequency[3]!=RXR_ANCHOR_RAW && frequency[3]!=RXR_ANCHOR_RAW+1000u)return DBG_RANGE;
#ifdef DBG_ENABLE_RX_STREAM_BURST
 if(dbg_u32(test_ram+192u)>1u)return DBG_RANGE;
#endif
 request->epoch=frequency[2]+1u;request->cp_sequence=cp_pending;
 request->heartbeat=mailbox->heartbeat;request->response_sequence=mailbox->response_seq;
 return DBG_OK;
}

static void rxr_run(transport_t *t,uint32_t sequence,const rxr_request_t *request) {
 rxs_context_t c;memset(&c,0,sizeof(c));c.command=request->last_command;
 c.cp_sequence=request->cp_sequence;c.wire_operation=RXR_OPERATION;c.started=osiUpTime();
#ifdef DBG_ENABLE_RX_STREAM_FAST
 c.started_us=osiUpTimeUS();
#endif
 uint32_t reply[8]={0},state[30],progress[16];
 uint32_t result=rxs_command(&c,9u,request->raw,reply);
 if(result==DBG_OK && (reply[5]!=request->raw || reply[6]!=request->epoch))result=DBG_SEQUENCE;
 if(result!=DBG_OK){encode_reply(t,sequence,RXR_OPERATION,result,0);send_all(t);return;}
 c.started=osiUpTime();
 uint8_t identity[16];const uint32_t words[4]={request->epoch,request->raw,c.command,RXR_VERSION};
 for(unsigned i=0;i<4u;i++)dbg_put32(identity+4u*i,words[i]);
 if(!rxs_packet(t,sequence,&c,RXS_ACCEPT,0u,0u,0u,0u,c.cp_sequence,identity,sizeof(identity),DBG_OK))result=DBG_TIMEOUT;
 bool stop_sent=false,draining=false;int64_t stop_time=0;uint32_t progress_polls=0u;
 while(result==DBG_OK && osiUpTime()-c.started<(int64_t)request->duration+RXS_INITIALIZE_TIMEOUT_MS+RXS_DRAIN_TIMEOUT_MS) {
  if(!c.initialized && osiUpTime()-c.started>RXS_INITIALIZE_TIMEOUT_MS){result=DBG_TIMEOUT;break;}
  if(!c.initialized || !(progress_polls++&63u)) {
   if(!rxs_read_words(RXS_PROGRESS_ADDRESS,progress,16u)){result=DBG_ACCESS;break;}
   if(progress[0]!=RXS_PROGRESS_MAGIC || progress[1]!=RXS_GENERATION || (progress[2]&1u))continue;
   c.phase=progress[3];c.error=progress[4];
   if(c.phase>=31u || c.error){result=DBG_NOT_READY;break;}
  }
  if(!c.initialized && c.phase<27u)continue;
  if(!rxs_state(state))continue;
  c.initialized=true;c.flags=state[3];c.reason=state[8];
  if((state[3]&1u) && !draining){draining=true;stop_time=osiUpTime();}
  if(!stop_sent && !(state[3]&1u) &&
     (osiUpTime()-c.started>=request->duration || state[6]>=200000u ||
      (request->stop_pairs && state[6]>=request->stop_pairs))) {
   result=rxs_command(&c,7u,0u,reply);stop_sent=result==DBG_OK;draining=stop_sent;stop_time=osiUpTime();continue;
  }
  if(draining && osiUpTime()-stop_time>RXS_DRAIN_TIMEOUT_MS){result=DBG_TIMEOUT;break;}
  uint32_t block=state[7];
  if(block!=state[6]) {
   uint32_t row=9u+(block%RXS_SLOTS)*3u;
   if(block!=c.blocks || state[row]!=block || state[row+1u]!=0u || state[row+2u]!=3u){result=DBG_SEQUENCE;break;}
   result=rxs_command(&c,5u,block,reply);
   if(result!=DBG_OK)break;
   if(reply[5]!=block || reply[6]!=block%RXS_SLOTS){result=DBG_SEQUENCE;break;}
   result=rxs_copy_pair(block,t->bulk);if(result!=DBG_OK)break;
   /* Complete DATA and HEAD are staged before releasing CP's ring slot. */
   result=rxs_command(&c,6u,block,reply);if(result!=DBG_OK)break;
   if(reply[5]!=block || reply[6]!=block+1u){result=DBG_SEQUENCE;break;}
   if(!rxs_send_pair(t,sequence,&c,block)){result=DBG_TIMEOUT;break;}
   ++c.blocks;continue;
  }
  uint32_t active=0u;for(unsigned i=0;i<RXS_SLOTS;i++)active|=state[10u+i*3u]&3u;
  if((state[3]&1u) && !active) {
   result=rxs_command(&c,10u,0u,c.park_response);
   if(result==DBG_OK) {
    c.parked=true;c.reason=c.park_response[6];
    if(c.park_response[5]!=c.blocks)result=DBG_SEQUENCE;
   }
   break;
  }
 }
 if(!c.parked) {
  if(result==DBG_OK)result=DBG_TIMEOUT;
  /* Never guess the next mailbox sequence after an ambiguous command error.
     When our last accepted sequence is still current, STOP is best effort. */
  uint32_t observed[8];
  if(rxs_read_words((uint32_t)test_ram+32u,observed,8u) && observed[2]==c.command && observed[7]==c.command)
   (void)rxs_command(&c,7u,0u,reply);
 }
 if(rxs_read_words(RXS_PROGRESS_ADDRESS,progress,16u)){c.phase=progress[3];c.error=progress[4];}
 invalidate(mailbox,192u);
 if(mailbox->request_seq!=request->cp_sequence || mailbox->response_seq!=request->response_sequence ||
    mailbox->heartbeat!=request->heartbeat || mailbox->active_generation!=RXS_GENERATION)result=DBG_SEQUENCE;
 if(result==DBG_OK && (!c.parked || (c.reason!=1u && c.reason!=2u) || c.phase!=30u || c.error))result=DBG_NOT_READY;
 uint32_t counters[20]={c.blocks,c.blocks*RXS_DATA_BYTES,c.blocks*RXS_HEAD_BYTES,
  (uint32_t)(osiUpTime()-c.started),c.cp_sequence,c.parked?1u:0u,c.phase,c.error};
 for(unsigned i=0;i<8u;i++)counters[8u+i]=c.park_response[i];
 counters[16]=request->epoch;counters[17]=request->raw;counters[18]=c.command;counters[19]=RXR_VERSION;
 uint8_t encoded[80];for(unsigned i=0;i<20u;i++)dbg_put32(encoded+4u*i,counters[i]);
 (void)rxs_packet(t,sequence,&c,RXS_END,c.blocks,0u,0u,c.flags,c.reason,encoded,sizeof(encoded),result);
}
