/* Included after AP memory/cache/framing helpers. Only fixed reviewed RXCAPT
 * buffers and the AP-owned test-RAM request line are touched. No arbitrary
 * address or CP function is accepted by this operation. */
#include "rxcapt_stream_protocol.h"

typedef struct {
 uint32_t command,cp_sequence,packet,blocks,flags,reason,phase,error;
#ifdef DBG_ENABLE_RX_REUSE
 uint32_t wire_operation;
#endif
 uint32_t park_response[8];
 bool initialized,parked;
 int64_t started;
#ifdef DBG_ENABLE_RX_STREAM_FAST
 uint32_t profile[32];
 int64_t started_us;
#endif
} rxs_context_t;

#ifdef DBG_ENABLE_RX_STREAM_FAST
/* Aggregate microseconds, one trace per run, in unused AP test RAM after the
 * separate 64-byte AP/CP mailbox. Command timing counts completed commands;
 * copy/send/state timing also counts failed attempts. */
static void rxs_profile_add(rxs_context_t *c,unsigned stage,int64_t start) {
 uint32_t elapsed=(uint32_t)(osiUpTimeUS()-start);
 c->profile[stage]+=elapsed;++c->profile[stage+7u];
 if(stage==11u && elapsed>c->profile[23])c->profile[23]=elapsed;
 if(stage==14u && elapsed>c->profile[24])c->profile[24]=elapsed;
}
#define RXS_TIME_START int64_t prof_started=osiUpTimeUS()
#define RXS_TIME_ADD(c,stage) rxs_profile_add(c,stage,prof_started)
#else
#define RXS_TIME_START ((void)0)
#define RXS_TIME_ADD(c,stage) ((void)0)
#endif

static bool rxs_copy_words(uint32_t address,void *out,uint32_t count) {
#ifdef DBG_ENABLE_RX_STREAM_BURST
 if(dbg_u32(test_ram+192u)==0u)return debug_copy_words_burst(address,out,count)!=0;
#endif
 return debug_copy_words(address,out,count)!=0;
}

static bool rxs_read_words(uint32_t address,uint32_t *out,uint32_t count) {
 invalidate((const void *)address,count*4u);
#ifdef DBG_ENABLE_RX_STREAM_FAST
 return rxs_copy_words(address,out,count);
#else
 for(uint32_t i=0;i<count;i++)if(!debug_load_word(address+i*4u,4u,out+i))return false;
 return true;
#endif
}

static bool rxs_state(uint32_t out[30]) {
 uint32_t second[30];
 if(!rxs_read_words(RXS_STATE_ADDRESS,out,30u) ||
    !rxs_read_words(RXS_STATE_ADDRESS,second,30u) || memcmp(out,second,sizeof(second)))return false;
 return out[0]==RXS_STATE_MAGIC && out[1]==RXS_VERSION && out[2]==RXS_SLOTS &&
        (uint32_t)(out[6]-out[7])<=RXS_SLOTS;
}

static uint32_t rxs_command(rxs_context_t *c,uint32_t operation,uint32_t block,uint32_t reply[8]) {
 RXS_TIME_START;
 uint32_t seq=c->command+1u;
 uint32_t request[8]={RXS_SERVICE_MAGIC,RXS_GENERATION,seq,operation,c->command,block,~seq,seq};
 memcpy(test_ram,request,sizeof(request));clean(test_ram,32u);
 int64_t started=osiUpTime();
 while(osiUpTime()-started<RXS_COMMAND_TIMEOUT_MS) {
  if(!rxs_read_words((uint32_t)test_ram+32u,reply,8u))return DBG_ACCESS;
  if(reply[0]!=RXS_SERVICE_MAGIC || reply[1]!=RXS_GENERATION ||
     reply[2]!=seq || reply[7]!=seq)continue;
  if(reply[3]==4u && reply[4])return DBG_SEQUENCE;
  if(reply[3]!=(operation==8u?3u:operation) || reply[4])continue;
  c->command=seq;
  RXS_TIME_ADD(c,operation==5u?10u:operation==6u?12u:15u);
  return DBG_OK;
 }
 return DBG_TIMEOUT;
}

static bool rxs_packet(transport_t *t,uint32_t wire_sequence,rxs_context_t *c,
 uint32_t kind,uint32_t block,uint32_t offset,uint32_t total,uint32_t flags,
 uint32_t auxiliary,const uint8_t *data,uint32_t size,uint32_t status) {
 uint8_t *p=t->tx+FRAME_HEADER;
 uint32_t words[8]={RXS_MAGIC,kind,c->packet++,block,offset,total,flags,auxiliary};
 for(unsigned i=0;i<8;i++)dbg_put32(p+i*4u,words[i]);
 if(size)memcpy(p+RXS_HEADER_BYTES,data,size);
 RXS_TIME_START;
 uint32_t operation=DBG_RX_STREAM;
#ifdef DBG_ENABLE_RX_REUSE
 if(c->wire_operation)operation=c->wire_operation;
#endif
 encode_reply(t,wire_sequence,operation,status,RXS_HEADER_BYTES+size);
 RXS_TIME_ADD(c,13u);
#ifdef DBG_ENABLE_RX_STREAM_FAST
 prof_started=osiUpTimeUS();
#endif
 bool sent=send_all(t);RXS_TIME_ADD(c,14u);return sent;
}

