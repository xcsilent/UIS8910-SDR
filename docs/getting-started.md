# Getting started / 使用指南

This guide assumes an Air724UG/UIS8910DM with a compatible receive-service firmware and a Windows x64 host. A stock LTE modem is not automatically a USB SDR. The release is v0.1 (unchanged tested runtime). Firmware can be rebuilt in Windows from the included pinned inputs; public redistribution/licensing remains subject to review. See [building](building.md) and [license status](../LICENSE-STATUS.md).

## 1. Prerequisites and device identity

| Component | Required for |
| --- | --- |
| Matching PAC and AP/CP service | RXCAPT and USB streaming; manual flash using the board's supported tooling |
| Windows x64 / WinUSB interface | native receive library; vendor COM control remains available |
| Python and `requirements/host.txt` | Python command wrapper and serial discovery |
| Paired native host DLL/EXE | selected by `outputs/host/manifest.json` |
| SoapySDR0.8.1 or the pinned SDR++ portable build | optional SDR application interface |
| B210 / UHD | only for intentional RF reference/communication experiments, not normal reception |

Do not infer device availability from old records. Close SDR++/Soapy/CLI consumers before opening another. The supported host is single-device/single-RX. A Linux-native device driver has not been delivered; WSL is used for parts of the build.

```powershell
python -m pip install -r requirements/host.txt
python -m serial.tools.list_ports -v
python -B tools/debug/uis_debug.py --port COM9 --timeout 5 info
```

`COM9` is an example. `python -B tools/sdr.py status` prints stored project status, **not live device state**. `verify` checks retained local artifacts, not a USB connection. Driver binding uses WinUSB GUID `{5D6BCE91-4F8A-4D42-9A0D-A9E6F8AC8910}` and recorded VID/PID1782:4e00; the runtime discovers the relevant vendor Bulk IN interface. Do not rebind every composite-device interface or hardcode an endpoint from an old experiment. `tools/usb/bind_winusb.py` defaults to inspection; check its help before an intentional installation.

## 2. Ten-second raw capture

Use a new output filename. Start with BW0 and an explicit RX gain index30:

```powershell
python -B tools/sdr.py receive --port COM9 --frequency-hz 2300000000 --gain-index 30 --bandwidth-index 0 --milliseconds 10000 --iq-output work/receive.raw --output work/receive.json
```

Auto chooses an internal RF route. A successful data transfer does not itself establish that an identifiable RF signal was received. Gain index0–124 is not calibrated dB or an established RF AGC setting. BW0 nominalFs=1.92 Msps,4 B/complex; a10 s raw budget is76.8 MB, but missing bytes/intervals and startup/tail must be interpreted from statistics.

| Entry | Raw output | Report output |
| --- | --- | --- |
| `python tools/sdr.py receive` | `--iq-output` | `--output` JSON |
| Native `sdr_receive.exe` | `--output` | stdout JSON |
| Native `sdr_receive.exe --stdout-raw` | stdout binary only | stderr JSON |

Do not pipe binary stdout through a PowerShell text pipeline. Use the Python real-time consumer or a binary-safe process reader. The raw format is explained in the [README](../README.md) and [report](technical-report.en.md). Keep a report beside each future capture: raw alone contains no frequency/Fs/gap metadata.

Check device-completed, host-received, consumer-written bytes, queue drops, session/control/cleanup errors and `drained` separately. A zero byte difference is not proof of continuous sampling. Normal stopping drains the device; do not unplug as the routine STOP mechanism.

## 3. SoapySDR

The retained host release contains SoapySDR0.8.1 and its UIS8910 module. The following discovery/probe calls can open control interfaces; release other consumers first:

```powershell
$env:PATH="$PWD\outputs\host\soapy;$env:PATH"
$env:SOAPY_SDR_PLUGIN_PATH="$PWD\outputs\host\soapy"
.\outputs\host\soapy\SoapySDRUtil.exe '--find=driver=uis8910,port=COM9'
.\outputs\host\soapy\SoapySDRUtil.exe '--probe=driver=uis8910,port=COM9'
```

Discovery/probe is not a capture command. An application using the matching Soapy runtime opens `driver=uis8910,port=COM9`, sets RX0 frequency and sample rate, calls `setupStream` withCF32 orCS16, then `activateStream/readStream/deactivateStream`. Only `antenna=Auto` is exposed. Set gain via `writeSetting("gain_index","30")`.

BW0/1/2/3 nominal rates are1.92/3.84/7.68/15.36 Msps. BW4 andBW5 both use30.72 Msps; BW5 requires `writeSetting("bw_mode","5")` after selecting the rate. `getBandwidth` returns0 and there is no independent analog-filter-width control. CF32 follows `(lane0-j*lane1)/2048`; stream calls must be serialized by the consumer. See [Soapy implementation](../host/soapy/README.md).

## 4. SDR++ native source

The native DLL calls the Windows library directly and does not require SoapySDR. It is built for a pinned SDR++ core, not every1.3.x binary. The local portable target is `D:\Tools\sdrpp_windows_x64`; exact source/core identities are in [notices](../THIRD_PARTY_NOTICES.md) and the [host manifest](../outputs/host/manifest.json).

With SDR++ closed, inspect an installation plan:

```powershell
python -B tools/install_sdrpp.py --sdrpp-root D:\Tools\sdrpp_windows_x64
# Apply intentionally after reviewing the plan; backs up old files/configuration
python -B tools/install_sdrpp.py --sdrpp-root D:\Tools\sdrpp_windows_x64 --apply
```

Start `sdrpp.exe`, select sourceUIS8910, enter the actual COM port, chooseBW0 and gain index30, set the center frequency and press Play. Internal routes are hidden. Frequency/gain requests are coalesced by the worker; switching sample-rate mode requires stopping first. Rapid dragging can postpone restart until the latest request settles. Do not expect continuous phase or zero retune gap.

Wideband FFT pacing helps partial-output modes, but large FFT windows across missing segments may show artifacts. Desktop visual acceptance was explicitly removed from project requirements; existing core/dataflow evidence is not presented as a measured desktop refresh rate. See [plugin details](../host/sdrpp/README.md).

## 5. Troubleshooting without repeated resets

| Symptom | Useful action |
| --- | --- |
| COM/WinUSB open fails | release other consumers; confirm actual interface/driver and identity |
| BUSY (`0x20000005` / control status5) | issue one supported STOP/status query; if successful STOP still leavesBUSY, stop retrying and report the state |
| Waterfall pauses while dragging | allow the latest120 ms request to settle; verify applied status and drain errors; use the paired plugin/runtime |
| No reference tone | check route/setup, frequency tracking and overload; a raw stream alone is not RF validation |
| Wide mode loses data | expected when native raw budget exceeds USB; do not change the reportedFs to average delivered bytes |
| Source capture file missing | old payloads were intentionally deleted; read final reports or reacquire, never substitute a different sample file |

If recovery requires physical reconnection, keep the failure/status report first. Do not repeat unchanged failed start/TX attempts. B210 is not needed for USB troubleshooting.

## 6. Reference and communication experiments

The documented10 s QPSK/OFDM demonstrations are complete; normal use does not require retransmitting them. Reproduction commands and source generation are in [Windows handoff](windows-handoff.md). Waveform files were removed as intermediates and can be generated again. Each finite TX must exit and release UHD before another starts. Record TX gain **and source amplitude**, RX gain and sampled near-rail/RMS; no digital clipping does not rule out analog compression. Historical gain65 is a UHD setting, not measured output power.
