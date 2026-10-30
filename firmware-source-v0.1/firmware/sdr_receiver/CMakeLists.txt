get_filename_component(SDR_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/../../../../.." ABSOLUTE)
set(SDR_DIR "${SDR_ROOT}/firmware/sdr_receiver")
set(MONITOR_DIR "${SDR_ROOT}/firmware/debug_monitor")
if(NOT EXISTS "${SDR_GENERATED_DIR}/cp_agent_blob.h" OR NOT EXISTS "${SDR_GENERATED_DIR}/udc_bindings.h")
    message(FATAL_ERROR "Use tools/build_receiver.py to prepare the service build")
endif()
add_appimg(${target} ${flash_ldscript}
    ${MONITOR_DIR}/ap_monitor.c ${MONITOR_DIR}/debug_hash.c ${MONITOR_DIR}/ap_access.S
    ${SDR_DIR}/iq_usb_ring.c ${SDR_DIR}/iq_udc_adapter.c ${SDR_DIR}/raw_usb_function.c)
target_include_directories(${target} PRIVATE ${MONITOR_DIR} ${SDR_DIR} ${SDR_GENERATED_DIR})
target_compile_definitions(${target} PRIVATE DBG_ENABLE_BULK=1 DBG_ENABLE_ASYNC_CALL=1 DBG_ENABLE_RAW_USB=1)

if(SDR_ENABLE_BW0_USB)
    target_sources(${target} PRIVATE
        ${SDR_DIR}/cp_capture_bridge.c ${SDR_DIR}/cp_stream_mailbox.c
        ${SDR_DIR}/cp_usb_stream.c ${SDR_DIR}/cp_usb_stream_snapshot.c
        ${SDR_DIR}/cp_usb_8910.c ${SDR_DIR}/cp_usb_scheduler.c ${SDR_DIR}/usb_segment_profile.c ${SDR_DIR}/bw0_usb_service.c)
    target_sources(${target} PRIVATE ${SDR_ROOT}/firmware/capture/rxcapt_profile.c)
    target_compile_definitions(${target} PRIVATE DBG_ENABLE_BW0_USB=1)
    target_compile_definitions(${target} PRIVATE SDR_BW0_MAX_BW=${SDR_BW0_MAX_BW})
    target_compile_definitions(${target} PRIVATE SDR_BW0_CONTINUOUS=${SDR_BW0_CONTINUOUS})
    target_compile_definitions(${target} PRIVATE CP_USB_COMBINED_EXCHANGE=${CP_USB_COMBINED_EXCHANGE})
    target_compile_definitions(${target} PRIVATE SDR_USB_SEGMENT_PROFILE=1)
endif()
target_compile_options(${target} PRIVATE -Wall -Wextra -Wno-misleading-indentation)
target_link_options(${target} PRIVATE -Wl,--undefined=debug_at_write_filter -Wl,--undefined=debug_data_abort_gate)
