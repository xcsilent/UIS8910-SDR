#pragma once
/* Allocation declarations used by the upstream SDR++ stream header.
 * This portable SDR++ ships Pothos VOLK with MSVC C++ decorated exports.
 * No VOLK DSP kernels or C++ object layouts are substituted here. */
#include <stddef.h>
__declspec(dllimport) void *volk_malloc(size_t,size_t);
__declspec(dllimport) void volk_free(void *);
__declspec(dllimport) size_t volk_get_alignment(void);
