# ZW217 仓库对 UIS8910DM SDR 的参考价值

本页保留分阶段研究与原始软件证据，不是当前待执行实验清单。当前固件/ABI以manifest及project-state为准（v32、trace ABI5）；汇总地址表已扩至129条、51个具名声明、每视图172个字段值。面向发布的收敛结论见[寄存器说明](../../../register-reference.md)和[技术报告](../../../technical-report.md)。原始IQ已按用户要求删除，旧采集报告保留最终数值，不能直接重算。

## v27 基线 PAC RF 镜像已解码

`python -B tools/verify/verify_rf_pac_payload.py` 校验 current PAC 哈希及容器页 CRC，提取 `riscV.bin.000`：条目头偏移 `0x1f6400`，载荷17936字节，36页；512字节页中偏移4..503为500字节数据，504/506为标记和页号，508为前508字节的CRC32。先前508字节提取混入页尾，其codec失败结论已撤回。

完整 SDK `CSDK_RDA8910.elf` 的 `halLzmaDecompressFile`（Thumb `0x600d6b81`）给出当前封装：偏移0为u32总输出37308；偏移4为u16块大小64KiB，偏移6为u8字典1KiB；偏移8为u32压缩长度17913，偏移12为硬件检查结果 `0x00311657`，流起点16，末尾7字节对齐填充。原始ARM函数经Unicorn执行，与解析结果一致；块解码以桩模拟，另验证空/未对齐指针、块失败、检查不匹配返回。此前借用ZW217推测的三个u32头、流后双检查值布局不适用于当前文件，已移除。

SDK自带 `tools/win32/lzmar.exe d2` 成功解压；使用同一工具对SDK镜像执行 `e2 65536`→`d2`，逐字节往返一致。当前PAC解码镜像SHA256为 `5df483f4435d11ed0a7e66918a5bce00e322097c57bbc4a1138b9940f1dc6ab8`，与SDK镜像同长但2037字节不同，分布在124个差异区间。证据见[容器与原生解析验证](../../../../records/rf/reference-rf-pac-payload.json)，可再生产物为 `work/rf-cache/current-rf-decoded.bin`。这不是实时RF RAM读回，也不是已验证的重打包方案。

已将当前PAC镜像直接用于[前端原生验证](../../../../records/rf/reference-rffe-current-pac-native.json)：8个初始化项、原始循环、45组模拟ID完成/超时和32组开关分派全部通过。它们验证的是当前PAC代码与保留NV下的软件关系，不证明总线ACK、实物型号或实际接收改善。

差异来源已闭合：解码镜像逐字节等于冻结归档的RFv6镜像，哈希也与历史 `rf-rxon-finish-native/build.json` 一致。它保留了此前调频系数、RXON请求、A组准备/完成和retune前缀重构。`0x37f0`系数helper会额外写入工作频率值到 `0x66ac`；这不是执行次数。对当前PAC执行51组系数输入，与当前C实现一致，见[定向系数验证](../../../../records/rf/reference-rf-current-pac-frequency.json)。不能继续用SDK原始retune中间地址解释这段已改写代码。

## RF 命令入口观察（v28 已部署）

v29恢复观测边界：`TERM_META+160`的address/original/replacement/active及result位于CP私有`0x8097f8a0`起，现有AP只读范围到`0x80970000`，当前proof仅复制M[0..31]，因此没有可用的独立恢复状态读回。正常phase30/成功排空是经停止路径的间接证据；operation53恢复default仅是下一次配置，不是RF副本或外部芯片读回。不扩大访问范围或为了读回替换尚待实测的v29。新增[链接停止分支执行验证](../../../../records/rf/frontend-override-stop-continuation-final-arm.json)从最终force_idle返回后执行实际transaction分支、真实restore及结果判断：空闲失败不执行restore；冲突、坏状态和写后读回失败进入0xa0d且保留active；正常恢复/无覆盖进入stage5 trace。只运行到失败处理或trace入口，不冒充完整DMA teardown/HELD、硬件idle、cache或外部ACK验证。

`tools/build_rf_observer.py` 仅在已证明属于RFv6请求重构的NOP区生成离线镜像，不恢复历史runner。原请求有效代码结束于 `0x60f6`，后续NOP区到 `0x6122`；先在 `0x60f6` 跳过整区，保留后续AUIPC原地址。在 `0x10e8` helper入口跳至该区的短桩，记录32位回绕次数 `0x6118` 和最后参数指针 `0x611c`，重放原第一条LBU后返回 `0x10ec`。仅借用原helper本就覆盖的a4/a5，不改变NV、ID结果或RFFE控制字，不增加ID读取、不热改运行代码。计数发生在控制器写入之前，只证明helper入口，不证明提交完成或ACK。

构建为 `work/rf-command-observer-validated/build.json`，镜像SHA256 `75318189d55ee76bc9d9478bcb8665cac36efe22e283db51d98c2a1f64122f04`。[候选原生验证](../../../../records/rf/reference-rffe-observer-native.json)保留全部8/45/32组前端用例，并加入9组完整32寄存器及有序控制器写入对照，含计数回绕；确认RXON跳过观察代码和数据。所有用例通过，ID直接读取路径不会增加该命令计数。随后已封装PAC并取得下述实机证据；原生验证本身不证明硬件时序或共享可见性。

