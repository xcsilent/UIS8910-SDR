# 唯一项目路线 / Consolidated roadmap

**当前硬件Goal已清除，没有自动执行中的RF/USB实验。** 本轮任务是专业开源整理与最终证据收敛，不能把文档完成标记为整项SDR研究完成。需求以[requirements](../requirements.md)为准；部署以[状态](../project-state.json)、[固件manifest](../../outputs/firmware/current/manifest.json)及[host manifest](../../outputs/host/manifest.json)为准，历史设备信息不是实时查询。

旧逐阶段执行叙述已保存到 `archive/open-source-preparation-2026-10-30/goal-roadmap.before-consolidation.md`，仅为保留研发过程，不作为另一套当前计划。最终性能集中在[performance](../performance.md)，研究与维护缺口集中在[maintainer review](../maintainer-review.md)。

## 1. 保留的工作基线

| 项目 | 最终状态与证据 |
| --- | --- |
|接收服务 |v0.1（原v32字节）、CP generation0x526f0501、BW0–BW5、6×8192 B输出槽、paired scratch、配置ABI2/trace ABI5；[部署](../../records/rf/coverage-v32-deployment.json) |
|主机接入 |Windows DLL/CLI/raw/stdout、SoapyCF32/CS16、SDR++原生模块已有真实数据流；[主机manifest](../../outputs/host/manifest.json) |
|改参 |正常停止→排空→配置→重采免芯片复位；快速SDR++调频合并并恢复，用户确认旧卡死已解决；不承诺无缝、锁定时间或相位连续 |
|RF覆盖 |B40下段40/40网格点、上段72/81完整参考，部分点另列条件；B3低端1375 MHz、B5低端687.5 MHz等有参考，连续范围与芯片极限未知 |
|通带/USB |历史相对−3 dB宽度与名义Fs分别记录；约30–32 MB/s实用供给，BW0/1预算可承载，BW2缺余量，BW3–5部分输出；[性能表](../performance.md) |
|空口通信 |10秒QPSK BW0、OFDM BW0/BW1功能证明完成；QPSK BW1有损，只证明可解载荷；[最终结论](../../records/communication/functional-acceptance.json) |
|RF行为还原 |129条地址交叉表、局部原生/C对照、NV/RFFE/PLL算术链；不是完整厂商初始化替代，物理LO lock未知 |
|前端研究 |RTM7916-51兼容性假设有软件依据；确切型号/BOM/总线结果未确认；B5开关对照无收益，B8不稳定，未据此改Auto |

## 2. 当前整理交付

`records/` 已归并为 RF、USB、主机、通信、维护、保留政策六个主题；`work/` 保留八个构建/依赖目录。旧元数据集中为一份本地 ZIP，路径索引和整理审计见 [records](../../records/README.md)。原始 IQ 不恢复；本次整理不启动硬件 Goal，也不改变已部署二进制。

中英文README/完整报告、架构/所有权/切频图、性能与失败说明、机器JSON/寄存器CSV/静态图、构建与使用指南、第三方来源、许可状态、issue/PR模板与便携CI保持一致。

用户已明确要求删除原始IQ和采集中间数据，只保留最终结论。工作区/records的采集载荷和重复过程日志已按审计清理；保留最终数值、条件和失败元数据。历史频谱不能直接重算；只重建表格/图不能冒充重做RF测试。源码、当前PAC、AP/CP链接依赖、SDK与工具链不作为采集缓存删除。[整理审计](../../records/maintenance/open-source-preparation-README.md)。

项目名称已确定为UIS8910-SDR，原创代码及文档采用GPL-3.0-or-later。由`tools/prepare_release.py`按allowlist生成脱敏源码及独立v0.1固件/Windows/Soapy/SDR++发布副本；入口与核对范围见[发布说明](../publishing.md)，不上传GitHub。副本包含v0.1平台PAC与固定ARM/SDK构建包，已有独立目录AP/CP/PAC构建证据。完整本地工具链保留，历史项目固件二进制已按用户要求删除。厂商PAC/SDK及ARM编译器原始声明、对应源码等分发依据仍未齐全；隐私扫描通过不等于取得再分发权。

