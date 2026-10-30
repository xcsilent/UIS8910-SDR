# UIS8910DM SDR

将 **Air724UG / UIS8910DM LTE Cat.1 模组改造成 USB 原始 IQ 接收设备**。

[English](README.md) · [完整技术报告](docs/technical-report.md) · [性能与证据](docs/performance.md) · [目录导航](docs/README.md)

保留厂商启动、RF 初始化和板级 NV/校准，从数字接收链的 RXCAPT 取得解调前 IQ，经 DDR 与 USB 2.0 High-Speed Bulk IN 送到 Windows。无需 SIM、注册网络或蜂窝解调。当前是单通道接收设备，不支持 SDR 发射。

## 已实现的能力

- BW0–BW5、采前频率/增益配置、正常免芯片复位的停止排空和重采。
- 用户只调整中心频率，内部接收路径由 Auto 选择；快速 SDR++ 调频合并到最新请求。
- Windows DLL/CLI/raw、SoapySDR CF32/CS16、SDR++ 原生插件。
- 原生 signed12 数值，little-endian 16+16 存储，每复数样点 4 字节。
- 当前约 30–32 MB/s 实用供给；BW0/BW1 预算可承载，宽档接受部分输出和间隙。
- 10 秒 B210→UIS8910→主机实时 QPSK/OFDM 传输证明。

当前固件以[唯一固件 manifest](outputs/firmware/current/manifest.json)为准，记录为 v0.1（原v32已验证字节）、CP generation `0x526f0501`；主机入口以[host manifest](outputs/host/manifest.json)为准。历史刷写、端口和会话不是实时状态。

## 性能说明

| 项目 | 当前有证据的表述 |
| --- | --- |
| 频率研究包络 | 约 687.5–1000 MHz、1375–2786 MHz；内部是离散点/网格，不承诺连续覆盖 |
| 低频高端 | 970/985 MHz 有成功参考；990 MHz 受条件影响；995/999.9 MHz 未合格，1000 MHz 只是软件包络 |
| 高频网格 | 2000–2390 MHz 步进 10 MHz，40/40 完整通过；2400–2800 MHz 步进 5 MHz，72/81 完整通过，其余分层保留 |
| 名义复采样率 | 1.92 / 3.84 / 7.68 / 15.36 / 30.72 Msps，未作精密时钟校准 |
| 历史相对 −3 dB 通带总宽度 | BW0–BW5 约 1.05–1.10 / 2.75–2.80 / 4.55–4.65 / 9.2–9.4 / 13.6–13.8 / 17.5–18.5 MHz |
| 全量 raw 预算 | BW0 7.68 MB/s；BW1 15.36 MB/s；BW2 30.72 MB/s 缺持续余量；BW3–5 超出当前供给 |
| 未测/未知 | ENOB、噪声系数、绝对灵敏度、SFDR、IIP3、物理调谐极限、精确丢样和绝对时间戳 |

![带宽预算和历史测量](docs/assets/bandwidth-usb.svg)

通带来自不同历史固件和路径的未校准端到端测量，不是所有频点的统一规格。12 位数值不等于 12 位 ENOB；USB 字节一致也不等于采样连续。

## 使用入口

已具备配套固件和主机文件的 Windows 工作站：

```powershell
python -B tools/sdr.py receive --port COM9 --frequency-hz 2300000000 --gain-index 30 --bandwidth-index 0 --milliseconds 10000 --iq-output work/receive.raw --output work/receive.json
```

COM9 仅为示例，运行前核对端口和独占。Python 包装器的 `--iq-output` 是 raw，`--output` 是 JSON；原生 CLI 的参数语义不同，详见[使用指南](docs/getting-started.md)。增益 0–124 是未校准索引，不是 dB。

raw 顺序为 `lane0,lane1`，每个 LE int16 的 bits15:4 保存 signed12，先算术右移 4。主机复数约定为 `(lane0-j*lane1)/2048`；物理 I/Q 命名和绝对相位未确认。没有应用层头、CRC、hash、逐包 ACK 或重传；配置和统计独立。USB 本身的协议校验仍然存在。

## 开源整理边界

当前交付仍依赖厂商闭源启动、RF和校准二进制。源码评审包已包含固定ARM编译器、必要SDK子集和唯一v0.1平台PAC，可在独立Windows目录编译AP/CP并重新打包固件；不是从零重建全部闭源组件。原创代码和文档采用 **GPL-3.0-or-later**，第三方保留原许可；厂商二进制和 ARM 工具链分发条件仍需核实。见[许可范围](LICENSE-STATUS.md)、[第三方来源](THIRD_PARTY_NOTICES.md)和[发布流程](docs/publishing.md)。未上传 GitHub。

按用户新要求，原始 IQ、生成的发送波形和转换副本已清理；最终数值、测试条件、失败结论和少量元数据保留。源码、当前固件、工具链和冻结历史未删除。详见[整理审计](records/maintenance/open-source-preparation-README.md)。

稳定技术结论集中在[完整报告](docs/technical-report.md)、[性能表](docs/performance.md)、[寄存器说明](docs/register-reference.md)和[机器可读能力表](docs/data/sdr-capabilities.json)。后续缺口和改进优先级见[维护者评审](docs/maintainer-review.md)，不自动恢复硬件 Goal。

## v0.1 固件构建

Windows下载源码后运行：

```powershell
python -m pip install -r requirements/build.txt
python -B tools/build_firmware.py
```

ARM编译器及必要SDK子集位于`build-support/`，原完整工具链在本地保留。固件构建不依赖旧版本PAC、旧work目录或历史测试报告。依赖仍含厂商二进制，公开分发前须审核其许可；此处没有上传GitHub。新编译产物未刷入，不冒充既有实测。[构建与验证范围](docs/building.md)。

## WSL 主机组件构建

在 x86_64 WSL2/Ubuntu 内安装依赖，然后从下载的项目根目录执行：

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends \
  python3 cmake ninja-build ca-certificates \
  gcc-mingw-w64-x86-64-posix g++-mingw-w64-x86-64-posix \
  binutils-mingw-w64-x86-64
python3 -B tools/build_host_components.py --toolchain-root /usr
```

一条入口构建 Windows x64 接收 DLL/CLI、调谐计时工具与 Soapy 模块，产物在
`outputs/host/build-v0.1/`，不会替换已安装组件。Soapy0.8.1 固定源码与许可已放入
`build-support/`，无需原 work 目录、历史测试报告或已编译 Soapy SDK。
apt 会安装编译器所需 Linux 动态库；编译不需要 pip、UHD 或连接硬件。
[完整依赖、离线缓存与验证说明](docs/building-wsl.md)。原生 SDR++ 插件另需 Windows
MSVC/Windows SDK 和匹配的 SDR++ C++ ABI，不属于这个 MinGW 构建入口。
