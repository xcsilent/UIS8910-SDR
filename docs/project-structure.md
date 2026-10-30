# 项目目录与维护指南 / Repository structure

The local research workspace preserves build tools and engineering evidence. The public source/release package is generated from an explicit allowlist and sanitized copies; it is not an upload of the workspace or its Git history. Final conclusions are the normal reading surface. Deleted IQ is not a publication dependency.

## 主目录

| 路径 | 职责 | 维护规则 |
| --- | --- | --- |
| `firmware/` | AP/CP 采集、USB 与 RF 服务源码 | 通过源码和固定输入构建，PAC 不代替源码 |
| `host/` | Windows、SoapySDR、SDR++ | 保持配对 DLL、Auto 与格式定义一致 |
| `tools/` | 构建、验证、受控实验与发布 | 日常入口 `tools/sdr.py` |
| `build-support/` | 固定 ARM/SDK/Soapy 构建输入及清单 | 保留校验和、来源与第三方许可说明 |
| `inputs/` | 完整本地 SDK、硬件资料和固定参考 | 不作普通缓存删除，不整体进入发布包 |
| `outputs/` | 唯一 v0.1 固件与主机产物 | `current`/manifest 是当前交付指针 |
| `records/` | RF、USB、主机、通信、维护、保留政策六类最终证据 | 不再创建按版本分散的根目录 |
| `docs/` | 技术报告、架构、性能、寄存器和指南 | 结论指向小型证据，未验证能力保持未知 |
| `work/` | 工具链、最终构建、发布副本与必要缓存 | 只保留八个主题目录，清理前读其 README |
| `archive/` | 冻结历史及单份本地元数据 ZIP | 按具体缺失事实查阅，不恢复旧执行分支 |

## 阅读入口

从 [README](../README.md) 进入[完整技术报告](technical-report.md)、[English report](technical-report.en.md)、[性能参数](performance.md)、[架构](architecture.md)、[寄存器说明](register-reference.md)、[使用方法](getting-started.md)、[构建方法](building.md)和[维护评审](maintainer-review.md)。`docs/data/` 提供机器 JSON/CSV；`docs/assets/` 提供架构及测量图。

证据导航见 [records/README.md](../records/README.md)，本地依赖见 work/README.md (local-only research reference, omitted: `../work/README.md`)。历史标签、端口和“已刷入”文字只表示当时，不应复制为当前设备身份。

## 当前产物边界

- 固件指针：`outputs/firmware/current/manifest.json`；只保留 v0.1。
- 主机指针：`outputs/host/manifest.json`；库、CLI、Soapy、SDR++ 分别记录真实构建身份。
- 新 PAC 必须进入独立候选目录，用户手动刷入后才可标记部署。
- 固件链接产物与当时源码保留在 `outputs/firmware/v0.1/`；本次目录整理不改写这些快照或发布二进制。

## 已完成的目录收敛

2026-10-30 按用户要求删除原始 IQ 和采集中间载荷，共 1,675 份、34,852,574,208 B，见[删除审计](../records/maintenance/open-source-preparation-capture-cleanup.json)。保留最终数值、条件和失败结论；旧频谱和解调不能直接重算。

随后将 `records/` 的 32 个顶层目录归并为 6 类，4,006 份原记录保留 412 份直接引用记录，其余 3,594 份元数据集中到一个本地 ZIP (local-only research reference, omitted: `../archive/research-metadata-2026-10-30/README.md`)。`work/` 的 140 个顶层目录收敛为 8 个，移除重复构建、独立验证副本和临时实验目录，保留完整工具链、SDK、当前构建和发布副本。精确路径对应见[索引](../records/index.json)，范围与结果见[整理审计](../records/maintenance/directory-consolidation.json)。

早先 64.60 GB 的盘点是清理前元数据快照，不能作为当前占用；不要由新图表或目录调整推断重新做过硬件实验。

## 生成本地 GitHub 发布副本

```powershell
python -B tools/prepare_release.py --refresh
```

默认生成 `work/github-publication-v0.1/source/` 和分开的固件、Windows、Soapy、SDR++ Release 包。[publication-manifest.json](publication-manifest.json)规定源码和最终记录的 allowlist；[发布流程](publishing.md)说明脱敏、校验、依赖与发行边界。`--refresh` 仅更新该工具管理的目录，不触碰已部署文件。

整个 `work/`、本地 ZIP、完整研究参考树、原始 IQ 和原 Git 历史均不直接发布。厂商 PAC/SDK 与 ARM 编译器的分发依据仍须核对；隐私扫描通过不等于取得第三方分发权。本工具不初始化远程仓库，也不上传 GitHub。

## 后续目录纪律

- 最终性能只维护一份机器 JSON 与派生表格，不按每轮实验另建计划。
- 实验输出使用对应主题和明确文件名；最终结论写入 records，重复构建留在可重建 work 子目录。
- 历史源码指纹不因移动路径而刷新；旧报告不冒充当前源码测试。
- 新目录整理由精确清单控制，保留工具链和固定依赖；不执行整个 work/ 的清空。
