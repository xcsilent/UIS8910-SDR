# Third-party sources and notices

This file records local provenance observed on2026-10-30. Original project contributions use GPL-3.0-or-later; this does not grant redistribution rights to third-party material or replace upstream licenses. [License scope](LICENSE-STATUS.md) identifies the remaining distribution questions.

| Input / dependency | Pinned source | Observed terms / publication treatment |
| --- | --- | --- |
| UIS8910 CSDK / hotelec | `https://gitee.com/hotelec/RDA8910_CSDK.git`, commit `585a0c8352cf3937a32b63f638fabe767d0ca28c` | root LICENSE containsGPLv3 text; bundled modem/RF/boot binaries, PAC/NV, tools and manuals require their own provenance review. Full tree excluded from review export |
| ZW217 UIX8910 reference | `https://github.com/obaidi2005/ZW217_W19_V4.1_yisai.git`, commit `d48d55e028c13b6f50c291cbb7ea29201c3c8432` | no top-level license identified in the local review; mixed vendor sources. Full tree/excerpts excluded by default pending per-file review |
| RDA8955/8810/8850e excerpts | local manifest `inputs/reference-source/predecessors/source-manifest.json`, eight selected files | original notices retained locally; no blanket permission inferred. Entire predecessor trees remain outside publication export |
| SoapySDR0.8.1 | commit `1cf5a539a21414ff509ff7d0eedfc5fa8edb90c6` | source and `LICENSE_1_0.txt` bundled in `build-support/soapysdr-0.8.1-source.zip`; Boost Software License1.0. Build copies license beside the DLLs; member hashes in `host-manifest.json` |
| SDR++ | commit `f10fb98af8b80de01de94e60c17608e4281e2515` | local `work/sdrpp/source/license`: GPLv3 text. Project module is GPL-3.0-or-later; Release includes COPYING and the ABI-specific plugin, not the entire SDR++ application |
| MinGW-w64 / winpthreads | retained Ubuntu MinGW package copyright files | Soapy package retains the MinGW-w64 and GCC package copyright/license notices with `libwinpthread-1.dll`; upstream author credits are preserved |
| UHD / B210 runtime | externally installed UHD and device images | used for finite reference TX; no UHD bundle or device image included in source review export |
| ARM, MinGW, MSVC, Windows SDK | retained local toolchains, identities in build records | ARM subset is included in the local buildable review package; review its notices/corresponding source before publishing. MinGW/MSVC/Windows SDK remain local/optional prerequisites |
| Python packages | numpy,pyserial,pyelftools,Unicorn,matplotlib as applicable | installed separately via requirements groups; retain upstream notices if packaging binaries. Requirements are not vendored source or a lockfile |
| PULP ISA material | local reference input used to interpret RF instructions | reference use, no new redistribution assertion |

SDR++ ABI identification: retained target core SHA256 `5cc72ceb770e64646855ade781a59642d2e9be68dc6325a094c74a5fd4df6328`. Matching a product version string does not establish C++ ABI compatibility. The current plugin/runtime identities are listed individually in the [host manifest](outputs/host/manifest.json).

The current PAC retains vendor CP/RF/NV/boot. Firmware application modifications do not convert those retained components into original project source. Do not attach an original-code license to an entire PAC or SDK by implication.

Reconstructed files may contain vendor-derived algorithms, declarations or excerpts; review their individual headers and derivation records before applying a blanket license. Public upstream availability alone is not permission to relicense or redistribute. The local export is for review, not a certification that every included file is cleared.

Sources can be independently located using the pinned URLs/commits; no third-party tree was downloaded during this documentation task.