已完成匹配CP的ABI5阶段读取及最终封装：RF Observer v28历史PAC（已删除二进制，最终结果保留在records/rf-frontend），generation `0x526c0501`，已部署并核对。CP沿已使用的RF别名视图读取 `0x500010e8` 入口指令，仅在匹配 `0x0120506f` 后双读 `0x50006118/611c`；每阶段固定32次RF/context读取、不轮询。匹配/不匹配、不稳定读、保留字损坏及错误generation拒绝均经实际ARM代码验证，ABI4另作回归。五个8字执行记录替换ABI4尾部，诊断区仍512字节，不新增DDR或payload处理。它只保存指针，不解引用该指针；双读相同不是原子快照或跨核cache一致性保证。

[最终候选验证](../../../../records/rf/frontend-execution-final-candidate.json)确认相对v27只改APPIMG及modem中 `riscV.bin.000`，其余modem文件逐字节一致；所有页/PAC校验和通过，最终PAC的RF重新提取、解压后与补丁镜像一致。另拒绝坏页CRC、有效CRC下重复页号、截断和超分配容量写入。AP/CP原生、ABI5 trace、旧ABI4回归和布局通过；CP resident14832字节小于16384字节保留区。v28已晋升current，v27保留回退。B5/B8/B40各1秒短采免复位并排空，五阶段签名匹配且双读稳定。采集阶段helper增量1/1/2；最后开关参数对应B5 selector4/port2、NV row4 entry0（slave13/reg0=5），B8 selector6/port3、row6 entry0（slave13/reg0=2），B40 selector15/port0、row22 entry1（slave15/reg2=1）。NV于epoch3停机后读取，对较早采集不是原子快照。见[部署证据](../../../../records/rf/frontend-observer-v28-deployment.json)。这闭合helper入口执行与NV行关系，不证明外部ACK、器件型号或接收收益。下一步核对独立开关/端口控制条件，才进行单变量参考对照；不能把整条B5/B8配置差异归因于一个开关。

实机NV的[路径隔离对比](../../../../records/rf/frontend-observer-v28-route-isolation.json)显示B5/B8还同时改变GPO开关输出（mask252、value0/24）及RX端口。MDLL表中虽存7/8，但当前动态使能为0；既有原生证据证明该条件绕过表值，不能宣称实际分频不同。不能只比较RFFE值5/2就解释既有整链接收差异。

[搬运与分派联合验证](../../../../records/rf/frontend-observer-v28-copy-restore-isolation-native.json)在固定selector/行时，仅替换第一条switch_open的数据字节5↔2。执行实际CP BIN `0x801b9aba..0x801b9acc`、veneer及scatter加载的`0x804388` memcpy，将NV `0x2ac`起0x117c字节复制到CP视图`0x5000974c`；B5/B8目标分别是`0x500097f0/9810`。两行、四变体、八个RF开关分派通过：只有开控制器数据写值改变，关闭命令一致，无额外保留RF RAM写入。随后在同一个模拟内存状态中重新搬运基线，副本逐字节恢复。该证据替代此前只做RF分派的隔离报告，但仍不证明搬运函数的实时调用时点或cache协议。

`firmware/rf_rebuild/rf_frontend_override.c`实现有界模板覆盖/恢复：要求CP侧独占和空闲，核对v28入口签名、发布指针、源NV行与RF副本；仅接受本板B5/B8的slave13/reg0及值2/5，写一个数据字节，不修改源NV、USID、PA或关闭命令。写前保存恢复状态，读回失败仍保留active；恢复遇到第三种值不覆盖并保持失败状态。[ARM验证](../../../../records/rf/frontend-observer-v28-override-policy-arm.json)在O0/O2共64个正常及故障用例通过。v29-final候选已接入prepare后/RX事件前及成功RF停止后的恢复，operation53默认关闭且只允许在首次默认采集成功停止排空后设置。见[CP生命周期](../../../../records/rf/frontend-override-lifecycle-arm.json)、[AP控制](../../../../records/rf/frontend-override-ap-final-arm.json)、[最终PAC验证](../../../../records/rf/frontend-override-final-candidate.json)。离线验证不证明硬件映射、cache、所有权或实际恢复时序；本次[实时核对](../../../../records/rf/frontend-override-v29-runtime-check.json)仍为v28且无operation53，所以候选未部署。匹配后固定整条B5/B8路径，仅改变值2/5做参考对照，不用整链切换冒充单变量实验。停机或恢复失败必须保持不可重用并报告。

本资料已纳入 SDR 主线的参考证据；参考核对本身未访问设备、发射或刷写。调查原文保存在[前端调查报告](UIS8910DM_RF_frontend_report.md)，其第9节是此前在线访问受限时的初步判断，本页补充实际源码核对。当前执行状态与步骤以主计划为准。

## 来源与范围

仓库为 https://github.com/obaidi2005/ZW217_W19_V4.1_yisai ，核对提交 `d48d55e028c13b6f50c291cbb7ea29201c3c8432`（2024-07-23）。递归树返回37227项、未截断。当前构建配置选择UWS6121E，但仓库实际包含`chip_drv/chip_plf/uix8910`及对应底层源码，并非只有历史型号注释。两平台的`rf_registers.h`字节完全相同；这证明该提交复用了头文件，不能单独证明所有硬件版本兼容。

初次提取10个相关文件到`inputs/reference-source/zw217-uix8910/`，来源、SHA256和上游blob匹配状态见该目录`source-manifest.json`。8个文件与上游blob一致，包括核心RF/USB/DMA寄存器头；项目mk和DMA驱动C经连接器文本解码后未达到字节一致，仅作文本参考，原摘录不覆盖。完整源码快照放在 `inputs/repositories/ZW217_W19_V4.1_yisai`，固定同一提交，用于全文检索；获取状态见摘录目录的 `full-checkout.json`。保留原始版权声明，不接入构建或直接移植。另核对同提交的analog_reg.h及uix8910_reg_analog.h，未找到本次PLL/MDLL字段定义。

