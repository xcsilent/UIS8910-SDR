# Publishing UIS8910-SDR / 发布说明

Project name: **UIS8910-SDR**. Initial release: **v0.1** (VERSION `0.1.0`).
Original code and documentation: **GPL-3.0-or-later**; third parties retain
their own terms. See [license scope](../LICENSE-STATUS.md).

## Publication contents

| Location | Contents |
| --- | --- |
| GitHub source tree | `firmware/`, `host/`, `tools/`, English/Chinese README, architecture, register reconstruction, technical/performance reports, final measurement summaries, build recipes and CI |
| Source build inputs | Pinned SDK/compiler/Soapy subsets and the v0.1 platform PAC used by the documented firmware recipe; vendor/compiler distribution questions remain open |
| Firmware Release ZIP | The manifest-selected `Air724UG_SDR_v0.1.pac`, identity, manual flashing/compatibility notes |
| Windows Release ZIP | Paired receive CLI/DLL/import library; separate paired timing CLI/DLL |
| Soapy Release ZIP | Paired module, receive DLL, Soapy runtime/utilities, winpthread runtime and notices |
| SDR++ Release ZIP | Native module and its paired receive DLL, GPL text and pinned core ABI identity; SDR++ itself is obtained separately |
| Source Release ZIP | Same sanitized source tree, firmware source snapshot and preserved final conclusions; no research Git history |

IQ, TX waveform payloads, captures, raw logs, conversations, full SDK/reference
trees, personal configuration, device identifiers and obsolete firmware
versions are excluded. Upstream copyright/author/license credits are retained.
Do not upload this research workspace or its existing Git history.

## Local preparation

From the retained workstation, without attached hardware:

```powershell
python -B tools/prepare_release.py
```

Output is `work/github-publication-v0.1/`, containing `source/`, `release/`,
`preparation-report.json`, `RELEASE-NOTES.md` and checksums. `--output-dir` chooses
a new directory under `work/`; `--refresh` replaces only a previously managed
publication copy. Original evidence, local tools, deployed manifests and
installed host binaries are not changed. The preparation command performs no
Git, network, flashing, USB enumeration or transmit operation.

The source export is allowlisted by [publication-manifest.json](publication-manifest.json).
Preparation redacts structured device IDs and known identifiers embedded in
commands/log strings, personal home/workspace paths, and cleanup inventories
in copies. It checks source syntax, documentation links, derived numerical
tables, bundled build-input identities and copied binary hashes. A package
scan also covers nested build archives and ASCII/UTF-16 personal markers.
After packaging, it scans the final ZIPs, filenames, checksums, release notes
and preparation report as well as their unpacked contents.
These checks are scoped checks, not a claim that every binary field is decoded.

The original PAC NV was compared to the pinned SDK template: bytes 2–93651
match, only bytes 0–1 differ, and the additional 37420
bytes are all `FF`. This supports template provenance rather than a device
flash dump. It does not identify every NV field or establish redistribution
rights. Preparation records this comparison when the full local SDK exists.

## Rebuilding after download

For the Windows firmware, install Python 3.10+ and
`python -m pip install -r requirements/build.txt`, then run
`python -B tools/build_firmware.py`. This rebuilds the project AP/CP service
and repackages the retained vendor platform. It does not rebuild the closed
modem/RF/boot/NV. Details: [building.md](building.md).

For Windows receive/Soapy components, install the Ubuntu/WSL packages and run
`python3 -B tools/build_host_components.py --toolchain-root /usr` as described in
[building-wsl.md](building-wsl.md). This needs no original workstation paths.
SDR++ native builds separately require Windows MSVC/SDK and the pinned upstream
source/core; see [host/sdrpp/README.md](../host/sdrpp/README.md).

The retained firmware is a byte-identical v0.1 relabel of the tested release.
`firmware-source-v0.1/` in the prepared source contains its retained 133-file
project source snapshot, kept separate from active source. Two RX profile
files have since changed in active source. New builds are candidates, not
claims of byte-for-byte reproduction or new hardware acceptance.
Host component identities remain individually paired; they must not be flattened
into one directory or supplied with a replacement common `sdr_usb.dll`.

The SDR++ publication plugin copy contains one privacy adjustment: an embedded
UTF-16 local source-path prefix in read-only `.rdata` is replaced with a generic
prefix of the same length. Executable sections, file size and the paired receive
DLL are unchanged. The package manifest and plugin build metadata record the
publication hash and original hash. The source tree's host manifest describes
the retained deployed binaries and deliberately keeps their original identities.
The local plugin and SDR++ installation are not modified. Offline validation
loads the copied DLL with the exact target core and resolves its entry points;
the separate core FFT regression does not constitute a new RF or full plugin
hardware acceptance test. Standalone binary ZIPs refer to the companion source
ZIP for documentation and complete source provenance.

## Remaining release decisions

The owner has requested publication to `https://github.com/xcsilent/UIS8910-SDR.git`,
including the local SDK/compiler inputs and compiled v0.1 firmware/host packages.
Their redistribution terms are still recorded as unresolved in the notices;
including them at the owner's direction does not represent an independent
license determination. Preserve the vendor notices and provenance. Do not infer
that a technical build pass grants redistribution rights.

Only the separate prepared tree is intended for a fresh Git repository. Never
push the research workspace or its Git history. The public repository contains
the sanitized source tree; v0.1 ZIP packages can be attached as GitHub Release
assets with the provided checksums.
Release capabilities retain their measured limitations: receive-only, grid or
conditional RF coverage, partial wideband output, unknown precise lost-sample
positions, uncalibrated gain and no ENOB/sensitivity claim. Original IQ is not
available for replay; final tables remain reproducible from summary metadata.

中文：发布副本与本地研发目录分离，Release 保持各套 DLL 配对，不附带 IQ、
个人路径、设备序列号、聊天记录或旧 Git 历史。本命令仅准备本地文件。
厂商二进制与 ARM 工具链分发依据尚未齐全，不将其写成已获许可。
