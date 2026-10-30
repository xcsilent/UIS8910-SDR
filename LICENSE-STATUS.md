# Licensing and distribution scope

The owner selected **GPL-3.0-or-later** for the project's original code and
documentation on 2026-10-30. See the full [GNU GPL version 3](LICENSE). Original
contributions may be used under version 3 or, at your option, any later version.
Contributions are accepted under these same terms unless explicitly agreed
otherwise; there is no separate CLA.

This grant covers contributions the project owner can license. Existing
third-party notices and terms take precedence for their respective material.
It does not relicense the vendor modem, bootloader, RF libraries, board NV,
compiler, SDR++ core or other third-party components. Reconstructed code's
provenance and any applicable upstream terms must remain visible.

The receiver retains vendor binary dependencies; it is not a fully open-source
modem or a clean-room replacement for the complete chip firmware.

## Local release preparation

The public project name is **UIS8910-SDR**. Source, final measurement summaries
and v0.1 binary packages are prepared locally using
[the publication procedure](docs/publishing.md). Original research records and
installed components remain unchanged. No GitHub repository is created or
uploaded by that procedure.

Two third-party distribution questions remain open:

1. The SDK root contains GPLv3 text, but that does not establish the terms of
   every vendor boot/RF/modem/NV object included in the platform PAC or SDK
   subset. These inputs remain identified, separate build dependencies.
2. The selected ARM GCC/binutils bundle lacks its original distribution's
   complete notice/source package. Copying a GPL license text alone would not
   settle corresponding-source obligations. Confirm the original distribution
   and provide the applicable notices and source before uploading it.

The publication request includes the local SDK/toolchain inputs and firmware
PAC so the firmware build can be reproduced. These technical requirements do
not resolve third-party redistribution terms. Host runtime notices and exact
component pairings are retained. See
[third-party provenance](THIRD_PARTY_NOTICES.md).

中文：原创代码和文档已选定 GPL-3.0-or-later；第三方组件沿用原许可。
本地发布副本会移除个人路径、设备标识和采集载荷，原始证据不改写。
厂商二进制及 ARM 工具链的分发条件尚需核实；本轮不上传 GitHub。
