# Pinned build inputs / 固定构建依赖

This directory makes the Windows firmware build independent of the original
workstation's SDK checkout, `work/` outputs, historical PAC versions and PATH.
Python3.10+ and `requirements/build.txt` are the only separately installed
firmware-build prerequisites. These are local publication-review inputs;
no upload or new license grant has occurred.

| Input | Contents | Source |
| --- | --- | --- |
| `uis8910-sdk.zip` |266 files: API/RIL sources, headers, linker scripts, vendor `core_stub.o` and newlib libraries | hotelec RDA8910_CSDK commit `585a0c8352cf3937a32b63f638fabe767d0ca28c` |
| `arm-gcc-7.2.1-win32.zip` | selected GCC7.2.1 compiler/binutils, ARM headers and required soft/hard-float libgcc variants | same SDK's `prebuilts/win32/gcc-arm-none-eabi` |
| `soapysdr-0.8.1-source.zip` |101 tracked upstream files including Boost1.0 license; no build cache | SoapySDR commit `1cf5a539a21414ff509ff7d0eedfc5fa8edb90c6` |
| [Platform configuration](../firmware/platform/air724ug.json) | AP/CP mailbox, generation, verified UDC addresses/prefixes, explicit source lists | current linked service and SDK/PAC comparison |
| [v0.1 PAC](../outputs/firmware/v0.1/Air724UG_SDR_v0.1.pac) | only retained project firmware release; vendor platform, RF observer and board NV preserved during rebuild | byte-identical consolidation of previously deployed firmware |

`manifest.json` records every archive member's SHA256/length and each archive's
SHA256. `python -B tools/prepare_build.py` validates and expands them into
`work/build-deps/`; `--check` validates without extraction. Modified cache files
are rejected rather than silently overwritten. CMake/Ninja, WSL and an SDK symbol
ELF are unnecessary for this firmware recipe. These are build-input integrity
checks, not IQ data processing.

`host-manifest.json` separately pins the Soapy archive and every source member.
`python -B tools/usb/prepare_soapy_sdk.py --check-source` verifies it without
extracting or requiring WSL. The host build compiles it for Windows from source.
The Linux MinGW compilers, CMake, Ninja and their Linux runtime libraries are
installed through Ubuntu packages (or a distro-matched local cache); they are
not part of the Windows ARM compiler ZIP. Exact packages and a single combined
build command are in [WSL host builds](../docs/building-wsl.md). The workstation's
full cached `.deb` set and tools remain under `work/windows-toolchain/`.

AP uses Cortex-A5 Thumb hard-float (`neon-vfpv4`); CP resident/control and the
agent use soft-float. The explicit linker recipe preserves vendor library order
and validates the actual AP mailbox and reserved memory before PAC generation.

The complete original SDK, ARM tools, local MinGW, Soapy and MSVC/Windows SDK
trees remain on the workstation. They are useful for analysis and optional host
builds and are not obsolete firmware versions. The reduced archive does not
include debugger binaries or every CPU multilib variant.

Before public distribution, review [third-party notices](../THIRD_PARTY_NOTICES.md)
and [license status](../LICENSE-STATUS.md). The SDK root's GPL text does not clear
every vendor header, binary or NV item. Compiler corresponding-source/notices
obligations also need review. Technically buildable and legally cleared are
separate recorded states.
