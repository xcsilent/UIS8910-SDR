# WSL host builds / WSL 主机组件构建

中文快速说明：在 x86_64 WSL2/Ubuntu 安装下面的 apt 包，在下载的项目根目录执行
`python3 -B tools/build_host_components.py --toolchain-root /usr`。
它会生成 Windows 接收库/CLI、调谐工具与 Soapy 模块。Soapy 固定源码随项目提供，
无需原电脑的 work 目录或历史测试报告；MinGW 和它所需 Linux 运行库由 apt 安装。
原生 SDR++ 插件单独使用 Windows MSVC 工具链。

This recipe builds **Windows x64** `sdr_usb.dll`, `sdr_receive.exe`, the timing
CLI and the UIS8910 SoapySDR module from a GitHub clone or downloaded source ZIP.
It does not need a connected UIS8910, B210, firmware SDK, original `work/`
directory, historical experiment records or Windows Python packages.

## 1. WSL and Ubuntu packages

Use x86_64 WSL2/Ubuntu. The local verification environment is Ubuntu26.04;
Ubuntu24.04 is the CI target. ARM64 WSL/cross-host toolchains have not been
validated. Python3.10+ is required.

If WSL is not already installed, run in Windows PowerShell and complete Ubuntu's
first launch/user setup:

```powershell
wsl --install -d Ubuntu-24.04
```

Inside the Ubuntu terminal, install build dependencies once:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends \
  python3 cmake ninja-build ca-certificates \
  gcc-mingw-w64-x86-64-posix g++-mingw-w64-x86-64-posix \
  binutils-mingw-w64-x86-64
```

| Dependency | Use / dependency resolution |
| --- | --- |
| Linux Python3.10+ | runs the standard-library-only host builders; no pip packages needed for compilation |
| POSIX MinGW GCC/G++ | compiles C/C++ for Windows x64; `-posix` selects threading support used by Soapy and queues |
| MinGW headers/import libraries and runtime | Windows/WinUSB/SetupAPI headers, `libwinpthread-1.dll`; apt installs them through the compiler packages |
| MinGW binutils | assembler/linker, resource compiler, PE/DLL inspection |
| CMake + Ninja | builds the pinned upstream SoapySDR library and utilities |
| Linux compiler runtime libraries | glibc, `libgcc-s1`, `libstdc++6`, `libgmp10`, `libmpfr6`, `libmpc3`, `libisl23`, `zlib1g`, `libzstd1`; apt resolves the versions required by the installed compilers |
| `ca-certificates` | trusted downloads during environment setup |
| Git | optional for cloning; unnecessary when the project was downloaded as ZIP |

The source package contains [SoapySDR0.8.1 upstream source](../build-support/README.md)
at commit `1cf5a539a21414ff509ff7d0eedfc5fa8edb90c6`, including its Boost license.
It is compiled for Windows, so **do not substitute Ubuntu's Linux
`libsoapysdr-dev`**. UHD, SWIG, Python bindings, numpy and pyserial are not needed
to compile these host components. They have separate runtime/experiment roles.

## 2. Build from a downloaded source tree

Change to the project root in the Ubuntu terminal. For a Windows directory,
use its WSL path; quote paths containing spaces. The example drive/path is not
hard-coded by the builders:

```bash
cd '/mnt/d/Downloads/UIS8910DM'
python3 -B tools/build_host_components.py --toolchain-root /usr
```

The explicit `/usr` selects the packages installed above. Without that option,
the builder first uses retained tools under `work/windows-toolchain`, then
MinGW on PATH; if neither exists, the preparation script can download/extract
the seven compiler/header/runtime `.deb` packages into `work/` without sudo.

Default results:

```text
outputs/host/build-v0.1/
  build.json                      build identity and PE/import checks
  windows/
    sdr_usb.dll
    sdr_receive.exe
    libsdr_usb.a
  tune/
    sdr_tune_benchmark.exe
    sdr_usb.dll
  soapy/
    uis8910Support.dll
    libSoapySDR.dll
    libwinpthread-1.dll
    sdr_usb.dll
    SoapySDRUtil.exe
    soapy_receive_probe.exe
    SoapySDR-LICENSE.txt
work/wsl-host-v0.1/
  build.log
  commands.json
  soapysdr/                       pinned source and independently built SDK
  soapy-module/queue-test.exe      offline numeric/queue regression