static uint32_t rxs_copy_pair(uint32_t block,uint8_t *destination) {
 uint32_t slot=block%RXS_SLOTS;
 const uint32_t addresses[2]={RXS_DATA_ADDRESS+slot*RXS_DATA_BYTES,
                             RXS_HEAD_ADDRESS+slot*RXS_HEAD_BYTES};
 const uint32_t lengths[2]={RXS_DATA_BYTES,RXS_HEAD_BYTES};
 uint32_t output=0;
 for(unsigned region=0;region<2;region++) {
  invalidate((const void *)addresses[region],lengths[region]);
#ifdef DBG_ENABLE_RX_STREAM_FAST
  if(!rxs_copy_words(addresses[region],destination+output,lengths[region]/4u))return DBG_ACCESS;
  output+=lengths[region];
#else
  for(uint32_t i=0;i<lengths[region];i+=4u) {
   uint32_t value;if(!debug_load_word(addresses[region]+i,4u,&value))return DBG_ACCESS;
   dbg_put32(destination+output,value);output+=4u;
  }
#endif
 }
 return DBG_OK;
}

static bool rxs_send_pair(transport_t *t,uint32_t sequence,rxs_context_t *c,uint32_t block) {
 for(uint32_t offset=0;offset<RXS_PAIR_BYTES;) {
  uint32_t size=RXS_PAIR_BYTES-offset;
  if(size>DBG_MAX_PAYLOAD-RXS_HEADER_BYTES)size=DBG_MAX_PAYLOAD-RXS_HEADER_BYTES;
  if(!rxs_packet(t,sequence,c,RXS_BLOCK,block,offset,RXS_PAIR_BYTES,
      offset+size==RXS_PAIR_BYTES?1u:0u,RXS_HEAD_BYTES,t->bulk+offset,size,DBG_OK))return false;
  offset+=size;
 }
 return true;
}

static uint32_t rxs_preflight(transport_t *t,const uint8_t *p,uint32_t size,uint32_t *duration) {
 if(t!=&channels[0])return DBG_UNSUPPORTED;
 if(size!=12u || dbg_u32(p)!=RXS_VERSION || dbg_u32(p+8)!=RXS_GENERATION)return DBG_BAD_REQUEST;
 *duration=dbg_u32(p+4);
 if(*duration<1000u || *duration>180000u)return DBG_RANGE;
 invalidate(mailbox,192u);
 if(mailbox->active_generation!=RXS_GENERATION ||
    !dbg_within(mailbox->active_entry&~1u,2u,CP_SLOT0,3u*CP_SLOT_SIZE))return DBG_NOT_READY;
 if(cp_pending && mailbox->response_seq!=cp_pending)return DBG_BUSY;
 uint32_t progress[16];
 if(!rxs_read_words(RXS_PROGRESS_ADDRESS,progress,16u))return DBG_ACCESS;
 if(progress[0]!=RXS_PROGRESS_MAGIC || progress[1]!=RXS_GENERATION ||
    (progress[2]&1u) || progress[4] || (progress[3]!=1u && progress[3]!=10u))return DBG_NOT_READY;
 for(unsigned i=0;i<64u;i++)if(test_ram[i])return DBG_SEQUENCE;
#ifdef DBG_ENABLE_RX_STREAM_BURST
 if(dbg_u32(test_ram+192u)>1u)return DBG_RANGE;
#endif
 return DBG_OK;
}

