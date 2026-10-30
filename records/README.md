# 实验结论与验证记录 / Evidence records

这里保存被当前文档、能力表和工具直接引用的最终结论、测试条件及必要的验证记录。历史版本标签只标识当时实验；当前固件与主机程序以各自 manifest 为准，历史报告不代表新源码已经通过测试，也不是实时设备状态。

性能入口是[性能说明](../docs/performance.md)和[机器可读能力表](../docs/data/sdr-capabilities.json)。无需逐个翻阅旧实验目录。

| 主题目录 | 内容与推荐入口 |
| --- | --- |
| `rf/` | 接收范围、初始化、PLL、寄存器与前端；[B40 下段](rf/coverage-b40-grid-2000-2390-summary.json)、[B40 上段](rf/coverage-b40-grid-2400-2800-summary.json)、[寄存器交叉表](rf/reference-rf-register-crosswalk.json) |
| `usb/` | DMA、UDC、供给瓶颈、带宽与吞吐；[当前几何供给分析](usb/current-geometry-supply.json)、[BW5 通带](usb/geometry-v20-bw5-passband-summary.json) |
| `host/` | Windows、Soapy、SDR++、Auto 选路及切频验证 |
| `communication/` | 实时 QPSK/OFDM 功能结论与限制；[10 秒最终验收](communication/functional-acceptance.json)、[代表点汇总](communication/representative-summary.json) |
| `maintenance/` | 项目整理、发布与可复现构建；[固件构建](maintenance/release-v0.1-README.md)、[WSL 主机构建](maintenance/host-build-wsl-README.md)、[目录整理审计](maintenance/directory-consolidation.json) |
| `retention/` | 已删除 IQ 的历史索引及[保留政策](retention/README.md)，不包含采集载荷 |

2026-10-30 将原来 32 个顶层目录、4,006 份记录收敛为上述 6 个主题，保留 412 份直接引用的记录，另有索引与本轮维护结果。3,594 份旧元数据退出活动目录，原始字节集中保存在本地历史归档 (local-only research reference, omitted: `../archive/research-metadata-2026-10-30/README.md`)。这是元数据收敛，不是新硬件验证；NV/配置上下文不等于原始 IQ。

[精确迁移索引](index.json)记录旧路径到保留文件的对应关系。离线工具通过 `tools/sdr/artifacts.py` 解析，归档中才有的文件明确报告 ZIP 和成员名，不自动解压或恢复旧实验分支。最终性能数值、条件和原有失败结论仍保留；路径调整不刷新旧源码指纹。

原始 IQ、发射波形及采集中间数据已按用户要求删除。旧频谱与解调无法从载荷重算；最终表格可以由保留的 JSON 重新生成。GitHub 发布只选择经过清单和隐私检查的源码、文档与结果，不直接发布整个 `records/` 或本地归档。
