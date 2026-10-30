# Windows 使用与交接

当前唯一部署固件是 `outputs/firmware/current/manifest.json` 指向的 v0.1 PAC（原v32字节不变），CP generation 为 `0x526f0501`，无待刷 PAC。运行时状态仍需现场查询，历史 COM 号、占用和会话不代表实时设备状态。

## 运行前检查

```powershell
python -B tools/sdr.py verify
python -B tools/sdr.py status
python -B tools/debug/uis_debug.py --port COM9 --timeout 5 info
uhd_find_devices --args type=b200,serial=DEVICE_ID_REDACTED
```

COM9 只是最近使用的示例端口。B210 需确认序列号和已验证的 TRX1 映射；当前历史设备记录不能替代查询。

执行环境注意：一次受限环境的`uhd_find_devices`以`0xC0000005`退出，但Windows PnP仍为Started、无残留TX进程，改为较少限制的只读调用后正常发现同一B210。见[对照](../records/communication/representative-postflight.json)。不能单凭受限进程崩溃就要求拔插；先核对枚举、占用和执行权限。该证据支持环境相关原因，尚未定位具体失败API。

## Windows CLI

默认仅设置频率，使用Auto，`--band`只用于具体诊断。普通接收示例：

```powershell
python -B tools/sdr.py receive --port COM9 --frequency-hz 2300000000 --gain-index 30 --bandwidth-index 0 --milliseconds 10000 --iq-output work/receive.raw --output work/receive.json
```

遇到`0x20000005`或`control_device_status=5`，先释放SDR++/Soapy/CLI，只发送一次服务STOP（operation46）并查询。如果STOP成功而仍BUSY，不重复启动接收或TX，明确报告需要USB拔插/重启；它不是RF拒绝。正常停止→排空→改参→重采免芯片复位。

## 10秒实时通信

用户已将本次通信实验收敛为10秒证明无线能力；已收尾，不要求60秒验收。当前源码RX30的OFDM BW0/BW1与QPSK BW0无主机队列丢弃；QPSK BW1可解出零误码载荷但有59.2 MB主机丢弃，只作为有损无线证明。[能力表](status.md)和[交付证据](../records/communication/functional-acceptance.json)分别列质量、获取率、CPU、损失、电平、退出和排空，不宣称所有频点或长期稳定。

省略`--receiver`时读取`outputs/host/manifest.json`的Windows正式程序；默认10秒、RX索引30。使用有限文件自然退出，不用repeat或强杀作为正常收尾。当前TRX1映射为`A:A A:B / channel0 / TX-RX`，端口和序列号必须实时核对。

```powershell
python -B tools/comm_waveform.py --modulation ofdm --sample-rate 3840000 --seconds 10 --output work/comm-ofdm-bw1-10s.fc32
python -B tools/comm_realtime.py --port COM9 --frequency-hz 1900000000 --gain-index 30 --bandwidth-index 1 --duration-s 10 --tx-file work/comm-ofdm-bw1-10s.fc32 --serial DEVICE_ID_REDACTED --tx-gain 65 --modulation ofdm --output work/ofdm-live.json
python -B tools/comm_waveform.py --modulation qpsk --sample-rate 1920000 --amplitude-scale 4 --seconds 10 --output work/comm-qpsk-bw0-10s.fc32
python -B tools/comm_realtime.py --port COM9 --frequency-hz 2700000000 --gain-index 30 --bandwidth-index 0 --duration-s 10 --tx-file work/comm-qpsk-bw0-10s.fc32 --serial DEVICE_ID_REDACTED --tx-gain 65 --modulation qpsk --output work/qpsk-live.json
```

BW0 OFDM改生成采样率为1920000并选择BW0；BW1 QPSK使用3840000生成独立文件，不能只改接收参数套用。只测试USB可持续承载的BW0/BW1。幅度4仅复用已验证2700 MHz参数，不是所有频点默认；无数字削顶不能排除模拟压缩，无同步不自动加电平。