WSL主机构建统一为 `tools/build_host_components.py`，Ubuntu系统依赖见
[WSL构建指南](../building-wsl.md)，Soapy0.8.1固定源码随包提供。
独立含空格路径完成Windows DLL/CLI、调谐工具、Soapy SDK/模块构建及Windows离线验证，
见[主机构建证据](../../records/maintenance/host-build-wsl-README.md)。构建候选不改变已部署主机组件，
原生SDR++仍单独依赖MSVC/匹配core；硬件Goal保持未启动。

## 3. 若用户恢复实现工作：按收益排序

1. **交付一致性。** 统一C/C++ Auto质量边界：C++ B40 cap2786 MHz、Windows C包络2790.625 MHz现有差异已记录。保留手动探索请求与NV依赖；只回归受影响主机组件，重新构建后更新配对manifest。
2. **可复现构建。** 固件统一为v0.1平台配置与Windows入口`tools/build_firmware.py`；WSL主机统一入口`tools/build_host_components.py`，固定源码/工具包在`build-support/`。维护这两个不同构建目标的入口及CI，第三方许可仍须发布前审核。
3. **有硬件条件的具体RF缺口。** 根据BOM/有效ID/已闭合控制链做单变量测试，区分PLL/分频、片内模拟、外部滤波、天线与参考限制。未找到有依据的变量时不盲写、不重复零值快照或全频盲扫。
4. **可选标定。** 连续覆盖、ENOB、绝对功率/灵敏度/线性、时钟ppm和设备CPU等目前未知；有明确需求与校准条件才安排，不以它们阻塞已有功能说明。

RF依据：[B40下段](../../records/rf/coverage-b40-grid-2000-2390-summary.json)、[B40上段/边界](../../records/rf/coverage-b40-grid-2400-2800-summary.json)、[B3低端](../../records/rf/coverage-v32-b3-lower-summary.json)、[ZW217前端调查](../topics/rf/investigations/zw217-reference-assessment.md)。1000 MHz只是软件包络，995/999.9 MHz未合格；网格点不能拼为连续芯片规格。

## 4. 已关闭或不恢复的分支

- 不继续无收益USB scheduler/ACK/refill微调；30–32 MB/s不是已证明的硬件极限。仅有退化、故障或具体新瓶颈证据才重开。
- 不补USB无法全量承载档位的通信测试，不要求宽档全量持续输出。BW6/7无新增通带证据已关闭。
- 10秒通信功能证明已收尾，不追逐60秒门槛、失败频点功率网格或全频率×调制组合。
- 桌面视觉验收已由用户废弃；核心数据流测试不冒充桌面帧率。
- 不恢复蜂窝解调、BCPU全ROM、ZSP、1090 MHz扩展、全面冷启动精简、独立频谱GUI。

## 5. 恢复实验时的执行纪律

每轮一个最影响交付的阻塞、可验证假设、最小实验与继续/停止条件。同条件失败不重复；反汇编服务于实现/定位，不以全寄存器覆盖为门槛。RF实验默认RX增益索引30，记录TX设置/源幅度/原始电平；无数字近轨不能排除模拟压缩。

实机前核对UIS8910/B210当前身份、占用及TRX1软件映射，有限TX结束确认退出。必要PAC先独立目录构建验证、说明变化，由用户手动刷入，未刷不标部署。物理重启/接线等外部依赖明确说明；先推进独立有效工作，不靠无收益重复实验维持进度。

默认signed12、LE16+16、4 B/复数；IQ纯raw，无应用层头/CRC/hash/逐包ACK/重传。保留cache、长度、DMA所有权、完成和错误检查。配置与统计独立；不同层损失分别报，精确RF丢样未知。

校验：`python -B tools/sdr.py verify`及受影响的针对性构建/测试。便携文档校验用`tools/check_publication.py`；源码改变后不拿旧报告冒充当前通过。未验证能力保持未知，局部完成和暂时受阻都不是整体Goal完成。
