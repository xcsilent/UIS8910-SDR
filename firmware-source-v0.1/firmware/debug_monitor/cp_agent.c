#include "debug_shared.h"

static uint32_t irq_save(void) {
#if defined(__arm__)
 uint32_t n;__asm__ volatile("mrs %0,cpsr\ncpsid i" : "=r"(n) :: "memory");return n;
#else
 return 0;
#endif
}
static void irq_restore(uint32_t n) {
#if defined(__arm__)
 __asm__ volatile("msr cpsr_c,%0" :: "r"(n) : "memory");
#else
 (void)n;
#endif
}
static void icache_sync(void) {
#if defined(__arm__)
 uint32_t z=0;__asm__ volatile("dsb sy\nmcr p15,0,%0,c7,c5,0\ndsb sy\nisb sy" :: "r"(z) : "memory");
#endif
}
static int access_ok(uint32_t a,uint32_t n,uint32_t width,uint32_t space,int write) {
 if(!n || n>CP_TRANSFER_SIZE || (width!=1 && width!=2 && width!=4) || (a&(width-1)) || (n&(width-1)))return 0;
 if(space==DBG_RAM) {
  if(dbg_within(a,n,CP_SCRATCH,CP_SCRATCH_SIZE))return 1;
  if(!write && dbg_within(a,n,CP_SLOT0,3*CP_SLOT_SIZE))return 1;
  /* CP executable text and the resident agent are never generic write targets. */
  if(!write && (dbg_within(a,n,0x80000000,0x970000) || dbg_within(a,n,0x804000,0x40000)))return 1;
  if(write && dbg_within(a,n,0x80468000,0x360000))return 1;
 }
 if(!write && space==DBG_ROM && dbg_within(a,n,0x400a0000,0x28000))return 1;
 if(space==DBG_MMIO && n==width && width==4 &&
    (dbg_within(a,n,0x22000000,0x1000) || dbg_within(a,n,0x25000000,0xc00000)))return 1;
 return 0;
}
__attribute__((section(".text.entry"))) void cp_agent_poll(cp_mailbox_t *m) {
 m->abi=DBG_VERSION;m->heartbeat++;
 uint32_t seq=m->request_seq;dbg_barrier();
 if(!seq || seq==m->response_seq)return;
 uint32_t op=m->command,a=m->address,n=m->length,w=m->width,space=m->space;
 uint32_t status=DBG_OK,out=0;
 if(op==CP_READ || op==CP_WRITE) {
  if(!access_ok(a,n,w,space,op==CP_WRITE))status=DBG_RANGE;
  else {
   for(uint32_t i=0;i<n;i+=w) {
    if(op==CP_READ) {
     uint32_t v=w==4?*(volatile uint32_t *)(a+i):w==2?*(volatile uint16_t *)(a+i):*(volatile uint8_t *)(a+i);
     for(uint32_t j=0;j<w;j++)m->data[i+j]=(uint8_t)(v>>(8*j));
    } else {
     uint32_t v=0;for(uint32_t j=0;j<w;j++)v|=(uint32_t)m->data[i+j]<<(8*j);
     if(w==4)*(volatile uint32_t *)(a+i)=v;
     else if(w==2)*(volatile uint16_t *)(a+i)=v;
     else *(volatile uint8_t *)(a+i)=v;
    }
   }
   /* CP RAM can be cached; publish writes / fetch reads coherently. */
   if(space==DBG_RAM && op==CP_WRITE) {
#if defined(__arm__)
    for(uint32_t p=a&~31u;p<a+n;p+=32)__asm__ volatile("mcr p15,0,%0,c7,c10,1" :: "r"(p) : "memory");
    __asm__ volatile("dsb sy" ::: "memory");
#endif
   }
   out=op==CP_READ?n:0;
  }
 } else if(op==CP_ACTIVATE) {
  uint32_t base=a&~1u;
  if(!(a&1) || !(dbg_within(base,2,CP_SLOT0,CP_SLOT_SIZE)||dbg_within(base,2,CP_SLOT1,CP_SLOT_SIZE)||dbg_within(base,2,CP_SLOT2,CP_SLOT_SIZE)))status=DBG_RANGE;
  else {
   uint32_t flags=irq_save();icache_sync();
   m->previous_entry=m->active_entry;m->previous_generation=m->active_generation;
   m->active_entry=a;m->active_generation=m->generation;
   irq_restore(flags);
  }
 } else if(op==CP_ROLLBACK) {
  uint32_t flags=irq_save(),old=m->active_entry,old_generation=m->active_generation;
  m->active_entry=m->previous_entry;m->previous_entry=old;
  m->active_generation=m->previous_generation;m->previous_generation=old_generation;
  icache_sync();irq_restore(flags);
 } else if(op==CP_CALL) {
  uint32_t flags=irq_save();
  if(m->active_entry) {
#ifdef DBG_HOST_TEST
   extern uint32_t dbg_host_call(uint32_t,uint32_t);
   m->last_result=dbg_host_call(m->active_entry,m->argument);
#else
   m->last_result=((uint32_t (*)(uint32_t))m->active_entry)(m->argument);
#endif
  }
  else m->last_result=m->argument;
  irq_restore(flags);out=4;
  uint32_t v=m->last_result;for(uint32_t i=0;i<4;i++)m->data[i]=(uint8_t)(v>>(8*i));
 } else if(op!=CP_NOP)status=DBG_UNSUPPORTED;
 m->status=status;m->response_length=out;dbg_barrier();m->response_seq=seq;dbg_barrier();
}
