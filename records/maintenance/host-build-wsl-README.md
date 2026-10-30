# Independent WSL host build verification

Date:2026-10-30. Scope: downloadable source dependencies, Windows cross-build,
PE/runtime closure and Windows offline startup/API checks. No hardware was
enumerated, no COM port opened, no transmission, flash or installed host
component replacement occurred.

## Method and result

The allowlisted export was copied to `work/wsl host source check`, deliberately
using a path with spaces. It had no original toolchain, Soapy SDK, `inputs/` or
`archive/` tree. The new preparation command extracted the retained seven-package
Ubuntu26.04 MinGW cache into that copy's own `work/`. Linux runtime libraries,
Python3.14.4, CMake4.2.3 and Ninja1.13.2 came from the installed WSL environment.
This tests offline cache bootstrap, not a clean Ubuntu system installation.

```bash
python3 -B tools/build_host_components.py \
  --package-dir C:/Projects/UIS8910-SDR/work/windows-toolchain/packages
```

The combined command compiled the receive DLL/CLI, timing CLI, bundled upstream
Soapy0.8.1 SDK, UIS8910 module, capability probe and numeric queue test.
Twelve delivered artifacts were produced, including10 PE DLL/EXE files; all
were Windows x64 with complete non-system import dependencies in their folders.
The Soapy license and Windows pthread runtime were copied with the outputs.

The new Windows binaries passed all4096 signed12 conversion cases, CF32/CS16
conjugation, byte fragmentation, queue/drop/wrap/tail checks and the Soapy API
capability contract. The receive and timing CLIs loaded their paired DLLs and
returned expected usage/exit code2 without opening hardware.

## Retained evidence and limits

- [Independent verification](host-build-wsl-independent-build-verification.json): environment,
  build command, actual input hashes and offline startup results.
- [Combined PE/import build report](host-build-wsl-cross-build.json), [receive build](host-build-wsl-windows-build.json),
  [Soapy module build](host-build-wsl-soapy-build.json), [toolchain package versions/hashes](host-build-wsl-toolchain.json).
- [Windows queue/API results](host-build-wsl-windows-offline.json).
- [Current project verification](host-build-wsl-project-verification.json) records structural
  checks separately from the age or availability of historical RF evidence.

The independent copy and its regenerable build outputs were removed during the
2026-10-30 directory consolidation after these final reports were retained.
The original bootstrap used `outputs/host/build-v0.1/` and `work/wsl-host-v0.1/`.
The final-source rerun used
an explicit prepared prefix with `outputs/host/verified-v0.1/` and
`work/wsl-host-verified/`; exact commands/hashes are in the verification JSON.
Those outputs were candidates, not the installed host manifest's binaries.
The main MinGW/Soapy toolchains and package cache remain available for rebuilding.
Source changes need fresh build evidence.
Original RF/USB performance records do not become measurements of these binaries.

The [WSL guide](../../docs/building-wsl.md) lists the recommended apt-installed
toolchain recipe. Ubuntu24.04 cross-build/Windows offline jobs are configured
in GitHub Actions; their presence is not a remote CI run. Native SDR++ MSVC/core
ABI bootstrap and hardware streaming are outside this check.
