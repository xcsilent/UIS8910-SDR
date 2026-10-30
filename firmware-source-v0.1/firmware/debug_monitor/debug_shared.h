#ifndef UIS_DEBUG_SHARED_H
#define UIS_DEBUG_SHARED_H
#include <stdint.h>
#include <stddef.h>

#define DBG_VERSION 1u
#define DBG_MAX_PAYLOAD 4096u
#define DBG_MAGIC 0x31474455u /* UDG1 */
#define CP_GATE_MAGIC 0x31424455u /* UDB1 */
#define CP_DEBUG_BASE 0x80970000u
#define CP_DEBUG_SIZE 0x10000u
#define CP_AGENT_BASE (CP_DEBUG_BASE + 0x1000u)
#define CP_AGENT_LIMIT (CP_DEBUG_BASE + 0x5000u)
#define CP_SLOT0 (CP_DEBUG_BASE + 0x5000u)
#define CP_SLOT1 (CP_DEBUG_BASE + 0x7000u)
#define CP_SLOT2 (CP_DEBUG_BASE + 0x9000u)
#define CP_SLOT_SIZE 0x2000u
#define CP_SCRATCH (CP_DEBUG_BASE + 0xb000u)
#define CP_SCRATCH_SIZE 0x5000u
#define CP_TRANSFER_SIZE 1024u
#define CP_BASELINE_SHA "bd25923aa2fd2cde32fafe59305b6655a79645ad7ff447b74f0ffd4286a020d1"

enum dbg_op { DBG_INFO=1, DBG_READ=2, DBG_WRITE=3, DBG_STATUS=4,
 DBG_UPLOAD_BEGIN=16, DBG_UPLOAD_DATA=17, DBG_UPLOAD_END=18,
 DBG_ACTIVATE=19, DBG_ROLLBACK=20, DBG_CALL=21, DBG_CALL_ASYNC=22,
 DBG_REBOOT=31, DBG_BULK_READ=32, DBG_RX_STREAM=33 };
enum dbg_status { DBG_OK=0, DBG_BAD_REQUEST=1, DBG_RANGE=2, DBG_CRC=3,
 DBG_UNSUPPORTED=4, DBG_BUSY=5, DBG_TIMEOUT=6, DBG_BASELINE=7,
 DBG_SEQUENCE=8, DBG_DIGEST=9, DBG_NOT_READY=10, DBG_ACCESS=11 };
enum dbg_core { DBG_AP=0, DBG_CP=1, DBG_BCPU=2 };
enum dbg_space { DBG_RAM=0, DBG_ROM=1, DBG_MMIO=2, DBG_FLASH=3 };
enum cp_op { CP_NOP=0, CP_READ=1, CP_WRITE=2, CP_ACTIVATE=3,
 CP_ROLLBACK=4, CP_CALL=5 };

/* Publishers own separate cache lines. Request data is not reused before ack. */
typedef struct {
 volatile uint32_t magic, entry, abi, heartbeat;
 volatile uint32_t active_entry, active_generation, previous_entry, previous_generation;
 uint32_t reserved0[8];
 volatile uint32_t request_seq, command, address, length, width, space;
 volatile uint32_t argument, generation;
 uint32_t reserved1[8];
 volatile uint32_t response_seq, status, response_length, last_result;
 uint32_t reserved2[28];
 volatile uint8_t data[CP_TRANSFER_SIZE];
} cp_mailbox_t;
_Static_assert(offsetof(cp_mailbox_t,request_seq)==64,"request line");
_Static_assert(offsetof(cp_mailbox_t,response_seq)==128,"response line");
_Static_assert(offsetof(cp_mailbox_t,data)==256,"data offset");

static inline void dbg_barrier(void) {
#if defined(__arm__)
 __asm__ volatile("dmb sy" ::: "memory");
#else
 __asm__ volatile("" ::: "memory");
#endif
}
static inline void dbg_cache_barrier(void) {
#if defined(__arm__)
 __asm__ volatile("dsb sy" ::: "memory");
#else
 __asm__ volatile("" ::: "memory");
#endif
}
static inline uint32_t dbg_u32(const uint8_t *p) {
 return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
static inline void dbg_put32(uint8_t *p,uint32_t n) {
 p[0]=n;p[1]=n>>8;p[2]=n>>16;p[3]=n>>24;
}
static inline int dbg_within(uint32_t a,uint32_t n,uint32_t base,uint32_t size) {
 return n>0 && a>=base && n<=size && a-base<=size-n;
}
uint32_t dbg_crc32(const void *p,size_t n);
uint32_t dbg_crc_update(uint32_t crc,const void *p,size_t n);
void dbg_sha256(const uint8_t *p,size_t n,uint8_t out[32]);
#endif