## 对当前未决位义的直接帮助

下表“本地地址”是当前重构代码使用的RF核地址；参考头为`0x50030000`或GGE视图`0x05030000`加偏移。进一步核对发现默认CP地址与现有trace的`0x5003037c/374/364/410/2e0/2c0`完全对应，结合既有CP↔RF配置搬运证据，可以建立这些区域的源码视图对应，不再仅是偏移相似。GGE分支启用情况、硅修订兼容和硬件字段的物理生产条件仍须区分，不能在AP直接读写RF核地址。

| 当前本地地址/线索 | 参考头偏移与字段 | 可以推进的结论 |
| --- | --- | --- |
| `0x3037c`，此前轮询bit11 | `+0x37c` TXPLL校准状态；bit11 `txpll_cal_ready`，低11位 `txpll_vco_bits` | 可以按参考名标注校准ready/VCO结果，不再仅标为无定义；不应标为RXPLL锁定位，物理生产条件仍未独立确认 |
| `0x3036c` | `+0x36c` RXPLL校准状态；bit11 `rxpll_cal_ready` | 与上项是不同状态字，不能混用RX/TX命名 |
| `0x30364`/`0x30374` | RX/TX PLL校准控制第二寄存器 | 与本项目A/B控制分组位置对应，但该头部分控制字段只有匿名位名，未恢复完整硬件语义 |
| `0x302c0`/`0x302e0`低2位 | RX/TX SDM的DLL模式 | 与现有factor−7写法一致的位宽线索；实际分频含义仍以原生代码和NV证据为准 |
| `0x302cc`/`0x302e4` | RX/TX SDM控制，bit6 resetn、bit7 tx_rx、bits5:4 int_dec_sel | 原始`0x20→0x60`和`0xa0→0xe0`对应释放resetn；不再仅用泛称gate描述 |
| `+0x324`/`+0x354`，v21已纳入阶段记录 | BBPLL1/2状态bit14 `pll_lock_rx/tx`、bit10稳态锁定 | v21同步低频对照未提供接收成败判别；它们是BBPLL字段，不能直接当RF LO锁定 |
| `0x30410` | 模拟控制寄存器4，只有16位泛称 | 不能从本头进一步证明MDLL或freq_mode；已有DWARF/反汇编仍是主要依据 |
| `0x31040` | DLPF_CTRL，bit0 dlpf_rstn、bit1 dlpf_iir3_rstn | 原始2→3对应释放bit0，不能把全部控制字统称PLL开关 |

当前`rf_core_tune_plan.c`中selector≤12或17使用`0x30364/0x30360/0x302c4/0x302c8`，其他组使用`0x30374/0x30370/0x32228/0x3222c`；已还原的A组接收准备/完成写`0x30374`并可轮询`0x3037c`。不能把A组重构误当两组公共prepare/finish，也不因“TX”字样判错。早期 ABI1 trace 只读 A 组；当前 v22 已部署 ABI2 双组 trace。B5 期间 A 组保留旧值仍不能说明 B 组锁定，双组状态的实际判别能力见初始化总览。

初次9项声明检查见`records/rf/reference-zw217-layout.json`。定向核对运行`python -B tools/verify/verify_rf_register_reference.py`：展开rf_core地址及mode偏移表，当前报告为129条地址交叉项、51个匹配寄存器声明；默认CP与条件GGE两种构建以ARM编译检查结构偏移及每种172个位域初始化对象的实际数值。证据见[交叉表](../../../../records/rf/reference-rf-register-crosswalk.json)。原ABI1/ABI2布局来源保留，当前部署trace ABI5，以manifest和状态为准。它是离线声明一致性检查，不是实机位义验证或全寄存器覆盖门槛。

`globals.h`的APB枚举支持将`0x32000`区域分类为DFE、`0x38000`分类为TIMER_3；但RF头声明止于`0x31040`，没有DFE详细位图。当前FIR/抽取/0x32a00的位义不能从本头补齐。

## FEM、USB与DMA

- 文件名检索未发现型号专用驱动；全文检索进一步找到 `MS_Customize/source/product/config/uws6121e/nv_adaptive_cfg.c:46` 的注释 `00: RPM6743 & RTM7916`。这是 PA 板型配置线索，没有写明 -31/-51 后缀，也不是当前 Air724UG 用料证明。数组 GPIO11/12 与注释119/117不一致，不可照抄到本板。
- `SCI_Get_PA_VERSION()` → `REFPARAM_GetPAFileName()` 生成 `pa_ver%02d`；但 `nv_hwversion_adpter.c` 的 PA delta 合并位于 `FORCECHANGE_SUPPORT` 下，且被 `!PLATFORM_UWS6121E` 排除。不能把存在这一函数当作当前项目实际执行 PA 分支的证据。
- `lib/modem/UWS6121E_MODEM/UWS6121_cat1bis_volte_nognss/deltanv/modem_config.nv` 及 `indeltanv/hw_ver01.nv`、`hw_ver02.nv` 明确包含 `FEM_MIPI`、`MIPI_INIT`、`RX_MIPI_SW_Open/Close` 等文本配置；modem 还有 `cp.axf/cp.bin`。因此后续应沿配置消费者和二进制命令执行器追踪，不以找不到型号命名的 C 驱动为终点。配置行号须经同版本 band 表解释，不直接当标准 Band。
- USB头给出DWC式全局、设备、端点、FIFO与DMA寄存器定义，可辅助对照本项目UDC反汇编；它不是本项目厂商请求对象ABI，也不能凭定义删除cache或所有权检查。
- UIX8910 DMA有寄存器头和驱动C源码，可用于后续总线/地址/传输长度分析；AP通用DMA和当前CP RXCAPT、UDC DMA不是同一个模块，不能直接替换采集实现。
- 调查报告中的RTM7916/RPM6743资料主要涉及其他模组拆解。当前Air724U的器件型号、TRX接线和双工器/滤波器仍须板级证据核实；本仓库不足以判定675 MHz衰减由哪颗器件造成。

