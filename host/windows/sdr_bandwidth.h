#ifndef SDR_HOST_BANDWIDTH_H
#define SDR_HOST_BANDWIDTH_H
#include "../../firmware/sdr_receiver/sample_rate.h"
/* Host implementation ceiling, not advertised hardware support. INFO must
 * explicitly list a requested nonzero mode before CONFIG or START. */
#define SDR_HOST_MAX_BANDWIDTH_INDEX 5u
#endif
