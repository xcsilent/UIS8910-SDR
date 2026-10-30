# v0.1 release and independent build / 版本与构建收敛

The owner requested one firmware version (v0.1), removal of historical firmware
artifacts, retention of local build tools and a buildable downloaded source tree.
No hardware access, flash, GitHub upload or license selection is part of this task.

The v0.1 release PAC is byte-identical to the recorded deployed v32 PAC:
`a6a4930aca39ed38c524c09000cd12251fa3fe981eca63cb917461b42cb7527b`.
Its CP generation remains `0x526f0501`. Historical records keep original labels;
the release consolidation is not a new RF/USB hardware pass.

Current build entry: `python -B tools/build_firmware.py`. It compiles AP/CP and
packages a new PAC using pinned archives under `build-support/` and the sole
v0.1 vendor platform container. No old seed PAC, old work directory, historical
60s report or original SDK ELF is a build prerequisite. All original full local
SDK/toolchain trees are retained; the smaller dependency archives travel with
the local buildable source review copy.

The first compile completed successfully with a15,572 B CP resident and2852 B
control, mailbox `0x80f24780`, RAM end `0x80f69de0`. Current shared profile source
changes since the recorded firmware mean the rebuilt PAC is not assumed to have
the old hardware evidence. New output remains explicitly unflashed.

The cleanup audit (local-only research reference, omitted: `release-v0.1-firmware-cleanup.json`) confirms7,732 removed files,
1,119,972,325 bytes. Release directories now contain only `current/` and `v0.1/`.
Historical project releases, seed PAC and obsolete AP/CP build payloads were
removed; small final records/research source remain. Vendor SDK distribution
PACs embedded in complete reference SDK archives are inputs, not retained project
release versions, and were preserved with the local SDK/tool trees.

The [independent build verification](release-v0.1-independent-build-verification.json) passed
from `work/github source v0.1`, a source copy with spaces in its root path and no
original SDK, archive or old work directory. It unpacks and uses its own compiler
and SDK bundle. Command paths stay inside that copy. Packaged CP blobs match the
linked ELF; vendor payloads are unchanged, AP-system differences are limited to
the two hooks and container CRC. It generated exactly the same PAC as the first
build: `cdbce34e12500ab057a2bf1b4ba06d2ab146668d76cfe683f58ea1a311d037a7`.
ELF debug paths differ; the flashable PAC is byte-identical across directories.

The final build is retained in `work/build-v0.1`. Its PAC matches the independent
copy byte-for-byte. Targeted ARM emulation passed against this final build:

- [USB descriptors and control](release-v0.1-ap-usb-arm.json):24 compiled ARM cases.
- [AP service](release-v0.1-ap-service-arm.json): six-slot worker, three modeled sessions,
  configuration, scheduler and failure/ownership handling.
- [CP control](release-v0.1-cp-batch-arm.json): mailbox/ring/export and modeled stop faults.

OS/UDC/CP/peripheral models do not prove physical DMA/cache timing or RF reception.
The [toolchain inventory](release-v0.1-retained-toolchains.json) records preserved local tools.

The same installed Python/pyelftools was used; a pristine OS/Python install and
GitHub CI have not been tested. Optional Soapy/SDR++ build bootstraps retain their
separate prerequisites. New output is **not flashed or hardware-qualified**.

The export is local review material; vendor/SDK/compiler redistribution and
original-code licensing still need review before public release. Complete local
ARM/MinGW/Soapy/MSVC tool trees remain preserved. [Build instructions](../../docs/building.md).

[Final verification summary](release-v0.1-verification-summary.json) records the build,
cleanup, current ARM regressions, portable checks and disclosed limitations.
`sdr.py verify` passed identities/links; old evidence remains stale or
unverifiable where authorized removals retired its inputs. It is not a new
hardware result.
