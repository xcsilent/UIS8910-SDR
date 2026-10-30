# RF 重构代码索引

这里是从本地SDK还原的可构建代码，不是一套已经整体替代厂商的RF驱动。地址、调用顺序和证据入口统一见[RF初始化与调谐链](../../docs/topics/rf/init-sequences.md)。ZW217参考头保留在inputs中，不接入固件构建；新增离线C还原不改变已部署固件。

## 当前采集服务链接的部分

以[build-recipe.json](../capture/build-recipe.json)及[build_capture_bridge.py](../../tools/build_capture_bridge.py)为准。当前配方在rf_rebuild下仅链接：

| 文件 | 职责 | 不代表 |
| --- | --- | --- |
| rfad_frame_time.c | 有界读取RF帧时间、等待有限tick | 精确RF锁定时间测量 |
| rfad_spi.c | 经CP RFAD的GPO/命令口提交命令 | 直接在AP访问RF寄存器或移植FEM RFFE协议 |
| rfad_off_immediate.c | 有界立即停RF流程 | 完整设备复位/无条件回滚 |
| rfad_rx_request.c | 将配置编成event/RX请求包 | 完整执行PLL与模拟初始化 |
| rfad_stop.c | 停止窗口等RFAD辅助流程 | 已自主替换厂商RX/冷启动 |

它们由firmware/capture的事务状态机组合；厂商RF LTE初始化、RF_EVENT和RF_RX入口仍被调用。添加了-I搜索目录不等于该目录所有C文件均被链接。

## RF核的离线重构

| 模块 | 还原范围 | 地址视图/边界 |
| --- | --- | --- |
| rf_core_rxon_request | RXON字解包、校正、上下文/系数与B主体组合 | 纯解包及离线总线入口；不能把mode字段与8955 FREQ_MODE混同 |
| rf_core_frequency | 原生0x37f0系数算法 | 纯数据；默认因子7，不证明物理分频拓扑 |
| rf_core_tune_plan | 原生调谐前缀，A/B两组写计划 | RF本地地址；polling_enabled入口拒绝，不替代全部完成流程 |
| rf_core_tune_flow | 校正、上下文读取、调谐及尾部计划 | resolve_tune_request用CP别名读取上下文；生成的步骤用RF本地地址，不能共用一个不区分视图的裸总线 |
| rf_core_rxon_prepare | A组模拟/MDLL准备 | RF本地；B组由下列独立模块组合，不能将本文件当B组入口 |
| rf_core_rxon_prepare_b_prefix | B组入口保存/模拟配置、0x4632时钟helper、预计算系数提交及0x4fc4..0x50da前缀 | RF本地，10字节行表0x8a54；分段验证，非完整B组prepare |
| rf_core_rxon_prepare_b_mode | B组0x50da..0x529c模式相关模拟分支 | RF本地；接收入口保存的0x30400/404旧值，不能在中间重新读取替代 |
| rf_core_rxon_b | B组0x4ecc..0x5360组合入口；with_helpers接入真实表应用和mode实现，另保留回调入口作差分/适配 | RF本地；预计算系数/冷启动由上游保证；非完整自主RF启动、未部署 |
| rf_core_rxon_finish | A组有界ready/定时器、校准、mode及最终写入 | RF本地；mode由回调提供，失败不保证回滚 |

`rf_core_rxon_apply_tables()`从A组finish提取共用原始0x453c，实现14次上下文/表读取和9次写入，无ready/VCO读或轮询。-O0/-O2各252例原始/C逐访问差分、各23个访问失败点通过。B组仍保留历史名calibration回调，不把该函数误称PLL锁定检查；总线宽度适配和完整调用链部署尚未完成。表索引/独占上下文由调用者保证。
| rf_core_mode | 原生0x3a7c六档，45次半字写入 | RF本地；采样率与通带另行实测，不支持把任意高编号当扩宽 |

上述rf_core C文件没有进入当前capture构建的链接源集合。离线差分成功只能证明对应输入域与原始软件行为相符，不能证明替换后的跨核执行、MMIO时序或模拟接收。

`rf_core_rxon_post_configure()`补齐共用原始`0x38a8`：RXON 返回后调用方`0x616a`与 retune `0x66ce`均使用它。保留实时 selector、四个中心表及 mode 宽度表读取，包含原始32位字写入`0x50109050`和五次16位写入；不把该混合地址直接当 AP 可访问空间。现有 retune 规划器已含默认表对应规则，本函数增加可执行总线接口及运行时查表行为。-O0/-O2 各1492例原始指令逐访问对照、各128个失败位置通过，含非默认表、频率窗口边缘和非法mode无访问检查。无ready/VCO读取，不能当作锁定检查；仍未链接或部署。

