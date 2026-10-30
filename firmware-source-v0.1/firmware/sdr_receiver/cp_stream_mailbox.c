#include "cp_stream_mailbox.h"
#include <stddef.h>

#define SERVICE_MAGIC 0x52585331u
int cp_stream_mailbox_init(struct cp_stream_mailbox *m,volatile uint32_t *lines,
                           uint32_t generation,struct cp_mailbox_cache cache)
{
    if (!m || !lines || ((uintptr_t)lines&31u) || !generation ||
        !cache.clean || !cache.invalidate || !cache.barrier) return 0;
    *m=(struct cp_stream_mailbox){0};
    m->request=lines; m->response=lines+8; m->generation=generation; m->cache=cache;
    return 1;
}
int cp_stream_mailbox_begin(struct cp_stream_mailbox *m,uint32_t operation,
                            uint32_t block,uint32_t now_ms,uint32_t timeout_ms)
{
    if (!m || m->pending || m->fault || m->completed==UINT32_MAX || !timeout_ms ||
        timeout_ms>60000u || (operation!=7u && operation!=9u && operation!=11u && operation!=12u && operation!=13u && operation!=14u) ||
        (operation==7u && block)) return 0;
    uint32_t sequence=m->completed+1u;
    m->request[7]=0;
    m->cache.barrier(m->cache.context);
    m->request[0]=SERVICE_MAGIC; m->request[1]=m->generation;
    m->request[2]=sequence; m->request[3]=operation;
    m->request[4]=m->completed; m->request[5]=block;
    m->request[6]=~sequence;
    m->cache.barrier(m->cache.context);
    m->request[7]=sequence;
    m->cache.clean(m->cache.context,m->request,32u);
    m->cache.barrier(m->cache.context);
    m->pending=sequence; m->operation=operation; m->block=block;
    m->begun_ms=now_ms; m->timeout_ms=timeout_ms;
    return 1;
}
enum cp_mailbox_result cp_stream_mailbox_poll(struct cp_stream_mailbox *m,
                                              uint32_t now_ms,struct cp_stream_reply *out)
{
    if (!m || !out || !m->pending) return CP_MBOX_BAD_REPLY;
    uint32_t first[8];
    m->cache.invalidate(m->cache.context,m->response,32u);
    m->cache.barrier(m->cache.context);
    for (unsigned i=0;i<8;++i) first[i]=m->response[i];
    if (first[0]==SERVICE_MAGIC && first[1]==m->generation &&
        first[2]==m->pending && first[7]==m->pending) {
        m->cache.invalidate(m->cache.context,m->response,32u);
        m->cache.barrier(m->cache.context);
        unsigned i;
        for (i=0;i<8;++i) if (first[i]!=m->response[i]) break;
        if (i==8) {
            *out=(struct cp_stream_reply){first[3],first[4],first[5],first[6]};
            if (first[3]==4u || first[4]) {
                /* A rejected CP command does not advance its sequence cursor.
                 * Reusing that sequence could consume the old error reply as
                 * a reply to the new payload. End the session; never guess.
                 */
                m->fault=1; m->pending=0;
                return CP_MBOX_REJECTED;
            }
            if (first[3]!=m->operation || (m->operation!=7u && first[5]!=m->block)) {
                m->fault=1; m->pending=0;
                return CP_MBOX_BAD_REPLY;
            }
            m->completed=m->pending;
            m->pending=0;
            return CP_MBOX_DONE;
        }
    }
    if ((uint32_t)(now_ms-m->begun_ms)>=m->timeout_ms) {
        /* Preserve pending and keep observing this exact command: a timeout
         * does not prove CP rejected it or returned any buffer ownership.
         */
        m->fault=1;
        return CP_MBOX_EXPIRED;
    }
    return CP_MBOX_WAIT;
}
