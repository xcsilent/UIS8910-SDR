#ifndef UIS8910_RFAD_SPI_H
#define UIS8910_RFAD_SPI_H
#include "rfad_frame_time.h"

/* Version-bound immediate RFAD SPI sequence, with a bounded 100-raw-tick
 * wait. The caller owns RFAD/GPIO, the RF timer, clocks and calibration RAM.
 * rfnv/cursor address layout is that of the reconstructed current CPBIN.
 * BAD_ARGUMENT occurs before any access. TIMEOUT/BAD_CLOCK can occur after
 * the command was submitted: keep RF ownership and the GPIO state pinned;
 * this function deliberately does not perform the final restore store then.
 * The command is a raw RF word, not a validated high-level tuning request. */
enum rfad_frame_time_result rfad_spi_write_bounded(
    const struct rf_bus *,uint32_t rfnv,uint32_t cursor_context,uint32_t command,
    uint32_t card,uint32_t poll_limit);
#endif
