# 文档导航

## English entry points

- [Project overview](../README.md) and [getting started](getting-started.md).
- [Complete technical report](technical-report.en.md), [architecture diagrams](architecture.md), [measured performance](performance.md).
- [Register spaces / fields](register-reference.md), [capabilities JSON](data/sdr-capabilities.json), [129-entry CSV](data/rf-registers.csv).
- [Building and reproducibility](building.md), [WSL host dependencies/build](building-wsl.md), [maintainer review](maintainer-review.md), [third-party notices](../THIRD_PARTY_NOTICES.md).
- [Publication contents and local packaging](publishing.md): source, paired v0.1 releases, privacy handling and remaining distribution questions.

原始IQ和生成波形已按用户要求清理，只保留最终数值、条件和失败结论；旧迁移表不表示载荷仍存在。[清理审计](../records/maintenance/open-source-preparation-README.md)说明范围与复现限制。

本目录按“使用交付、工程实现、RF 研究、历史证据”组织。当前发布文件和实测记录仍分别以 `outputs/` 与 `records/` 为准；本目录中的说明不会把历史实验当成实时设备状态。

## 面向使用者

- [项目 README](../README.md)：项目目标、当前能力和限制。
- [Windows 使用与交接](windows-handoff.md)：CLI、SoapySDR、SDR++ 和通信实验命令。
- [当前能力表](status.md)：频率、带宽、格式、USB 供给和已验证功能。
- [完整技术性能报告](technical-report.md)：适合发布到 GitHub 的总体技术说明。
- [中英文性能表](performance.md)：采样率、通带、吞吐、CPU及损失分别说明。
- [使用指南](getting-started.md)：新使用者的前提条件、参数与常见问题。

## 面向开发者

- [当前架构](architecture.md)：固件、DMA、USB 和主机软件的数据/控制路径。
- [目录与维护指南](project-structure.md)：哪些目录是源码、发布物、证据和冻结历史。
- [开发与复现指南](development-history.md)：构建、验证、实验记录和证据等级。
- [构建说明](building.md)：主机候选、AP/CP配对、厂商输入和新克隆限制。
- [维护者评审](maintainer-review.md)：许可、复现、Auto一致性和未测指标。
- [USB raw IQ 实现](plans/usb-raw-stream.md)：所有权、缓存、队列和吞吐边界。
- [RF 初始化与调谐链](topics/rf/init-sequences.md)：SDK 反汇编、RF 核和 RXCAPT 执行顺序。
- [RF 调谐范围](topics/rf/tuning-range.md)：路由表、离散覆盖证据和未决边界。
- [PLL/分频参考](topics/rf/pll-reference-comparison.md)：频率算术、寄存器和前代参考的边界。
- [寄存器与反汇编参考](register-reference.md)：将已确认、推断和未知内容分开。

## 证据和历史

- `records/` 保存不可由源码完全重建的构建、实机和分析证据，按主题分目录。
- `records/retention/` 保存历史索引和当前删除策略，原始载荷已经移除；查看其README及retention.json。
- `archive/` 是冻结历史，只有在当前证据缺少具体事实时查阅。
- `work/` 是可再生工作目录，不能当作发布源或无条件删除。

## 证据等级

文档使用以下术语：

| 标记 | 含义 |
| --- | --- |
| 已验证 | 有当前源码/构建或实机记录直接支持，可作为交付能力说明 |
| 条件验证 | 只在记录的频点、增益、天线、参考和时间窗口下成立 |
| 软件已知 | 由反汇编、模拟器或 C 对照确认，尚未证明硬件物理行为 |
| 未决 | 现有证据无法区分多个原因，不能宣传为能力 |

