#include <stdio.h>
#include <stdlib.h>
#include "../../firmware/sdr_receiver/rf_profile.h"
int main(int argc,char **argv)
{
    if(argc!=3) return 2;
    uint32_t band=(uint32_t)strtoul(argv[1],NULL,10),hz=(uint32_t)strtoul(argv[2],NULL,10);
    uint32_t channel=sdr_rf_channel(band,hz);
    printf("%u %u\n",channel,channel?terminal_profile_anchor(channel)*100u:0);
    return 0;
}
