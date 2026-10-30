# 当前能力与缺口

本页是历史部署/测量状态，不是实时查询；当前Goal已清除。本轮只做开源整理。面向读者的收敛结论见[性能页](performance.md)与[完整报告](technical-report.md)。原始IQ已按用户要求删除，最终数值/条件保留；旧报告不能直接重算。

当前发布统一为 **v0.1（原v32已验证字节，统一手动频率解限）**，配对 CP generation `0x526f0501`，见[部署和RF证据](../records/rf/coverage-v32-deployment.json)。这是用户刷写确认、运行时generation与采集验证，不是整片 Flash 读回。部署入口以[current manifest](../outputs/firmware/current/manifest.json)为准；端口、占用和硬件状态仍须实时查询。

## 接收与软件

- 最新RF网格：B40/BW0在2400–2800 MHz按5 MHz步进完成81点测试，72点完整通过，2435/2440 MHz按用户要求作为环境影响下通过。高端细化2786 MHz完整通过，2787–2789 MHz参考跟随可见但突出度退化；2800 MHz在B40/B41均有TX相关响应，但频率跟随失准，未作为合格接收交付。它们是现有天线条件下的网格与质量证据，不是芯片物理上限或整个区间逐Hz证明。[测量汇总](../records/rf/coverage-b40-grid-2400-2800-summary.json)。

- 当前主机交付已将B3默认/Auto请求包络扩至1375–1920 MHz，共用C表生成Windows/Soapy/SDR++配置。SDR++核心 BW0–BW5、Auto往返和停止排空，Soapy CF32/CS16 BW5、Auto改频和停止排空均有实机证据。便携版 `D:\Tools\sdrpp_windows_x64` 的插件及配对运行库已与发布目录同步，另补BW0/RX30真实核心接收、9次Auto请求及停止排空，[安装与回归](../records/host/sdrpp-portable-release-delivery-20261030.json)保留哈希及备份。射频依据仍是B210离散参考点，不能把软件包络当连续覆盖。

- BW0–BW5、采前频率/增益配置、停止排空后重采已有实机证据；正常操作免芯片复位。宽档允许丢块及间隙，不保证样点或相位连续。
- Windows DLL/CLI、内存接收、raw写盘、Soapy CF32/CS16及SDR++原生插件已有真实数据流验证。[交付入口](../outputs/host/manifest.json)、[Soapy当前 BW5](../records/host/soapy-current-hardware-auto-b3-bw5.json)、[SDR++当前 BW0–BW5](../records/host/sdrpp-current-hardware-auto-b3-bw0-5.json)。
- 当前发布 Windows CLI 的 B3 Auto 1375 MHz BW0 已完成 10 秒和 60 秒持续采集；60 秒设备供给 7.680 MB/s、主机接收 7.658 MB/s，设备排空成功。设备与主机差额按 raw 传输约束记录，丢失位置未知，见[10秒](../records/rf/coverage-current-windows-cli-b3-1375-10s.json)和[60秒](../records/rf/coverage-current-windows-cli-b3-1375-60s.json)。
- 当前发布 Windows CLI 的 B8 Auto 942.5 MHz BW0 已完成短采集，设备与主机均完成 7,667,712 字节，差额为零并成功排空，见[B8实机证据](../records/rf/coverage-current-windows-cli-b8-9425.json)。
- B5 942.5 MHz 的普通请求会被标准软件包络拒绝；使用显式 `--unrestricted-frequency` 后底层 BW0 采集、数据回传和停止排空成功，见[B5解限路径证据](../records/rf/coverage-current-windows-cli-b5-9425-unrestricted.json)。该结果证明软件限制与底层请求能力不同，不等同于该频点已完成外部参考接收验证。
- 当前发布 Windows CLI 的 B40 Auto 2300 MHz BW0 采集与排空通过，设备与主机差额为零，见[B40链路证据](../records/rf/coverage-current-windows-cli-b40-2300.json)。该记录只证明路由和 USB 数据链，不替代外部参考 RF 验证。
- v30已补[Soapy CF32/CS16 Auto](../records/host/soapy-v30-auto-route.json)及[真实SDR++核心BW0快速混合调参/Auto/重叠边界](../records/host/sdrpp-v30-retune-auto.json)回归，均停止排空。项目交付包含用户认可的快速调参恢复行为；便携插件已同步当前发布文件，保留其配对DLL。Windows实时接收器独立晋升，不替换其他消费者的DLL；不新增RF覆盖或桌面验收结论。
- SDR++便携版在 `D:\Tools\sdrpp_windows_x64`；当前核心协议、真实数据流、快速改频和停止排空均已通过。快速调参卡住已由用户确认解决，异常驱动取消的固定时间上限仍未知。
- raw两路交错little-endian int16，每路signed12位于bits15:4，每复数样点4B；解码先算术右移4。主机正频率约定 `(lane0-j*lane1)/2048`，物理I/Q命名与ENOB未确认。
- IQ数据面无应用层头、CRC、内容哈希、逐包ACK或重传。采集DMA写DDR、UDC DMA读同一缓冲，保留cache、长度、完成及所有权检查。配置与统计独立。

