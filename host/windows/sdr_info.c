/* Bounded JSON reader for monitor INFO. No scanning for substrings inside
 * unrelated strings/nested objects; ambiguous duplicate root keys are refused. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>
#include <stdio.h>
#include "sdr_session.h"
#include "../common/rf_auto.h"
#define RXCAPT_MULTI_PROFILE 1
#include "../../firmware/capture/rxcapt_profile.h"
struct span { const char *p; size_t n; };
struct parser { const char *p,*end; };
static void space(struct parser *s)
{ while(s->p<s->end && strchr(" \r\n\t",*s->p) && *s->p) ++s->p; }
static int take(struct parser *s,char c)
{ space(s);if(s->p==s->end || *s->p!=c) return 0;++s->p;return 1; }
static int string(struct parser *s,struct span *v)
{
    if(!take(s,'"')) return 0;
    v->p=s->p;
    while(s->p<s->end) {
        unsigned char c=(unsigned char)*s->p++;
        if(c=='"') { v->n=(size_t)(s->p-v->p-1);return 1; }
        if(c<32) return 0;
        if(c=='\\') {
            if(s->p==s->end) return 0;
            c=(unsigned char)*s->p++;
            if(c=='u') {
                for(unsigned i=0;i<4;++i) {
                    if(s->p==s->end || !*s->p || !strchr("0123456789abcdefABCDEF",*s->p++)) return 0;
                }
            } else if(!c || !strchr("\"\\/bfnrt",c)) return 0;
        }
    }
    return 0;
}
static int equal(struct span v,const char *text)
{ return strlen(text)==v.n && !memcmp(v.p,text,v.n); }
static int value(struct parser *s,unsigned depth)
{
    space(s);if(s->p==s->end || depth>16) return 0;
    struct span unused;
    if(*s->p=='"') return string(s,&unused);
    if(*s->p=='[' || *s->p=='{') {
        int object=*s->p++=='{';char end=object?'}':']';
        if(take(s,end)) return 1;
        do {
            if(object && (!string(s,&unused) || !take(s,':'))) return 0;
            if(!value(s,depth+1)) return 0;
            if(take(s,end)) return 1;
        } while(take(s,','));
        return 0;
    }
    const char *start=s->p;
    while(s->p<s->end && !strchr(" ,]}\r\n\t",*s->p) && *s->p) ++s->p;
    struct span token={start,(size_t)(s->p-start)};
    if(equal(token,"true") || equal(token,"false") || equal(token,"null")) return 1;
    const char *p=start,*end=s->p;
    if(p<end && *p=='-') ++p;
    if(p==end) return 0;
    if(*p=='0') ++p;
    else { if(*p<'1' || *p>'9') return 0;while(p<end && *p>='0' && *p<='9') ++p; }
    if(p<end && *p=='.') { ++p;const char *q=p;while(p<end && *p>='0' && *p<='9') ++p;if(q==p) return 0; }
    if(p<end && (*p=='e' || *p=='E')) {
        ++p;if(p<end && (*p=='+' || *p=='-')) ++p;
        const char *q=p;while(p<end && *p>='0' && *p<='9') ++p;if(q==p) return 0;
    }
    return p==end;
}
static uint32_t array_contains(struct span array,uint32_t item)
{
    if(!array.p) return ERROR_NOT_SUPPORTED;
    struct parser s={array.p,array.p+array.n};
    if(!take(&s,'[') || take(&s,']')) return ERROR_NOT_SUPPORTED;
    char requested[16];snprintf(requested,sizeof(requested),"%u",(unsigned)item);
    int found=0;
    do {
        space(&s);const char *start=s.p;
        if(!value(&s,0)) return ERROR_INVALID_DATA;
        if(equal((struct span){start,(size_t)(s.p-start)},requested)) found=1;
        if(take(&s,']')) break;
        if(!take(&s,',')) return ERROR_INVALID_DATA;
    } while(1);
    return found?0:ERROR_NOT_SUPPORTED;
}
uint32_t sdr_session_validate_info(const char *json,uint32_t bytes,uint32_t band)
{ return sdr_session_validate_info_bw(json,bytes,band,0); }
static uint32_t validate_mode(const char *json,uint32_t bytes,uint32_t band,uint32_t bandwidth,int continuous)
{
    static const char *keys[]={"firmware","raw_usb","raw_usb_abi","bw0_usb",
        "bw0_status_operation","bw0_start_operation","bw0_stop_operation",
        "bw0_config_operation","bw0_recovery_status_operation","bw0_rf_profiles",
        "bw0_bandwidth_indices","bw0_config_abi","bw0_until_stop","bw0_keepalive_operation","bw0_lease_timeout_ms"};
    static const char *expected[]={"\"uis8910-sdr-bw0-usb-v1\"","true","1","true","44","45","46","47","48"};
    if(!json || !bytes || bytes>SDR_CONTROL_MAX_PAYLOAD) return ERROR_INVALID_DATA;
    if(bandwidth>SDR_HOST_MAX_BANDWIDTH_INDEX) return ERROR_NOT_SUPPORTED;
    struct parser s={json,json+bytes};struct span fields[15]={{0}};
    if(!take(&s,'{') || take(&s,'}')) return ERROR_INVALID_DATA;
    do {
        struct span key;
        if(!string(&s,&key) || !take(&s,':')) return ERROR_INVALID_DATA;
        /* Reject escaped root keys instead of allowing alternate spellings to
         * hide a duplicate of a capability. Current monitor emits plain keys. */
        if(memchr(key.p,'\\',key.n)) return ERROR_INVALID_DATA;
        space(&s);const char *start=s.p;
        if(!value(&s,0)) return ERROR_INVALID_DATA;
        for(unsigned i=0;i<15;++i) if(equal(key,keys[i])) {
            if(fields[i].p) return ERROR_INVALID_DATA;
            fields[i]=(struct span){start,(size_t)(s.p-start)};
        }
        if(take(&s,'}')) break;
        if(!take(&s,',')) return ERROR_INVALID_DATA;
    } while(1);
    space(&s);if(s.p!=s.end) return ERROR_INVALID_DATA;
    for(unsigned i=0;i<9;++i) if(!fields[i].p || !equal(fields[i],expected[i])) return ERROR_NOT_SUPPORTED;
    uint32_t error=array_contains(fields[9],band);
    if(error) return error;
    if(continuous && (!fields[12].p || !equal(fields[12],"true") ||
        !fields[13].p || !equal(fields[13],"49") || !fields[14].p || !equal(fields[14],"5000")))
        return ERROR_NOT_SUPPORTED;
    if(!bandwidth && !fields[10].p) return 0; /* legacy BW0 firmware */
    if(bandwidth && (!fields[11].p || !equal(fields[11],"2"))) return ERROR_NOT_SUPPORTED;
    return array_contains(fields[10],bandwidth);
}
uint32_t sdr_session_validate_info_bw(const char *json,uint32_t bytes,uint32_t band,uint32_t bandwidth)
{ return validate_mode(json,bytes,band,bandwidth,0); }
uint32_t sdr_session_validate_until_stop_info(const char *json,uint32_t bytes,uint32_t band,uint32_t bandwidth)
{ return validate_mode(json,bytes,band,bandwidth,1); }

uint32_t sdr_session_auto_route(const char *json,uint32_t bytes,uint32_t hz,
    uint32_t current,uint32_t bandwidth,uint32_t continuous,uint32_t *selected)
{
    static const uint32_t candidates[]={5,8,3,40};
    if(!selected || !hz || hz%100 || continuous>1)return ERROR_INVALID_PARAMETER;
    *selected=0;uint32_t mask=0;
    for(unsigned i=0;i<4;++i) {
        uint32_t band=candidates[i];
        uint32_t e=validate_mode(json,bytes,band,bandwidth,(int)continuous);
        if(e && e!=ERROR_NOT_SUPPORTED)return e;
        if(!e && terminal_profile_auto_channel(band,hz))mask|=uis_auto_bit(band);
    }
    *selected=uis_auto_choose(mask,hz,current);
    return *selected?0:ERROR_NOT_SUPPORTED;
}