B组前缀的-O0/-O2各100组合成原生差分及26个总线失败点、模式中段各675组差分及1065个总线失败用例见[b-prepare-prefix.json](../../records/rf/reference-b-prepare-prefix.json)。复核入口为`python -B tools/verify/verify_rf_prepare_b_prefix.py`，扩展已有检查，不增加版本专用runner。同报告核对B组完成尾部及共用0x453c/0x3a7c调用；未将完整B组标为已实现或部署。

同一报告新增组合入口-O0/-O2各264组原生总线/回调序列差分和618个失败点；共用校准/mode内部作为回调边界，不重新声明为本次验证的实现。另126例原始调用方证明先计算b520系数再按selector分派B/A组；它不证明硬件RFAD请求新鲜性或跨核执行时序。

`rf_core_rxon_b_with_helpers()`已通过统一宽度总线接入实际表应用与mode实现；当前-O0/-O2各90组完整B主体原始/C差分、883个故障位置及3类非法总线检查通过。上层`rf_core_rxon_request_b()`另接通请求/校正/系数生产，各150例、340失败位置和5种非法值通过。整链发现的mode0重复b550查表、mode4/5 selector5/15控制分支已修正，独立mode各264例/584失败位置通过。动态上下文读取和全部写入比较，省略的私有常量读先与保留镜像核对。作用域mode0–5、初始化表/独占上下文，不含ABI、冷启动、地址桥、物理校准或实机表未改证明；失败不回滚。仍未链接当前采集服务或部署。

本板路径组合补验：将已存同epoch NV的B3/B5/B8端口对应到保留RF镜像真实模拟行，新增36组完整请求链用例（各mode0–5、两个raw中心），每优化请求链合计186例、680个失败位置、5种非法值通过。显式验证30418/3040c/30480/30468写入及30414的表值→OR40→OR60锁存序列；不将最终值直接等同表项。模拟/数字flag=0、MDLL bypass和初始寄存器为测试条件，未证明运行RF RAM表值、物理引脚/校准或接收范围。B40属A组，未冒充此次B主体验证覆盖。

同文件新增 `rf_core_rxon_publish_state()`还原共享调用者`0x616e..0x6200`条件标志、两处`0xacc`回调及状态/校正索引保存。-O0/-O2各288组原始/C比较、281个失败位置和4种非法合同通过，包含回调修改共享状态后的重新读取。`0xacc`在调用者组合中保留回调边界，内部时间记录主体单独验证；后续调用及原子性未证明。该软件状态不是PLL锁定或接收成功标志，未链接或部署。生产/消费引用与边界见统一初始化链文档。

`rf_core_rxon_record_timing()`还原`0xacc`的`0xad0..0xb52`主体并含helper `0x902`：最多10次读取系统计数请求状态，打包两组时间数据到`0x928c/0x92a0`五槽环，`0x92ce`索引递增模5。-O0/-O2各100例原始/C逐访问比较及63个失败位置通过；硬件循环按保留RI5CY手册建模。始终忙仍继续使用最后值，与原始软件一致，不是锁定或计数器成功保证。总线混合RF本地RAM和字面系统MMIO地址，未建立CP/AP桥或部署，不应直接用于目标设备。该helper不读PLL状态、不写RF配置，已从后续PLL控制候选中排除。

## 其他保留模块

rfad.c及rfad_power/nv/memory/boot_memory/boot_inputs/control/frequency/variable等分别还原电源、NV、表、boot输入和控制子流程；rfad_analog/rx/rx_window/raw_capture/raw_dma提供相应分析/受控调用实现。rf_frontend_nv解析板级MIPI/GPO/MDLL数据，本机值不能由参考仓库默认校准替代。

rf_frontend_override提供实验用的单字节开关模板覆盖/恢复，尚未接入已部署v28。仅接受已知本板两条命令，要求独占、RF空闲及总线有序访问；读回/冲突失败保留恢复状态，不能继续当作可重用。ARM合成故障验证不替代实机cache和生命周期验证，见前端调查页。

这些模块有各自的作用域限制，详见头文件；“保留源码”“离线验证”“当前链接”“实机验证”分别判断。当前不恢复全面冷启动精简、BCPU全ROM或蜂窝解调。

## 地址复核

运行`python -B tools/verify/verify_rf_register_reference.py`可重建[寄存器交叉表](../../records/rf/reference-rf-register-crosswalk.json)，列出rf_core地址引用、mode偏移表、参考字段、CP别名和现有trace覆盖；该工具不访问设备、不修改固件。
