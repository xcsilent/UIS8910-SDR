#include <stdint.h>
#include "rxcapt_fem_command_snapshot.h"

static uint32_t pointers[5], reads[10], count;
static uint32_t fixture(void *context, uint32_t address)
{
    static const uint32_t objects[5] = {
        0x804ee978u, 0x804efcc8u, 0x804edc98u, 0x804ee4a4u, 0x804ef320u
    };
    (void)context;
    reads[count++] = address;
    for (unsigned i=0; i<5; ++i)
        if (address == objects[i]+0x2cu) return pointers[i];
    return address ^ 0x13579bdfu;
}

int main(void)
{
    uint32_t row[20];
    pointers[0]=0x25101260u; pointers[1]=0x2510157cu;
    pointers[2]=0x25102260u; pointers[3]=0x2510257cu;
    pointers[4]=0x2510257du;
    fem_command_observe(row, 2, fixture, 0);
    if (row[0]!=2 || count!=9 || row[15]!=0 || row[14]!=0) return 1;
    for (unsigned i=0;i<4;++i)
        if (row[1+3*i]!=pointers[i] || row[2+3*i]!=(pointers[i]^0x13579bdfu) || row[3+3*i]!=1) return 2;
    if (fem_command_pointer_valid(0x2510125cu) || fem_command_pointer_valid(0x25101580u) ||
        fem_command_pointer_valid(0x2510225cu) || fem_command_pointer_valid(0x25102580u) ||
        fem_command_pointer_valid(0xffffffffu)) return 3;
    return 0;
}