## 带宽与采样率

| 档位 | 名义复采样率 Msps | 全量4B预算 MB/s | 历史实测相对−3dB总宽度 MHz |
| --- | ---: | ---: | --- |
| BW0 | 1.92 | 7.68 | 1.05–1.10，B5 |
| BW1 | 3.84 | 15.36 | 2.75–2.80，B5 |
| BW2 | 7.68 | 30.72 | 4.55–4.65，B5 |
| BW3 | 15.36 | 61.44 | 9.2–9.4，B5 |
| BW4 | 30.72 | 122.88 | 13.6–13.8，B5 |
| BW5 | 30.72 | 122.88 | 17.5–18.5，B40 |

通带是不同历史固件/路径的未校准端到端测量，包含调谐、模拟和数字链路，不能当所有路径、中心频率或v30的统一规格。名义采样率不代替精密时钟校准，字节吞吐不代替RF带宽。[BW0/1细化](../records/rf/bw01-summary.json)、[BW2](../records/rf/mainline-bw2-passband-refined.json)、[BW3/4](../records/rf/wideband-passband-fft-summary.json)、[BW5](../records/usb/geometry-v20-bw5-passband-summary.json)。BW6/7无新增通带证据，已按用户要求收尾。

## USB供给、损失与调度

USB High-Speed Bulk，最大包512B，Windows默认32个64KiB异步读；六个8192B输出槽，宽档允许成对scratch丢弃。自动等待BW0/1=250µs、BW2–BW5=100µs，burst0。手动覆盖持续到显式恢复自动。

v29 B8/880MHz各10秒稳态：[BW0](../records/usb/b8-880-bw0-10s-v29-20261029.json)7.680、[BW1](../records/usb/b8-880-bw1-10s-v29-20261029.json)15.360、[BW2](../records/usb/b8-880-bw2-10s-v29-20261029.json)30.35MB/s。各3秒：[BW3](../records/usb/b8-880-bw3-3s-v29-20261029.json)31.55、[BW4](../records/usb/b8-880-bw4-3s-v29-20261029.json)31.60、[BW5](../records/usb/b8-880-bw5-3s-v29-20261029.json)31.94MB/s。宽档是部分供给，不是完整实时传输。

v30 B40/2300MHz短测：[开启统计](../records/usb/v30-refill-bw5-profiled.json)30.30、[关闭统计](../records/usb/v30-refill-bw5-unprofiled.json)31.04MB/s，两次排空，设备/主机尾差40/24KiB；单次顺序对照不能确定稳定开销。[时间线](../records/usb/v30-refill-timeline.json)仅最近24次，多数成功事件首次worker观察时已有新数据且operation14待完成；不是全会话分布或CP执行时间。[25µs短轮询](../records/usb/v30-refill-burst25-capture.json)30.43MB/s，未见明确收益，[已恢复自动](../records/usb/v30-refill-burst25-auto.json)并关闭统计。

历史v27 BW2 60秒稳态30.589MB/s并排空，scratch丢弃964完整对；[长采](../records/usb/scheduler-wide-deployment.json)。[BW2写盘10秒](../records/usb/scheduler-wide-bw2-file-10s.json)文件305,856,512B，写队列丢弃0，设备/主机尾差16KiB。这些不冒充v30长采。

设备完成量、主机接收量、文件/消费者量分别报告。字节一致不证明无采集间隙，scratch计数不等于总丢样；精确丢样数与位置未知。主机CPU、完成等待和调度tick均不代表设备CPU；应用队列耗空区间不是物理USB空闲时间。约30–32 MB/s作为当前实用供给基线，本轮优化已收口；未证明硬件物理上限，见[USB计划](plans/usb-raw-stream.md)。

## RF覆盖与外部前端

### 用户可见的合并频率范围

用户只设置中心频率，内部接收路径由 Auto 自动选择。当前首版用户范围合并为：

| 用户可调范围 | 当前说明 |
| --- | --- |
| 约 687.5–1000 MHz | 已有低频参考和采集证据；880–910 MHz 与 920–940 MHz 的路径交接已验证 |
| 约 1375–2786 MHz | 已有低频代表点、1900–1990 MHz 重叠对照和 2000–2786 MHz 高频网格证据 |

