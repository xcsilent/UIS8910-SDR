# 2026-10-30 开源整理与采集数据收敛

本轮只整理本地文件、文档和最终证据；没有刷写、RF发射、设备访问、Git提交或GitHub上传。先按用户要求保留原始资料；用户随后明确确认“包括原始IQ，只保留最终结论”，据此执行下述限定删除。

## 盘点

整理前[目录统计](open-source-preparation-inventory-summary.json)记录144,233个文件、64,604,259,594 B（64.60 GB，60.17 GiB），不含Git内部目录。完整元数据逐文件保存在 `file-inventory.jsonl.gz`，包含路径、长度、mtime和重解析标记，不读或hash IQ。Git索引状态快照为 `git-status.z`，没有stage/reset/clean操作。

| 顶层目录 | 整理前文件数 | 大小GB（十进制） | 处理 |
| --- | ---: | ---: | --- |
|archive |74,002 |17.402 |冻结历史保持 |
|inputs |40,850 |7.707 |SDK/参考/校准输入保持，不默认发布 |
|work |22,283 |28.276 |限定删除采集/波形载荷；工具链和链接依赖保留 |
|records |5,396 |11.108 |限定删除IQ载荷；最终数值、失败和条件保留 |
|outputs |1,337 |0.109 |当前固件/主机及旧构建未改 |
|firmware |134 |0.000570 |源码位置保持 |
|host |22 |0.000117 |源码位置保持 |
|tools |184 |0.001585 |新增整理/报告/便携检查工具 |
|docs |20 |0.000230 |整理前数量；本轮新增报告/导航/图表 |

盘点的8个遍历错误：5个IDA崩溃目录PermissionError、3个MinGW工具链文档重解析目录OSError，精确位置在统计JSON。未取得所有权或改变权限，不能声称已检查这些子目录内容。元数据全盘扫描也不等于对14万文件逐行代码审计。

## 已授权的数据删除

[删除清单](open-source-preparation-capture-cleanup.json)完整列出1,675个文件及长度/mtime，全部成功，释放 **34,852,574,208 B**（34.85 GB，约32.46 GiB）。只处理 `work/`、`records/` 下 `.raw/.fc32/.cs16/.iq`；删除前先落盘计划，再验证路径和文件状态，没有跨壳删除、符号链接遍历或payload hash。

不删除PAC/EXE/DLL/ELF/.bin、源码、NV、SDK、工具链、当前AP/CP构建或冻结archive。小型测量JSON属于最终结论的条件与数值来源，仍保留原路径以便核查；不恢复成需要反复运行的实验链。原始载荷删除后不可从源码还原，历史频谱/解调无法再直接重算。`records/retention/retention.json`与文件解析器明确报告这一事实，不把删除误报为数据损坏或以其他样本替代。

另按[采集日志清单](open-source-preparation-capture-log-cleanup.json)删除638份重复过程日志，970,421 B；没有选择构建/工具链日志。冻结archive中历史数据未改动，不在当前数据保留或公开导出的能力承诺内。

整理后[元数据快照](open-source-preparation-after-inventory-summary.json)：142,521个文件、29,760,188,768 B（29.76 GB），含新文档、图表和本地源码副本，不含Git内部目录，仍有相同8个遍历限制。明确删除量为34,853,544,629 B（载荷+日志）；前后总量还包含新增文件，不能把两者差值当精确删除量。

## 稳定交付面

- 中英文README与完整技术报告，统一说明厂商依赖和未测能力。
- 架构、DMA所有权、停止排空/重采图；明确设备直接DMA与主机队列拷贝边界。
- [最终性能](../../docs/performance.md)及 [能力JSON](../../docs/data/sdr-capabilities.json)，按原始摘要生成静态图。
- [寄存器说明](../../docs/register-reference.md)、129条地址CSV及参考字段CSV，保留证据等级，RF LO lock未知。
- 构建/使用/维护者评审、第三方来源、许可待决说明、issue/PR模板及便携CI。
- 本地allowlist源码评审导出，排除SDK/PAC/DLL/raw/工具链/归档。此副本仍需来源、许可和隐私审核，不冒称已脱敏发布包。

原Goal中按阶段累积的“当前/下一步”已收敛成一份未激活的简明路线；旧文本备份在 `archive/open-source-preparation-2026-10-30/goal-roadmap.before-consolidation.md`，保留研发过程但不恢复多套活动计划。

## 结论纠正

12位数值不等于ENOB；原始两路称lane0/lane1，物理I/Q未定。软件频率包络不等于连续RF覆盖，1000 MHz不是已通过边界。校准ready/VCO码/BBPLL lock不能充当RF LO lock。宽档频谱可用不等于全量连续传输。C/C++ Auto上界差异已公开记录，不在文档任务中静默替换已测二进制。

## 检查结果与边界

最终离线检查结果见本目录JSON记录：文档链接、表格生成一致性、源码语法、授权删除策略和全项目verify。结构/身份通过与历史代码证据新鲜度分开报告；不把stale报告称为当前代码重新通过。未进行硬件或二进制重编译。

主要结果入口：[检查汇总](open-source-preparation-verification-summary.json)、[全项目身份/结构](open-source-preparation-project-verification.json)、[便携检查](open-source-preparation-portable-checks.json)、[文档链接](open-source-preparation-documentation-links.json)、[删除策略](open-source-preparation-retention-verification.json)、[评审副本检查](open-source-preparation-review-portable-checks.json)。这些检查不证明新RF性能或许可已经清理。

新克隆的完整固件构建仍依赖外部输入和AP/CP绑定；许可未选择；BOM、校准性能和物理极限未确认。这些是明确剩余项，见[维护者评审](../../docs/maintainer-review.md)。