实时解调无需raw文件，`--iq-output`可选；保存在线处理过的数据，主机丢弃会留下同样缺口。USB保持signed12、LE16+16、4 B/复数样点纯raw。OFDM仅对解调副本做FIR33/8192样点连续去DC，FIR16样点延迟计入样点位置，重置后有过渡。队列满时批量丢弃并报告，不阻止设备停止排空。

`completed`表示生命周期完成，不能代替载荷质量、获取率或主机队列结果。`source_file_accounting`以有限源完整帧作分母，不是实际RF发射帧计数；精确样点损失未知。失败频点与旧长测保留在[代表点索引](../records/communication/representative-summary.json)，不继续重复扫描。

## SoapySDR

```powershell
$env:PATH="$PWD\outputs\host\soapy;$env:PATH"
$env:SOAPY_SDR_PLUGIN_PATH="$PWD\outputs\host\soapy"
.\outputs\host\soapy\SoapySDRUtil.exe '--find=driver=uis8910,port=COM9'
.\outputs\host\soapy\SoapySDRUtil.exe '--probe=driver=uis8910,port=COM9'
```

Soapy 用户面只暴露 `antenna=Auto`，调用 `setFrequency` 后由共享表选择内部路径。支持 BW0–BW5 名义采样率 1.92/3.84/7.68/15.36/30.72 Msps；BW4/BW5 同名义速率，BW5 通过 `bw_mode=5` 区分。

## SDR++ 便携版

项目发布插件是 `outputs/host/sdrpp/uis8910_source.dll`。便携版 `D:\Tools\sdrpp_windows_x64` 的插件及配对`sdr_usb.dll`已同步并核对哈希，旧文件/配置已备份。与安装文件同字节的隔离核心完成BW0/RX30接收、9次Auto频率请求及停止排空，见[安装与实机证据](../records/host/sdrpp-portable-release-delivery-20261030.json)。用户原配置内容保留；不新增RF覆盖或桌面视觉结论。正常启动`sdrpp.exe`，Source选UIS8910，COM填现场端口；只设置频率，内部Auto选路。其他消费者须释放设备。

## 构建

Windows 主机库和 Soapy 使用 WSL MinGW，SDR++ 使用项目内 MSVC 工具链：

```powershell
wsl.exe bash -lc 'cd C:/Projects/UIS8910-SDR && python3 -B tools/build_host.py --output-dir outputs/host/windows-current-rebuild --unrestricted-frequency'
wsl.exe bash -lc 'cd C:/Projects/UIS8910-SDR && python3 -B tools/build_soapy.py --host-dir outputs/host/windows-current-rebuild --output-dir outputs/host/soapy-candidate --build-dir work/soapy-candidate'
python -B tools/build_sdrpp.py --host-dir outputs/host/windows-current-rebuild --output-dir outputs/host/sdrpp-candidate --build-dir work/sdrpp-candidate
```

`windows-current-rebuild` 是独立构建候选；只有检查通过后才复制到正式目录并更新 `outputs/host/manifest.json`。固件 PAC 仍由用户手动刷入，当前无待刷候选。

新使用者见[中英文使用入口](getting-started.md)，完整依赖与AP/CP绑定见[构建说明](building.md)。本地verify不是实时查询，新克隆缺SDK/PAC/work时不能声称完整构建通过。原始IQ与生成波形已按用户要求清理，通信复现需重新生成有限源；最终结论保持不变。

关键证据：

- [当前能力表](status.md)
- [当前主机 manifest](../outputs/host/manifest.json)
- [当前固件 manifest](../outputs/firmware/current/manifest.json)
- [B40 覆盖汇总](../records/rf/coverage-b40-grid-2400-2800-summary.json)
- [项目整理复盘](../records/maintenance/2026-10-29-project-review-README.md)
