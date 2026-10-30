# 2026-10-29 项目复盘与收敛

## 已确认的主线

项目目标是把 UIS8910 接收链交付成可重复使用的原始 IQ SDR。首版边界是：RF 配置、采集前改频/增益/带宽、停止排空后重采、USB raw IQ、Windows/SoapySDR/SDR++ 数据入口。蜂窝解调、SIM、BCPU 全 ROM、ZSP、独立频谱 GUI 和 ENOB 不属于首版门槛。

## 当前基线

- 固件：`outputs/firmware/current/manifest.json` 指向 v32 PAC，CP generation `0x526f0501`；用户已确认刷入。
- 数据：signed12 数值放在 little-endian 16+16 位容器，每个复数样点 4 字节；无应用 CRC、包头、ACK、重传。
- USB：RXCAPT DMA→DDR→UDC DMA→Bulk IN，六个 8192 字节槽；当前实用供给约 30–32 MB/s，宽档允许丢块和间隙，USB 调度微调已收口。
- RF：B40/BW0 2400–2800 MHz 5 MHz 网格完成 81 点，72 点完整通过；2435/2440 MHz 按用户确认的 Wi-Fi/蓝牙环境影响验收。2786 MHz完整通过，2787–2789 MHz参考仍可跟随但质量下降，2800 MHz B40/B41均有TX相关响应但频率跟随退化。[证据](../rf/coverage-b40-grid-2400-2800-summary.json)
- 主机：Windows、SoapySDR、SDR++正式目录已重建或核对，离线队列/Auto/FFT验证通过。

## 发现并修正的整理问题

1. `outputs/host/*/build.json` 曾保留 candidate 目录路径，正式 manifest 却引用正式目录；当前构建清单已改为正式产物路径。
2. `outputs/host/manifest.json` 曾把 SDR++便携版的旧安装状态标成与发布匹配；哈希核对显示便携版仍是 `53d56bf0...`，当前项目发布插件是 `outputs/host/sdrpp/uis8910_source.dll`，因此状态已改为未同步。
3. `docs/architecture.md`、`docs/windows-handoff.md`、`docs/plans/usb-raw-stream.md` 残留 v23/v29/v31 待刷叙述；已改成当前 v32、当前主机目录和当前 USB 决策。
4. 历史报告仍保留原貌；它们只用于具体缺失事实，不再作为当前部署或待办。

## 后续优化顺序

1. 先完成主机发布与便携 SDR++ 的哈希同步，并做一次当前版本硬件回归。
2. 回到 RF 覆盖：实时核对设备后，以 B40/BW0、RX gain40、B210 TX gain55、1.92 Msps、8192 字节分析窗口作为复现条件，先筛选 2400 MHz 以下的 5–10 MHz 网格，再对转折和代表点做完整双音/100 kHz 改频参考。
3. 低频重叠点优先比较 B3/B5/B8 的同一有限 TX 条件，按接收质量和改频跟随选择 Auto 路径；不把软件包络、单点响应或背景噪声当芯片极限。
4. RF 路由改善有同条件收益后才改共享 Auto 表；没有收益的 FEM、匿名滤波位和未知校准不再重复实验。
5. USB 仅在出现实际退化、故障或明确收益证据时重开；BW4/BW5继续以 SDR 频谱可用为目标。

## 当前不再作为任务门槛

逐行覆盖全部 27 个标准 Band、全寄存器位含义、BCPU 全 ROM、蜂窝解调、2.6 GHz 干扰诊断、严格零丢样、USB 物理极限证明和 ENOB 测量。