## Air724UG 前端假设的边界

用户确认手头型号为 Air724UG。EC200U 拆解中的 RPM6743-31/RTM7916-51 可作为候选用料，不能因同用 UIS8910DM 就认定板级 BOM、从地址、端口与滤波器相同。

RTM7916-51 原厂规格书副本描述了 PA 与 14 路 TRx 天线开关；寄存器0含通路选择，0x1D/0x1E为产品/厂商标识，默认 USID 为14。它不能仅归类为“GSM器件”；LTE接收也可能使用其开关部分。RPM6743 的 PA 功能不等于 RX 增益控制。参考：[RTM7916-51规格书](https://uploadcdn.oneyac.com/upload/document/1628491606760_7753.pdf)。

本机[历史NV快照](../../../../records/rf/reference-rf-dual-v17-v20-frontend-mdll.json)显示，B3/B5/B8/B40 的 switch_open 第一项均是 slave13/reg0，值分别为4/5/2/8；B40另有 slave15/reg2/value1。它们证明配置内容，尚非总线波形或芯片ID读回。即使数值能对上某份开关表，也不能据此唯一识别型号；默认地址不同既不能直接判同，也不能直接排除可重分配的 USID。

### 已验证的软件关系

CP `fem_rx_mipi_swon` / `fem_rx_mipi_swoff` 在 SDK ELF 中分别位于 `0x801f2d20` / `0x802c3304`，将 `(u16_soft_band_ind<<4)|0x2c8000/1` 写入传入对象+0x2c所指位置。字段名由 `st_rf_lte_info` 的 DWARF 类型确认：+6 为软件选择器，+4 为 NV 行索引。它不是 RFFE slave 地址，也不能直接作为总线帧。`rfad.c` 的 action50–54 对应 RAM2 的 mipi_sw1..5；特定接收行到执行时序的完整关系仍需追踪。ELF VMA、CP BIN 和 RF 本地地址必须分别解释。

对 SDK CP `cp.axf` 的直接调用和 ARM→Thumb 跳板进行静态核对，发现9个调用点，其中5个经 `0x81b50c` 跳转到 `swon`，1个经 `0x81b4bc` 跳转到 `swoff`，其余3个直接调用 `swoff`；调用位于 `rf_rx_on_ltetdd`、`rf_rx_on_ltefdd`、`rf_rx_off_ltetdd`、`rf_rxtx_stop` 和 `rf_rxoff_tddcon`。更正：`0x806824/0x806924` 属于 `rf_rx_on_ltefdd`，并非之前误述的 `rf_rx_off_ltetdd`；必须按 ELF 符号地址范围判断，不能用反汇编行内对邻近文字池的符号注释判断归属。可用 `python -B tools/verify/verify_rffe_cp_callers.py` 复核[地址与跳板](../../../../records/rf/reference-rffe-cp-callers.json)。这只证明 SDK 中存在调用点，不证明当前固件走过分支、RFAD 事件送达或 RFFE 总线事务发生。

当前采集源码确实依次调用生成绑定中的 RF event 和 RX 请求入口；不能仅凭同地址把 SDK `cp.axf` 的函数套到 `cp.bin`：绑定 event 入口 `0x802d0720` 在 ELF 地址视图中处于其他函数内部，而 ELF 的 `rf_lte_event_req` 位于 `0x802b0b6a`。进一步按现有 CP 线性地址假设比较，本地 `cp.bin` 在绑定入口对应位置的632字节与该 ELF 函数有587字节相同，入口前4字节相同，支持两者存在对应关系，但并非字节一致。先前单凭 ELF 同地址得出的疑点不能视为绑定错误。还需核对差异指令和实际 PAC 的 CP 装载映射，才能把 SDK 中开关调用路径应用于当前固件。[可复核比较](../../../../records/rf/reference-rffe-cp-callers.json)不证明部署镜像或运行分支。

对这两段按 Thumb 顺序解码，31处编码不同的共同指令位置均保留相同助记符；差异包含 PC 相对地址、调用目标与立即数。例如 ELF `rf_get_freq` 调用目标 `0x802b0882` 对应 BIN 目标 `0x802d043a`，`rf_lte_get_semseg` 的 `0x802b07ea` 对应 BIN `0x802d039a`。这些是静态地址对应候选，顺序反汇编可能涵盖数据，助记符相同不证明操作数语义、控制流或函数等价；更不能据此证明前端调用已发生。PAC 的 modem 条目并未直接包含完整 `cp.bin`，其打包/装载关系仍待核对。

v24 停止排空后，核对 INFO、CP generation `0x526a0501` 和同一 epoch，使用 AP DDR 只读接口双读 `0x802d0720` 的632字节，结果稳定且与本地 `cp.bin` 相应区间逐字节相同。[记录和原始字节](../../../../records/rf/reference-rffe-event-runtime-v24.json)支持当前 AP 视图下该入口内容与 BIN 对应；并未确认完整 PAC 装载过程、CP 执行该路径或前端总线事务。

本地 BIN 的 scatter 记录将源 `0x804750bc` 的 `0x29724` 字节映射至 `0x804000`；对六个接收开启/关闭调用点按此映射核对 Thumb `blx`、ARM 跳板及目标：五个 `swon` 调用指向跳板 `0x81b598`，跳板目标 `0x8020306d`；一个 `swoff` 调用指向 `0x81b548`，目标 `0x802d3fcd`。它们相对 ELF 对应调用点偏移 `0x40`，不能直接使用 ELF 地址。[静态检查](../../../../records/rf/reference-rffe-cp-callers.json)验证 BIN 指令与 scatter 描述，不证明运行时低地址区域的字节、分支执行或开关总线动作。当前采集路径确实调用 event/RX 入口，但两者与上述接收开关调用间的分支和事件执行仍须闭合。

已核对 BIN 跳板实际目标函数的完整短指令序列：开启和关闭分别组合 `0x2c8000`、`0x2c8001` 与 `0x804ed5ac+6` 的 selector 左移4，再写入调用对象 `+0x2c` 的指针所指位置。对应 RAM2 绑定结构的 `config+44` 是 action 50（mipi_sw1）的命令指针；但还须确认现场所选事件的具体对象、指针有效性和写入后生命周期，不能仅根据结构偏移推断设备已发命令。

沿 BIN 两个具体条件分支核对字面量和参数，TDD 一条分支传入对象 `0x804ee978`，FDD 一条分支传入 `0x804efcc8`。它们是静态分支候选而非本次采集已选对象；另有其他分支，不能把其中任一对象套用到所有接收。频率证据保存的对象地址本身不证明这些分支被选中或 mipi 命令指针有效，且停机后读数可能已被覆盖。下一诊断应在 RX 调用前后保留所选对象和有界命令槽，验证新鲜性及指针范围，而非只读停止后遗留值。

进一步核对其他分支的字面量池，TDD 使用 `0x804eda30` 与 `0x804ee42c` 基址，FDD 另一分支使用 `0x804ef2a8`；其中 TDD 的一条路径将前者加 `0x268` 后传给辅助函数，与频率证据记录的一个候选对象一致。这一对应缩小了诊断范围，仍不证明该分支实际选中。不得解引用候选对象中未校验的命令指针；应在控制器命令内存允许范围、对齐及状态确认后才采样，且必须把调用前后值是否变化与路径执行区别报告。

v24 epoch25 已停止排空时，以 AP DDR 接口双读五个候选对象的64字节；各自 `+0x2c` 均为对齐的 RFAD 命令区域指针，分别为 `0x25101340/1420/129c/12c8/13ac`（后四个补齐同一 `0x2510` 前缀）。[只读记录](../../../../records/rf/reference-rffe-event-objects-stopped-v24.json)未解引用这些指针，也未确认采集时对象选择、命令值、新鲜性或总线动作；epoch是当时会话证据，不代表此后设备状态。

现有 ABI3 的512字节区在8字头和五个16字阶段行之后剩余160字节；阶段2/3分别在 RX 请求调用前/后。空间可以容纳有限候选的地址和值，但已有 ABI3 解码和构建验证不承认额外语义，因此不能在未协商版本时借用尾部。调用前后值发生变化可以支持命令槽被修改，值相同则无法区分“重复写相同值”和“未执行”；两种情况都不能证明 RFAD 触发或 RFFE 应答。后续候选必须明确这一判别边界，并在编译布局、地址校验、故障路径和实际收益验证后才交付刷写，不以该快照单独宣称选路闭合。

进一步核对 BIN 的 RX 请求函数 `0x804c00`：满足前置条件后，`0x804ed8` 检查 `[sl+2]` 为0才进入开启分派，`0x804ee2` 根据 `[r7+0x28]` 是否为1分别调用 TDD `0x806304` 或 FDD `0x8067ba`。这两个 BIN 函数各包含前述开关开启调用。前面还有 `[r1+4]` 等条件，且此处寄存器所指对象与本次采集状态尚未在实机确认；不能仅因请求入口被调用就认定开启分派或 RFFE 命令已执行。静态证据与边界见同一检查报告。

现已用 BIN 字面量池和 ELF 符号/DWARF 对应这两个字段：`[sl+2]` 对应 BIN `0x804ed566`，ELF 名为 `g_lterx_event_flag`；`[r7+0x28]` 对应 BIN `0x804ed5d4`，ELF 类型成员为 `st_rf_lte_info.u16_tddfdd_flag`。这是地址和静态类型的对应，字段名不代替取值及硬件效果；停止后的读取也不能代表调用时的值。更正此前对导出范围的描述：`proof()` 从 `0x804ed5ac` 复制11个32位字，**包含** `0x804ed5d4`，但不包含 `0x804ed566`；而 `proof()` 在调用后及 HELD 时还会重写，不能把最终记录当作调用前快照。若要验证实际分支，需在调用前采样两个字段及更早的分支条件，或取得等价的已有证据，并保留会话/阶段一致性。

该分派前另一个门禁由 BIN `0x804e64` 读取 `0x804ed738` 的半字，只有为0才进入后续事件标志检查；该地址来自 BIN 字面量池，硬件语义尚未确定。RX 函数自身在到达门禁前会执行其他读写，因此仅在函数入口外采样三个位置并不能单独证明实际分支，诊断设计还需核对中间写入和调用时序。

静态复查显示，RX 请求函数早期会在多个分支写入 `sl+6`（与 `sl+2` 是不同半字），不能把这两处状态混为一谈；此前置门禁不满足时函数还会写 `0x804ed73e`。这不排除间接调用或并发写入，仍需对运行时执行路径建立证据。现有 trace 阶段2在 RX 调用前、阶段3在调用后，但 ABI3 并未记录三个门禁地址；新增快照应使用明确的新 ABI 和阶段，且须证明写入后的字段实际可判别分支，再决定是否值得生成待刷固件。

RF侧 `0x7140` 分派器在 RF RAM门禁 `0xaf74` 非0时，将参数bits8:4提取为selector、低四位为操作号，经 `0x940c` 的selector→NV行表选取命令。op0/1/2/3分别对应 RX switch open/close、LNA open/close，所选地址依次为 `0x97b0/0x9ab0/0x9db0/0xa0b0 + 16×NV行`。`0x6712` helper在首项非0时发送最多4个非零项，复用 `0x10e8` 初始化helper。以保留本板 B3/B5/B8/B40 的selector/行注入映射，32组操作与门禁开/关原生执行对照通过；B40确实选择两条外部命令。这里只验证所注入映射和门禁下的分派过程，未读取实时0x940c/0xaf74，也未证明RFAD事件送达、命令时序或实际端口导通。

DWARF 的 `rf_lte_nv_fem_mipi_tag` 将 `mipi_init` 放在 FEM+0，`rx_mipi_sw_open` 在+100，`gsm_tx_mipi_sw_open` 在+0x10ac。CP 原始搬运把 NV 0x2ac 起的 FEM 数据送到 RF 本地 `0x974c`。初始化表项为小端 value/reg/slave/reserved；本机历史原始 NV (local-only research reference, omitted: `../../../../records/rf/runtime-frontend-current.rfnv.bin`)前八项是 `000e1d96 000e1e9a 000e1f2d 000d1c38 000f1d00 000f1e20 000f1f0f 000f1c38`，以后为0。前两项值与 RTM7916-51 的产品/厂商低字节 ID 一致，第三项含新 USID=13 的候选配置，第四项已经使用13；这支持地址迁移假设，尚不证明器件实际应答或迁移生效。ZW217 对应初始化项4–6为 F1D2C/F1E3D/F1F3F，板级配置明显不同。

| 软件步骤 | 原生代码与结果 | 验证边界 |
| --- | --- | --- |
| 初始化列表 | RF 0x183a检查首项；首项为0跳过整表。否则0x1960发送首项，0x184c..1858扫描至0x97b0，跳过后续0项 | 原始循环执行与8次独立 helper 执行相同；不是总线波形 |
| 初始化 helper | 0x10e8将byte0→0x3c008、byte1→0x3c000、`(byte2<<10)|0x72`的低16位→0x3c004 | 三次16位 MMIO写；外围协议/应答未模拟。参考 RF APB槽12名为RFFE |
| ID读取目标 | RF 0xa7fa = FEM+0x10ac+2，对应 NV 0x135a，即首项 GSM TX开关命令的slave字节 | 两份保留快照均为13；仅借用配置字段，不涉及恢复GSM解调任务 |
| ID读取动作 | 0x185c..190e先选择reg0x1e，再0x1d；控制字为`(slave<<10)|0x70`，轮询0x3c018，结果来自0x3c010 | 45组合成目标/ID/立即完成、延迟及超时验证通过；延时wrapper省略，无真实时序/ACK证明 |
| 保存结果 | RF 0x96e4=目标slave，0x96e6=reg1e结果，0x96e8=reg1d结果；等待超时则相应结果为0 | 所测片段只保存，不比较ID是否匹配。0可能是有效值或超时，单独读结果不能裁决身份 |

复核：`python -B tools/verify/verify_rffe_init_native.py`，见[原生执行/DWARF证据](../../../../records/rf/reference-rffe-init-native.json)。它固定校验 PULP 参考来源，执行真实 RF 指令并提供合成 MMIO 输入，不模拟 RFFE 从设备或模拟射频。v23 ABI3保存结果快照已部署并在BW0短采后读取：五阶段目标均为13、厂商/产品保存值均为0；配置指针、双读及目标匹配标志正常。[实机记录](../../../../records/rf/frontend-v23-hardware-trace.json)。这证实保存结果可观察，不能确认从设备身份或排除RTM7916；原始超时信息已经丢失，不能靠重复读同一保存值消除不确定性。

### 对 SDR 的价值和下一项

读回限制补充：原始BIN的swon/swoff已做8组合成输入执行，访问顺序为读取对象+44的32位命令指针、读取CP DDR `0x804ed5b2` 的16位selector、向命令槽写一个32位命令；helper不读取命令槽返回值。selector4/6的open命令分别为 `0x2c8040/0x2c8060`，close仅置bit0。见同一[原生证据](../../../../records/rf/reference-rffe-cp-callers.json)的native_helper_accesses。这并不证明物理RAM2可读或只写；在没有可靠读回语义前，零值不能作为执行失败或前端缺失的判据。此外ABI4主记录的selector/端口来自RF本地 `0x5000b538/0x5000b534`，不是CP DDR的selector和pending；RF本地状态晚于请求返回更新，既可能来自延后CP分派，也可能来自立即排定后到时执行的RFAD事件。不得用这一现象单独确认延后分支。下一次有效观测应区分CP分派与RF事件执行；这项未决不阻塞独立的USB等待策略工作。

延后RXON路径已补齐：SDK ELF中除了 `rf_lte_rx_data_req`，`rf_lte_agc_set` 也调用FDD/TDD RXON。后者上层包括 `l1cc_lte_txrx_int_hisr`、`l1cc_lte_iddet_int_hisr` 和数据更新/校准函数。CP BIN `0x804e64` 门禁非0时在 `0x804ed73e` 设置待处理标志，然后跳过立即RXON；AGC片段 `0x8053a0` 检查该标志，非0时按duplex分派至 `0x806304/0x8067ba`。四组请求门禁和三组AGC分派输入已执行原始BIN指令验证，均在RXON入口前停止；见[调用与原生片段证据](../../../../records/rf/reference-rffe-cp-callers.json)。这是合成状态下的软件控制流，不证明实机两次采集走了延后分支，也不证明RFAD槽读回语义。它解释了为什么立即返回快照不是充分观测点：下一步先定位实际分派及pending消费时机，必要时利用已有trace保留字加入明确的阶段状态，不能把更多相同零值读取作为进展。

ABI4命令槽观察已部署v25，离线[快照ARM验证](../../../../records/rf/frontend-v25-trace-arm.json)与[PAC配套验证](../../../../records/rf/frontend-v25-candidate.json)通过。它在现有512字节trace的160字节尾部记录RX请求前/后五个对象的指针及有效命令槽值。仅对4字节对齐、位于 `0x25101260..0x2510157c` 或 `0x25102260..0x2510257c` 的指针解引用；其他指针保留地址并标记无效。已验证边界、越界跳过、阶段清理和无控制器写入。物理断电恢复后，B5/B8两次BW0短采正常完成并排空，期间免复位改参；五个指针有效但两个阶段读值均0。片内selector/端口在请求返回后的阶段仍是上一路配置，到停止前已分别改变为4/2和6/3，见[实机观察](../../../../records/rf/frontend-v25-recovery-and-command-observations.json)。这不能证明槽未被写入或器件缺失，也不能裁决读回语义；不重复同条件快照。下一步定位原生分派时序及RFAD读回语义，再决定补充分支证据的最小方式。尚未证明RFFE应答或实物型号。

若 slave13 的寄存器0符合 RTM7916-51 mode control，且低五位为器件实际收到的数据，本机历史配置 B3/B5/B8/B40 的 4/5/2/8 分别对应 TRx9/TRx6/TRx4/TRx10。这是带条件的路径假设，不证明器件后缀、实际导通或板上走线；B40 还有 slave15/reg2，不能忽略第二器件。B5/B8 还使用不同的片内 RX 端口，验证外部开关时必须控制这一变量，不能把两条整链响应差异直接称为开关收益。

这些证据证明本分支有明确研究入口和可检验收益：取得前端身份/兼容组及路径映射后，才能把弱响应更准确归因于片内还是外部选路/滤波，改善覆盖与 Auto 选择。它们没有证明覆盖或灵敏度已经改善。用户已恢复[唯一主计划](../../../plans/goal-roadmap.md)，当前部署、待刷与实机证据以项目状态为准。

下一项继续追踪接收开关执行及latch/trigger关系，以及主动ID读取的完成/超时/总线互斥条件。只有这些条件明确后才考虑重新读取；同条件下不重复全0保存值快照。ID 无法唯一确认后缀时保留兼容组结论；必要时再请求顶标/BOM或总线测量条件。随后才做接收开关的最小单变量 B210 对照，保留 PA 关闭、不移植其他板 NV、不猜写 USID/未知控制位。器件识别受阻时继续 USB/软件交付，避免无限等待。

AGC前置门禁补正：之前三组片段验证从`0x8053a0`开始，不能代表从AGC入口即可消费RXON pending。已从`0x805382`和`0x8052a4`两个更早入口执行原始BIN共16组对照，覆盖RXOFF pending（`0x804ed73c`）、RXON pending（`0x804ed73e`）和duplex。两个片段均要求RXOFF pending非0才会继续到RXON pending检查；RXOFF pending为0时，即便RXON pending为1也直接退出本片段。RXOFF实现以明确的调用边界stub跳过，未模拟其真实效果。另独立执行`0x8052de`返回后清理，确认清除RXON pending及`0x804ed566`。证据仍在同一调用验证报告。实际AGC入口还有模式/计数等条件，这16组不证明全函数或设备执行。下一诊断若采样pending，应同时保留RXOFF pending、事件标志和调用阶段；pending非0不是执行证据，清零也可能有其他写入者，不能只增加一个最终标志就判定闭合。

RFAD事件提交补充：BIN跳板`0x81b618`指向`0x80297604`，执行事件字bit30置位；`0x81b620`指向`0x8029673a`，执行bit30清零。真实BIN helper在合成事件RAM下共8组执行，验证只对目标字做32位读改写、保留其他位。第一条普通TDD路径在`0x8063aa`置位一个事件，随后`0x8063be`写switch命令；`0x806416`可按另一个条件清零事件。FDD对应为`0x806850`、`0x806864`和`0x8068bc`。置位事件索引取配置+0x10，条件清零索引取+0x0c，事件bank基址为`0x25101000`；switch命令目的地址则来自对象+0x2c。不同索引字段的现场值可能相同，但不能把这几步概括成同一switch槽的“先写后触发”。报告保留各条件分支的地址顺序，不能把地址排序当作单条执行时间线。这些证据没有证明硬件取指、RF核执行或RFFE应答。

因此下一次有效观测需要同时区分三层：CP条件分派、被选事件的索引/有效位及命令目标、RF核收到action后的分派。仅扩大命令槽快照或只增加一个pending最终值无法闭合。不凭静态bit30含义主动重触发或修改事件。

v27停止排空、epoch5且INFO阈值2时，已用现有AP接口双读CP DDR对象与事件配置，期间状态完全一致，见[有界配置读取](../../../../records/rf/reference-rffe-config-stopped-v27.json)。BIN字面量与参数计算定位第一条普通TDD配置为`0x804ee9fc`，FDD为`0x804efd4c`，不是按对象固定加相同偏移推算。该TDD配置置位索引42、条件清零索引41，对应事件地址`0x251010a8/a4`；FDD索引96/95，对应`0x25101180/17c`。这里地址仅由配置计算，未解引用MMIO、未写事件。本次确认两组索引不同；它仍是停机后的候选配置，不证明采集选择这些对象、事件值新鲜或RFAD执行。地址推导已纳入同一原始BIN验证。读取过程中曾多读的`0x804efdd4`保留为未分类DDR，不能当FDD配置使用。

下一步诊断范围可缩至分派时的对象/配置、两种事件索引、RXOFF/RXON pending及RF端action执行证据；不能从这次静态配置直接选定实机分支。取得执行证据前，不直接将上述事件地址套给所有TDD/FDD接收，亦不主动清零、置位或重放开关命令。

RF侧可观测性核对：对已有32组`0x7140`分派用例增加RF本地RAM写入和`0x10e8`helper入口参数跟踪，全部通过。所覆盖B3/B5/B8/B40、开关/LNA开关及门禁0/1路径没有写入低64KiB RF RAM；helper调用次数与实际三次16位控制器写入的命令数一致，参数已保存在同一原生报告的`command_helper_arguments`。这意味着在这些路径内没有可供停机读取的执行计数/最后命令；不排除调用者、其他分支或硬件具有其他状态。不能再以重复读取相同RF RAM补齐本路径执行证据。

下一次诊断应优先在RF实际命令helper边界观察，而不是继续增加CP候选槽：记录采集开始基线及结束计数、最后命令参数和RF分派操作，才能区分“CP没有送达”“RF门禁跳过”和“已向RFFE控制器提交”。后者仍不证明ACK或端口导通。实施前须核对RF镜像装载/可修改代码区、旧指令校验、跳转范围、指令及数据缓存同步、RF局部RAM保留区和并发读取协议；不能把CP预留代码余量当RF代码空间，也不能直接借用未证明空闲的RF RAM。优先保留现有接收固件；在上述部署条件未闭合前不生成只增加更多静态字段的PAC。

镜像部署边界补充：当前采集绑定`rf_lte_init_dyload`的BIN入口`0x801d8c70`，24字节wrapper依次调用`0x801db858`、`0x802c3ec8`、`0x802f0670`并尾跳`0x801db8e0`。SDK ELF对应符号分别是`b_idle_init`、`rf_var_init`、`b_rfad_init`、`b_rfad_mem_init`，wrapper对应关系已纳入同一BIN验证。该静态wrapper没有直接搬运RF可执行镜像；但尚未穷尽各callee副作用，因此不能由名称断言完整流程绝不重载。现有重构覆盖RFAD变量、控制器及模板初始化，不构成RF可执行代码更新/指令缓存同步的证明。不得以`dyload`名称为依据热改RF指令，也不得默认补丁会在每次采集自动恢复。下一项需查明真正RF镜像装载或取得可验证的停核/恢复及缓存协议；此为v27阶段的热改限制；v28通过独立PAC冷加载验证观察补丁，不依赖热改协议。

已找到更具体的镜像装载线索：固定ZW217仓库`chip_drv/chip_module/chip/uix8910/load_modem.c`的`LOAD_modem()`匹配内存索引中的`riscV.bin`，先执行`CHIP_REG_AND(RF_ISRAM_BASE+0x35008,~0x10)`，源码注释为reset RISCV、等待CP释放，再调用`MEM_bzpLoad(LZMA_BZP_EX04,entry.addr,entry.len)`。uix8910头定义`RF_ISRAM_BASE=0x50000000`；helper检查目的8字节对齐和解压长度不超过目标长度。该源码关系已纳入原生验证报告并记录三个源文件哈希，但属于参考源码检查，未编译证明全部条件，也未证明当前AP执行相同加载器。当前v27 AP ELF按名称未找到LOAD_modem/MEM_bzpLoad/riscv符号，不等于实现不存在；不能仅凭参考注释直接操作复位位。

v27停止排空、epoch5时，现有AP接口双读`0x80000000`的4096字节内存索引，状态保持一致，记录见[当前镜像索引](../../../../records/rf/reference-rf-image-index-v27.json)。实际`riscV.bin`条目地址`0x50000000`、长度`0x9800`、原始cpneed字段1027；cpneed位义本轮不推断。该记录确认当前加载目标声明，与参考表驱动方式相容，但未读取RF代码、未确认解压内容或实际加载控制流。条目长度不是RF全部可用RAM大小，更不能据此把`0x9800`以后直接作为空闲区；已有RF运行状态在更高地址，插桩仍需明确保留区。后续PAC解码及v28入口签名证据已推进该问题；不再重复此静态快照，也不据此热改RF指令。

### 2026-10-29 当前只读快照

当前设备的只读前端与 RF/NV 快照分别记录在 [current-readonly-frontend-20261029.json](../../../../records/rf/frontend-current-readonly-frontend-20261029.json) 和 [current-readonly-rf-snapshot-20261029.json](../../../../records/rf/reference-current-readonly-rf-snapshot-20261029.json)。快照前后状态一致，读取没有写校准或改变 RF 配置。它确认了各 NV 行的 MIPI/GPO 表项、selector、RX port 和 switch 值仍可读取；这些结果只证明软件配置存在，不能确认 Air724UG 的实际 FEM 型号、MIPI 总线 ACK、物理滤波器或板级射频连接。后续只有新增总线事务或同条件外部参考对照时才继续扩展该分支。