```

Keep each output folder's DLLs together. The builder checks Windows x64 PE
architecture and that non-system DLL imports are present beside each executable.
Compilation does not enumerate USB devices or open COM ports, and does not
replace `outputs/host/manifest.json` or any deployed host component.

Outputs must be new directories. For another build:

```bash
python3 -B tools/build_host_components.py --toolchain-root /usr \
  --output-dir outputs/host/build-check --build-dir work/wsl-host-check
```

`--without-soapy` builds the receive DLL/CLI and timing CLI without CMake/Ninja.
`--jobs 3` controls Soapy compile parallelism. Manual component entries remain
available in [building.md](building.md), but the combined entry prepares and
pairs their paths automatically.

## 3. Existing local/offline toolchains

Full local tools remain retained. Verify a prepared prefix without downloading:

```bash
python3 -B tools/usb/prepare_host_toolchain.py --check
python3 -B tools/usb/prepare_host_toolchain.py --system --check
```

The first form uses local tools before PATH; the second explicitly checks `/usr`.
An alternate prefix can be selected with `--toolchain-root /path/to/usr` or
`UIS8910_MINGW_ROOT`. A compiler for Windows itself (`*.exe`) cannot run as the
Linux MinGW compiler in this recipe.

The local `.deb` cache is retained at `work/windows-toolchain/packages` and is not
part of the public source package. For a distro-matched complete offline cache:

```bash
python3 -B tools/build_host_components.py --package-dir /path/to/mingw-packages
```

Do not mix Ubuntu release/version sets. This path still needs the Linux runtime
libraries, Python, CMake and Ninja installed. The seven cache packages are
`gcc-mingw-w64-x86-64-posix`, `g++-mingw-w64-x86-64-posix`,
`gcc-mingw-w64-x86-64-posix-runtime`, `gcc-mingw-w64-base`,
`binutils-mingw-w64-x86-64`, `mingw-w64-x86-64-dev`, `mingw-w64-common`.

Soapy's small source archive is bundled and checked; its prepare step needs no
Git/network. It can be checked from Windows or Linux without extraction:

```text
python3 -B tools/usb/prepare_soapy_sdk.py --check-source
```

## 4. Windows offline checks and CI

After compilation, run from Windows PowerShell in the same source tree:

```powershell
python -B tools/verify/verify_soapy.py --area outputs/host/build-v0.1/soapy --queue-test work/wsl-host-v0.1/soapy-module/queue-test.exe --output work/host-build-offline.json
```

Without `--hardware` this checks numeric conversion/queues and creates a Soapy
object using COM999 for offline capability queries; it does not open the port.
The source's `--capabilities` contract must pass, not merely DLL linking. Device
streaming and new binaries' hardware acceptance are separate from compilation.

GitHub Actions includes an Ubuntu24.04 cross-build job using the same command,
plus a Windows job that runs the produced queue/capability checks. The local
independent-copy evidence is recorded in [the final WSL build reports](../records/maintenance/host-build-wsl-README.md). The regenerable independent copy was removed after verification; the main local toolchain and package cache are retained.
A configured workflow is not a claim that GitHub has already executed it.

## 5. Troubleshooting and SDR++ scope

| Failure | Action |
| --- | --- |
| `python3` resolves to Windows Python | use `/usr/bin/python3` in the Ubuntu terminal; the host builder requires Linux Python |
| no MinGW candidate/package | run apt update and ensure the distribution's `universe` repository is enabled |
| compiler reports missing `.so` | install the compiler through apt to resolve its Linux runtime dependencies, or install those matching the offline `.deb` set |
| CMake rejects pre-3.5 compatibility | the Soapy preparation command supplies `CMAKE_POLICY_VERSION_MINIMUM=3.5` for recent CMake; use the project entry |
| previous output/build directory exists | choose new paths; do not overwrite an installed CLI/DLL or reuse a relocated CMake cache |
| module cannot load in another Soapy application | use a matching Windows x64 Soapy0.8 ABI and keep dependency DLLs on PATH |

The native SDR++ module has a separate **Windows MSVC/Windows SDK/C++ ABI**
toolchain and pinned SDR++ core/source requirements. It is not built by the
WSL/MinGW recipe; see [SDR++ build notes](../host/sdrpp/README.md). Existing local
MSVC/SDR++ files are preserved. These WSL checks must not be described as a new
SDR++ native-module or RF hardware pass.