static void rxs_run(transport_t *t,uint32_t sequence,uint32_t duration) {
 rxs_context_t c;memset(&c,0,sizeof(c));c.started=osiUpTime();
#ifdef DBG_ENABLE_RX_STREAM_FAST
 c.started_us=osiUpTimeUS();
 memset(test_ram+64u,0,128u);clean(test_ram+64u,128u);
#endif
 uint32_t result=cp_submit(CP_CALL,0,0,0,0,0x100bu,0,NULL,&c.cp_sequence);
 if(result!=DBG_OK){encode_reply(t,sequence,DBG_RX_STREAM,result,0);send_all(t);return;}
 if(!rxs_packet(t,sequence,&c,RXS_ACCEPT,0,0,0,0,c.cp_sequence,NULL,0,DBG_OK))result=DBG_TIMEOUT;
 bool stop_sent=false;
 uint32_t state[30],reply[8],progress[16];
 while(result==DBG_OK && osiUpTime()-c.started<(int64_t)duration+RXS_DRAIN_TIMEOUT_MS) {
  if(!c.initialized) {
   if(!rxs_read_words(RXS_PROGRESS_ADDRESS,progress,16u)){result=DBG_ACCESS;break;}
   if(progress[0]==RXS_PROGRESS_MAGIC && progress[1]==RXS_GENERATION && !(progress[2]&1u)) {
    c.phase=progress[3];c.error=progress[4];
    if(c.phase>=31u){result=DBG_NOT_READY;break;}
    if(c.phase>=24u && rxs_state(state))c.initialized=true;
   }
   if(!c.initialized) {
    invalidate((const void *)&mailbox->response_seq,64u);
    if(mailbox->response_seq==c.cp_sequence){result=DBG_NOT_READY;break;}
    if(osiUpTime()-c.started>RXS_INITIALIZE_TIMEOUT_MS){result=DBG_TIMEOUT;break;}
    continue;
   }
#ifdef DBG_ENABLE_RX_STREAM_FAST
   /* ACCEPT framing/send are timed separately; keep the phase sums disjoint. */
   c.profile[8]=(uint32_t)(osiUpTimeUS()-c.started_us)-c.profile[13]-c.profile[14];
#endif
  }
  bool state_ok;
  {RXS_TIME_START;state_ok=rxs_state(state);RXS_TIME_ADD(&c,9u);}
  if(!state_ok)continue;
  c.flags=state[3];c.reason=state[8];
  if(!stop_sent && !(state[3]&1u) && osiUpTime()-c.started>=duration) {
   result=rxs_command(&c,7u,0u,reply);stop_sent=result==DBG_OK;continue;
  }
  uint32_t block=state[7];
  if(block!=state[6]) {
   uint32_t row=9u+(block%RXS_SLOTS)*3u;
   if(state[row]!=block || state[row+1u]!=0u || state[row+2u]!=3u)continue;
   result=rxs_command(&c,5u,block,reply);
   if(result!=DBG_OK)break;
   if(reply[5]!=block || reply[6]!=block%RXS_SLOTS){result=DBG_SEQUENCE;break;}
   {RXS_TIME_START;result=rxs_copy_pair(block,t->bulk);RXS_TIME_ADD(&c,11u);}
   if(result!=DBG_OK)break;
   /* AP owns the complete staging copy before CP may reuse its slot. */
   result=rxs_command(&c,6u,block,reply);
   if(result!=DBG_OK)break;
   if(reply[5]!=block || reply[6]!=block+1u){result=DBG_SEQUENCE;break;}
   if(!rxs_send_pair(t,sequence,&c,block)){result=DBG_TIMEOUT;break;}
   ++c.blocks;
   continue;
  }
  uint32_t active=0;
  for(unsigned i=0;i<RXS_SLOTS;i++)active|=state[10u+i*3u]&3u;
  if((state[3]&1u) && !active) {
   result=rxs_command(&c,8u,0u,c.park_response);
   if(result==DBG_OK) {
    c.parked=true;c.reason=c.park_response[6];
    if(c.park_response[5]!=c.blocks)result=DBG_SEQUENCE;
   }
   break;
  }
 }
 if(!c.parked) {
  if(result==DBG_OK)result=DBG_TIMEOUT;
  if(c.initialized)(void)rxs_command(&c,7u,0u,reply);
 }
 if(rxs_read_words(RXS_PROGRESS_ADDRESS,progress,16u)) {
  c.phase=progress[3];c.error=progress[4];
 }
 if(result==DBG_OK && (!c.parked || (c.reason!=1u && c.reason!=2u) || c.phase!=30u || c.error))
  result=DBG_NOT_READY;
 uint32_t counters[16]={c.blocks,c.blocks*RXS_DATA_BYTES,c.blocks*RXS_HEAD_BYTES,
   (uint32_t)(osiUpTime()-c.started),c.cp_sequence,c.parked?1u:0u,c.phase,c.error};
 for(unsigned i=0;i<8;i++)counters[8+i]=c.park_response[i];
 uint8_t encoded[64];for(unsigned i=0;i<16;i++)dbg_put32(encoded+i*4u,counters[i]);
 (void)rxs_packet(t,sequence,&c,RXS_END,c.blocks,0,0,c.flags,c.reason,encoded,sizeof(encoded),result);
#ifdef DBG_ENABLE_RX_STREAM_FAST
 c.profile[0]=0x41505431u;c.profile[1]=1u;c.profile[2]=RXS_GENERATION;c.profile[3]=2u;
 c.profile[4]=c.blocks;c.profile[5]=c.packet;c.profile[6]=result;
 c.profile[7]=(uint32_t)(osiUpTimeUS()-c.started_us);
 c.profile[25]=c.phase;c.profile[26]=c.error;c.profile[27]=duration;
 c.profile[28]=c.cp_sequence;c.profile[29]=c.reason;
#ifdef DBG_ENABLE_RX_STREAM_BURST
 c.profile[30]=dbg_u32(test_ram+192u);
#endif
 memcpy(test_ram+64u,c.profile,128u);clean(test_ram+64u,128u);
#endif
}
