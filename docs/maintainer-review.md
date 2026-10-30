# Engineering and open-source maintainer review

Review date2026-10-30. This is the consolidated delivery-gap list; it does not restart the hardware Goal. Original captures were removed at the owner's request, and measurements have not been repeated for this review.

## What is ready to explain

The repository can now explain the conversion method, responsibilities, DMA ownership, raw lane format, receive lifecycle, reconstructed register chain and limits of the measured results. English and Chinese reports link to final evidence. Derived JSON/CSV tables and static SVG/PNG plots are generated from final summaries; automated portable checks do not require vendorSDK or hardware.

The local source-review export is an allowlist, not a copy of the64 GB research workspace. It includes the pinned ARM/SDK subset and sole v0.1 PAC required for the firmware build. It excludes complete reference trees, host DLLs, capture payloads and frozen archives. Historical firmware artifacts were removed at the owner's request; full local SDK/toolchains and final research records remain.

The current sanitized source inventory is in `work/github-publication-v0.1/source/EXPORT-REVIEW.json`; the paired binary packages and privacy/integrity results are described in `work/github-publication-v0.1/preparation-report.json`. Small directly cited final summaries are included. Links to omitted research inputs are labeled as local-only in the publication copy. The redundant earlier source-review and independent WSL copies were removed after retaining their final evidence. Firmware and WSL host components can be built using the documented inputs and external system packages; native SDR++ bootstrap remains separate.

## Priority0: decisions before a public release

| Gap | Why it matters | Concrete next action / completion condition |
| --- | --- | --- |
| Original contribution license selected | owner selected GPL-3.0-or-later for original code/docs | root LICENSE and scope are present; third-party components retain their terms |
| Vendor and reconstructed-source provenance | SDK root GPL text does not clear every included binary/manual/NV | classify copied/derived files and separate external prerequisites; omit uncleared material |
| Export metadata privacy | historical records contain local paths and device serials | `tools/prepare_release.py` sanitizes copies including JSON/log strings and scans package contents; local evidence is preserved |
| Build-input distribution clearance | local independent-copy build uses pinned ARM/SDK archives and v0.1 vendor PAC | technical bootstrap is implemented; review third-party redistribution and compiler source/notice obligations before public upload |

Original contributions are now GPL-3.0-or-later; no upload has occurred. [Local publication packages](publishing.md) separate source from paired binaries and report unresolved distribution items. Omitted local-only references remain labeled.

## Priority1: delivery consistency

| Finding | Current evidence | Recommended implementation when code work resumes |
| --- | --- | --- |
| B40 Auto cap differs acrossC/C++ consumers | [C++ helper](../host/common/RfAuto.hpp) uses2786 MHz quality cap; [Windows helper](../host/windows/sdr_info.c) with [C Auto policy](../host/common/rf_auto.h) retains2790.625 MHz table envelope; `verify_rf_auto.py` expects the latter | put the quality bound in one shared capability source, preserve manual exploratory requests, run focused cross-consumer boundary tests, then rebuild paired host components |
| Auto range and measured RF strength are different | route catalog/thresholds are software policy; full optimal-path sweep was not performed at everyHz | label requestability separately from reference evidence; avoid presenting a selected route as globally strongest |
| Single current firmware build | `tools/build_firmware.py` and `firmware/platform/air724ug.json` compile current6×8192 service from bundled inputs | keep the single recipe current; legacy builders are research tools, not release prerequisites |
| Host componentDLLs advance independently | Windows real-time CLI promoted separately fromSoapy/SDR++ | package each paired component; release checklist compares manifest identities and runtime ABI |
| Wideband stream lacks exact gap locations | pure raw/no sequence metadata by design | document partial-segment semantics in adapter/API help; don't invent timestamps or fake a lower continuousFs |
| Old state/README references drifted to previousv23/v29 | release manifest and currentv32 state differ from old narrative | current intros now point to manifests; keep historical records unchanged and marked as such |

These are proposed code changes, **not implemented release changes** in this documentation task. Passing Markdown/JSON checks does not close them.

## Priority2: measurements that would improve the data sheet

| Unknown | What would reduce uncertainty | Scope control |
| --- | --- | --- |
| Continuous RF intervals and physical limits | calibrated conducted source/attenuation, suitable antennas or board fixture, sparse representative testing then refine actual transitions | do not equate missing signal with chip limit; don't re-scan every old point |
| Exact external frontend and wiring | board photo/BOM/schematic, reliable boundedID transaction evidence | maintain compatible-group hypothesis until actual identity/wiring is known |
| ENOB, sensitivity, noise figure, SFDR/IIP3 | characterized source, calibrated levels and explicit measurement methods | optional characterization, not prerequisites for existing10 s functional proof |
| Sample clock accuracy / absolute timing | independent frequency/time reference and supported timestamp design | nominalFs remains nominal; no claimed coherent/MIMO operation |
| Overload and analog compression | single-variable lowerTX/RX comparisons and known input level | native12 near-rail absence is necessary evidence only for sampled digital levels |
| Device CPU and retune interruption | instrumentation outside payload hot path and defined wall/CPU measurement boundaries | architecture alone does not supply numbers; no strict zero-loss gate |

The owner ended repeated USB micro-optimization. Reopen only for a concrete regression or a new measured bottleneck. BW6/7, cellular demodulation, fullBCPU ROM, ZSP,1090 MHz expansion and GUI work remain outside the retained delivery scope. Desktop visual acceptance was abandoned; no new visual test is scheduled.

## Verification and reproducibility limits

- Local full verification checks release identities, raw policy, links, syntax and evidence freshness. Old fingerprints can remain stale; this is disclosed separately from a structural pass.
- Portable CI checks documents, final summaries and dependency archive identities. It includes a Windows firmware build, an Ubuntu24.04 Windows-host cross-build, and Windows offline checks of the produced queue/Soapy binaries. The configured workflow has not been run by GitHub merely because it exists; none of these jobs proves RF performance.
- The [WSL recipe](building-wsl.md) specifies POSIX MinGW C/C++, Linux runtime dependencies, CMake/Ninja, bundled Soapy source and paired DLLs. Local independent-copy build/runtime evidence is in [host-build-wsl](../records/maintenance/host-build-wsl-README.md). Native SDR++ MSVC/core ABI prerequisites are still separate.
- Final summary tables are reproducible from retained smallJSONs. Old spectra/decoded waveforms cannot be independently recalculated after authorized raw deletion; the [audit](../records/maintenance/open-source-preparation-README.md) records that choice.
- Neither a calibrated board schematic nor an authentic full RF register manual is supplied. Independent relocated-copy firmware build evidence is retained in [the final build records](../records/maintenance/release-v0.1-README.md). The [register crosswalk](data/rf-registers.csv) is an engineering reconstruction, not an official manual.

## 发布前需要所有者决定的两件事

原创代码和文档已确定为 GPL-3.0-or-later。发布范围为源码、技术文档、最终结果及 v0.1 固件和配对主机工具，不含 IQ、个人信息或原 Git 历史。按[发布流程](publishing.md)生成本地副本；厂商组件与 ARM 工具链的分发条件仍需解决，本轮不上传。