两段之间约 1.0–1.375 GHz 尚未形成可交付的连续接收证据。范围端点是当前天线、参考信号和测试条件下的工程能力，不是芯片物理极限；网格证据也不排除未测点存在窄空洞。高于 2786 MHz 可通过 unrestricted 诊断入口请求，但不属于 Auto 用户范围。

软件可请求范围、离散参考点与连续覆盖必须区分，见[频率范围](topics/rf/tuning-range.md)。保留高频宽调谐证据，不退回标准Band边界。按用户要求跳过2.6GHz频谱/干扰诊断；物理上限未确认。内部选路只作为实现细节，不向用户暴露。

B3下探新增实测：v31的1710/1680/1650 MHz及v32的1600/1500/1447/1400/1375 MHz通过参考开关、双音和100 kHz频移跟随；1300/1350 MHz首音未识别。全部使用原NV/selector2/RX端口1与7分频，未通过换校准或复位实现。离散点不能拼成连续覆盖，未检出不直接等同物理极限。v32显式路径已取消频段软件包络，Auto择路已将B3请求包络扩至1375–1920 MHz；Windows、Soapy和SDR++共用该软件表，实测证据分别见`records/rf/coverage-b3-coverage-windows-auto-released.json`、`records/host/soapy-b3-coverage-auto.json`和`records/host/sdrpp-b3-coverage-auto.json`。

[B5/900MHz](../records/rf/frontend-fem-b5-900-v29-20261029-rerun.json)默认5与覆盖2通过有限参考，差异−0.09dB，无收益依据。[B8/880MHz](../records/rf/frontend-fem-b8-880-v29-20261029-live3.json)软件配置和采集通过，FEM比较排空但参考不稳定，不能声称改善或不支持。不重复同条件比较，不修改Auto默认开关。

SDK与固定ZW217参考已建立NV、初始化、ID流程与接收switch关系。RTM7916-51仍为有依据的兼容性假设；保存零值不能区分超时和有效0，不能确认型号、后缀、外部ACK或板级接线。私有恢复状态未独立读回，停止排空是间接控制流证据。[前端分析](topics/rf/investigations/zw217-reference-assessment.md)。

## 通信功能证明与剩余交付

按用户最新10秒标准，本次B210发射→UIS8910 raw USB→主机实时QPSK/OFDM解调实验已收尾。当前源码四组结果如下，均RX索引30、TX设置65；源幅度和原始电平、CPU、字节差额及源码身份见[交付证据](../records/communication/functional-acceptance.json)。索引不等于校准dB，UHD设置不等于dBm。

| 中心 MHz | BW | 调制 | 有效帧 | BER | EVM | 主机丢弃 B | 源帧获取率 |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| [2700](../records/communication/realtime-qpsk-2700-bw0-tx65-rx30-current-10s-v1.json) | 0 | QPSK | 2022 | 0 | 4.68% | 0 | 99.75% |
| [1900](../records/communication/realtime-ofdm-1900-bw0-tx65-rx30-single-10s-v1.json) | 0 | OFDM | 4157 | 0 | 3.15% | 0 | 99.78% |
| [1900](../records/communication/realtime-ofdm-1900-bw1-tx65-rx30-single-10s-v1.json) | 1 | OFDM | 8320 | 1.56e-05 | 3.04% | 0 | 99.84% |
| [1900](../records/communication/realtime-qpsk-1900-bw1-tx65-rx30-current-10s-v1.json) | 1 | QPSK | 2866 | 0 | 10.34% | 59179008 | 70.70% |

QPSK BW1仅证明无线载荷可实时解调，主机丢弃59.2 MB、获取率70.7%，不作为无损/稳定组合。另三组无主机队列丢弃，仍不证明精确零RF丢样。各组TX自然退出、设备停止排空，无数字近轨抽样；不排除模拟压缩。

BW0/BW1名义1.92/3.84 Msps，对应QPSK240/480 ksym/s、OFDM7.5/15 kHz子载波间隔及约0.72/1.44 MHz占用；这不是完整接收通带测量。原始signed12、LE16+16、4 B/复数样点纯raw不变。主机OFDM选带/去DC与单精度优化仅影响解调副本，[同IQ和回归证据](../records/communication/ofdm-conditioning.json)保留失败及历史长测；当前不再以60秒为门槛。

历史代表点覆盖、失败频点和不同电平条件保留在[统一索引](../records/communication/representative-summary.json)，不重新扫描。1000/2600/2786 MHz及部分低频OFDM仍未通过，不把通信失败等同于不支持RF接收，也不拼成连续通信覆盖。

整体SDR仍保留物理上下限/板级限制未决、外部前端型号未唯一确认等状态。便携SDR++发布一致性已解决。通信子任务收尾不代替物理RF结论；后续按[唯一计划](plans/goal-roadmap.md)处理具体交付，停止重复长测和低收益USB微调。
