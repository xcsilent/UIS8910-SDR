# UIS8910 RF 地址、初始化与调谐链

技术解释以本页、本机原始二进制和固定ZW217参考为准。历史实验只证明各自输入；Goal执行状态见主计划。本次目录整理未操作硬件。

现有接收使用LTE RFAD→RF RISC-V→RF/DFE→RXCAPT，取解调前IQ，不要求LTE解调。**当前服务仍保留厂商RF初始化和RX请求，独立C重构没有整体替代它们。** GSM/GGE的软件入口不同，不能据此推定两套完全独立模拟RF。

## 地址视图

2026-10-28 本机MDLL选择补证：v20停止排空epoch21的前端NV重复读一致，`NV+0x1270=0`；B3/B5/B8/B40行内因子分别7/7/8/8。扩展原有PLL验证器，执行原始CP搬运，再以原始RF `0x37f0` 在四个selector和五个working值下运行，共20例；读跟踪确认读取`0xa710`后跳过`0x940c`及`0xa714`表，结果因子均7。故当前配置中B8/B40的表内8不代表实际选择8。此证明以本机NV为输入的软件规则，不是RF运行RAM读回、PLL锁定或动态表启用后的selector映射。[证据](../../../records/rf/pll-verification.json)。复核：`python -B tools/verify/verify_rf_pll_reference.py --frontend-snapshot records/rf/reference-rf-dual-v17-v20-frontend-mdll.json`。

| 对象 | 地址/格式 | 依据与边界 |
| --- | --- | --- |
| RF核寄存器 | 本地`0x30000`起 | RF原始指令与`rf_core_*`的半字操作；不能作为AP裸指针 |
| CP访问RF寄存器 | `0x50030000 + offset` | 参考头默认基址与现有CP trace相符；这组已核对区域对应RF本地地址加`0x50000000` |
| 参考GGE视图 | `0x05030000 + offset` | 头文件条件分支`REG_ADDRESS_FOR_GGE`，不是当前设备启用此映射的证据 |
| RF运行RAM | 如本地`0xb464/0xb526/0xb53c`，CP`0x5000b464/...` | 软件开关、MDLL因子、working_raw，不能当硬件状态寄存器 |
| CP RFAD控制器 | `0x25100000`；GPO在`+8`、命令口在`+0xc` | 提交事件/时序/命令，不是PLL寄存器本体 |
| CP系统选择器 | `0x50080020/24/28/48/58` | 参考名RF_SEL、NB_LTE_SEL、GGENB_SEL、LVDS_SPI_SEL、RFSPI_MODE_SEL；位名不足以确定各0/1值选择哪个主设备 |
| GGE XCV命令 | 15位地址+16位数据，4字节大端发送 | 独立命令空间，未建立与全部RF MMIO的统一线性换算；不能套8955的9+18格式 |
| 板外FEM RFFE命令 | slave_id、reg_addr、reg_value | 本机NV中的外部器件地址，不是UIS8910片内寄存器地址 |

`globals.h`给出RF APB槽宽4KiB：CTRL_1/CTRL_2/DFE为槽0/1/2，TIMER_3为槽8。由此与原始地址对应，本地`0x32000..0x32fff`属于DFE、`0x38000`是第三定时器。参考`rf_registers.h`只声明到本地`0x31040`，没有DFE细节位图。

头文件REG32表示4字节槽；原始LHU/SH通常访问低16位，**不能因此统一改为32位访问**。CP调用入口另有Thumb位、BIN scatter与ELF VMA差异，必须使用匹配构建的binding。

## 两组调谐寄存器

A/B保留项目分组，RX/TX是参考头命名。接收使用TX命名组是原始程序行为，不能据名字判错。

| 功能 | B组：selector 0–12、17 | A组：其他有效selector 13–16、18–20 |
| --- | --- | --- |
| 常用路由 | B3/B5/B8 | B34/B38/B39/B40/B41 |
| 校准控制 | `0x30364` RXPLL_CAL_REG2 | `0x30374` TXPLL_CAL_REG2 |
| Q8写入 | `0x30360` RXPLL_CAL_REG1 | `0x30370` TXPLL_CAL_REG1 |
| 32位系数低/高半字 | `0x302c4/0x302c8` RXSDM频率字段 | `0x32228/0x3222c` DFE区，参考头未命名 |
| 分频编码 | `0x302c0[1:0]` dll_mode_rxsdm | `0x302e0[1:0]` dll_mode_txsdm |
| SDM控制 | `0x302cc`：`0x20→0x60` | `0x302e4`：`0xa0→0xe0` |
| 校准状态参考名 | `0x3036c[10:0]` rxpll_vco_bits；bit11 rxpll_cal_ready | `0x3037c[10:0]` txpll_vco_bits；bit11 txpll_cal_ready |

SDM控制变化均为bit6的`resetn_*`从0到1；bits5:4为int_dec_sel，保持2；bit7名为tx_rx，B=0、A=1。物理模式与完整时钟拓扑仍需另外核实。

`0x30364/374.bit7`写系数前清零、之后置一；参考只有匿名reg_91_bit70/reg_99_bit70，不能命名为PLL电源或锁定复位。`0x31040`有明确参考名DLPF_CTRL：2→3释放bit0 dlpf_rstn，bit1 dlpf_iir3_rstn保持1。

BBPLL1/2的`0x30324/0x30354.bit14`名为pll_lock_rx/tx，bit10为lock_steady、bit11为clk_ready。它们是**BBPLL**状态，不能直接当RF LO锁定；现有trace没有采集它们。

## 当前服务的执行顺序

入口是[rf_terminal_rx.c](../../../firmware/capture/rf_terminal_rx.c)的transaction()，支撑代码见[terminal_rxcapt_core.inc](../../../firmware/capture/generated/terminal_rxcapt_core.inc)。当前启用REUSABLE_STREAM、关闭FAST_TUNE，重采仍走完整事务。

1. 停止/排空上一轮；force_idle()停RFAD事件、恢复GPO并提交有界off-immediate。失败保留错误和所有权状态。
2. prepare()检查布局、状态及DMA资源，保存BW；isolated_phy_hw_init_and_probe()打开所需电源域、清autogate，依次调用厂商TXRX、DLFFT、LDTC系统初始化、RX FIR初始化、autogate初始化、RF LTE dyload初始化。保留这些依赖不等于启动解调。
3. prepare()继续分配DATA/HEAD DMA通道、设置描述符/回调/RX_PRE，启动DMA通道并保持必要电源约束。
4. 厂商初始化后以terminal_profile_nv_row()核对本次路由NV；缺行报0xa0b，不沿用旧路由。生成event/RX计划并初始化流环。
5. 正常分支先arm()配置/使能RXCAPT，再调用厂商RF_EVENT、写独立目标频率raw、调用厂商RF_RX。**不是等RF请求返回才启动DMA。** FAST_TUNE另有等待再arm分支，当前关闭。
6. RF核异步执行校正、系数、模拟配置、SDM/校准、DFE mode等。CP调用返回不等于RF调谐完成；采集循环处理DMA、环所有权、停止和恢复，IQ经DDR环交USB。
7. 停RF、停/排空DMA和USB后进入HELD；操作9重新执行完整事务。正常操作免芯片复位，不承诺无缝切频或严格连续样点。

匹配v16的入口例子：RF_LTE_INIT_DYLOAD=`0x801d8c71`、RF_EVENT=`0x802d0721`、RF_RX=`0x804c01`、RX_FIR_INIT=`0x80abc3`（含Thumb位）。这些是该BIN/scatter绑定，不是通用地址；binding定义了LTE_PHY_INIT，也不表示当前isolated路径调用了整个LTE_PHY_INIT。

## 重构代码的实际边界

[rf_rebuild代码索引](../../../firmware/rf_rebuild/README.md)区分当前链接和离线实现。

- CP层的帧时间、有界停机、SPI提交、RX计划等已进入当前服务；NV加载、boot恢复、前端NV解析等独立实现不等于替换了完整厂商冷启动。
- RF核层的请求解包、系数、A/B调谐前缀、A组prepare/finish和六档mode已有C还原及对应验证；这些rf_core文件未进入当前capture构建的链接源集合。
- **B组RXON控制流已组合还原，完整独立RF冷初始化仍未实现**；[prepare_b_prefix](../../../firmware/rf_rebuild/rf_core_rxon_prepare_b_prefix.c)包含入口、时钟、提交及原始`0x4fc4..0x50da`前缀，[prepare_b_mode](../../../firmware/rf_rebuild/rf_core_rxon_prepare_b_mode.c)对应模式中段。[组合入口rf_core_rxon_b](../../../firmware/rf_rebuild/rf_core_rxon_b.c)衔接这些阶段与B组完成锁存，保留共用校准/mode回调边界。与A组模拟表及配置不同，不能只换PLL地址。
- 本轮直接执行B组原始片段`0x500a..0x5040`，得到依次半字写`0x3041c=0x11c0`、`0x30420=0x5861`、`0x30424=0x7208`、`0x30408=0x4845`。其参考名为ana_ctrl_reg7/8/9/2，内部仍匿名。该片段与A组准备的地址/配置不同，进一步说明不能只替换PLL地址；它是有明确入口/停止点的局部执行，不是整函数或硬件验证。
- 完整NV/校准启动、模拟路由物理对应、RF LO锁定判据与芯片上下限仍未全部还原。

B组完成片段`0x529c..0x5354`已离线执行12组field/数字标志上下文：先`0x30364=0xb3`、`0x30408=0x4844`；数字标志恰为0时写`0x30498=7`；再用10字节行表+8执行`0x30414/0x304b4`模拟锁存，写`0x302cc=0x60`释放RXSDM resetn。与A组相同的锁存动作，所选表及SDM地址不同。

随后原始`0x5354`调用共用校准helper `0x453c`，参数为RXON上下文；`0x5358`读取context[0]，`0x535c`调用共用mode helper `0x3a7c`。因此B组后续可复用已有校准/mode实现。该完成片段没有读取cal_ready状态，不能外推整函数/被调用函数均不等待；不能为对称性擅加A组等待。

[B组针对性验证](../../../records/rf/reference-b-prepare-prefix.json)：前缀在-O0/-O2各100组原生/C全总线序列对照，各26个失败位置立即停止；另12组原始完成尾部及两个JAL目标检查。均为合成状态，不证明板级适配或物理锁定。运行`python -B tools/verify/verify_rf_prepare_b_prefix.py`复核。

### B组入口与系数提交

新增入口`rf_core_rxon_prepare_b_enter()`对应0x4ecc..0x4f90（不含ABI保存跳板）：先读0x30400/404保存，再写0x30364=0x33、0x302cc=0x20。0xb52a为0时写0x30498=2、0x304c0=0并直接应用10字节模拟行表+6到0x30480；非零时将该表值OR入旧0x30480。最后写BBPLL1_REGA即0x30320=0x501f。失败不发布saved输出，已发生硬件写入不回滚。

其后原始0x4f94调用共用0x4632时钟helper；`rf_core_rxon_clock_mode()`已独立还原：0x30350（BBPLL2_REGA）按mode0..3写501f→511f→517f；mode4/5在selector5/15时写501f→508f→50ff，其他selector仍用普通三写；mode6写501f→507f。原生mode>6不写，不意味着开放新档位。保留原始两条NOP不代表跨执行核仍具有相同物理延时。

`rf_core_rxon_prepare_b_commit()`对应0x4f98..0x4fc4：按原始顺序从b520读Q8写30360、b524读低半字写302c4、b522读高半字写302c8。**这里提交预先计算的结果，没有重新调用频率计算函数。** 调用者仍需证明系数生产已完成且属于本次请求，不能用缓存旧系数替代。

同一报告新增-O0/-O2各48组入口对照/21个失败点、45组时钟helper对照/110个失败点、系数提交逐访问对照及6个失败点。原始时钟helper的跳转表和读取指令实际执行，仅LWRR/BNEM1/BEQM1按旧PULP参考建模。

### B组模式相关模拟配置

原始`0x50da..0x529c`已完整还原为独立C模块；表内mode来自RXON上下文，不代表所有值都是可接入的带宽。mode6是原生特殊配置分支，不能当作比BW5更宽的新档位。

| 条件 | 0x3046c | 0x30478 |
| --- | --- | --- |
| mode=0 | 0x3c00 | 0x0400 |
| mode=6 | 0x1cf8 | 0 |
| 其他mode，0xb4e0非零 | `(mode<<13) \| 0x1c00` | `mode<<10` |
| 其他mode，0xb4e0为零 | `(mode<<13) \| 0x1c03` | `(mode<<10) \| 0x0180` |

上述结果按原指令截为16位；0xb4e0的正式字段名/上游配置来源尚未闭合。这里判断的是非零，与只认恰为1的MDLL动态表使能不同。

- 0x3047c：mode6写0x228e，其余写0x328e。
- 0x304b4/0x304b8：mode≤2写0/0；其他模式selector为5或15时写0x0a4d/0x2888，其余写0x0a57/0x2088。不能将这两种配置仅凭值命名成具体模拟频段。
- 0x30400：入口原始0x4ed6保存的旧值OR 0xc000；0x30404：入口0x4ee2保存的旧值OR 0xbf05（mode≤3或mode6），其他模式OR 0xb715。中段不重新读取这两个寄存器；替换实现必须在同一阶段保存它们。
- 0xb52a恰为0时写0x30498=6，完成段再写7；非零则两次都跳过。这个软件标志不能与cal_ready或0xb4e0混用。

同一验证报告新增-O0/-O2各675组中段原生/C全部读写序列差分、各1065个总线失败用例，执行覆盖本中段每个原始指令边界。原生标准指令由Unicorn执行，EXTHZ/BSET/BNEM1/BEQM1四种旧PULP扩展按固定参考解释。mode7/65535仅为合成边界输入，未开放到设备或接收软件。

频率raw单位100Hz；校正后working_raw小于10000000时算术输入乘2。默认MDLL因子7，动态表仅enable恰为1才启用；Q4.28因子7在有效算术频率2912MHz回绕，是编码边界，不是物理极限。[详细对照](pll-reference-comparison.md)。

### B组组合入口与系数生产先后

请求辅助字段已沿原始解包补证：`0x30054`半字高四位写context+0x14（slot），低十二位写+0x16。两种保留CP RXON前缀生成的辅助字为0x0050，因此所测BW0/BW5请求slot=0、context16=0x50，`0x453c`表索引为15×selector；超出保留RF镜像的表值仍为未知运行RAM，不能补零当默认校准。扩展576例/优化级原始/C对照发现并修正未部署解码器：0x6080取RXON bits14:13两位，旧实现仅一位；0x4221原始索引2、旧C为0。另一个retune入口0x6390仍只取一位，不能混同。mode0后续可能用ZFIF覆盖索引，本测试不冒充完整校正路径证明。

v21已部署并通过BW0短采和五阶段双组记录。相同B5/BW0、RX40/TX60下687.5MHz参考通过（14.80dB，双音199.922kHz，改频99.844kHz），681.25MHz首音未识别后停止；所有有限发射退出。成功与失败记录中RX ready均1、VCO低位均出现1/2，selector4/端口2及所记录选路字相同。这排除了“仅凭静态低VCO值即可判定接收失败”的解释，未排除真实动态校准/模拟/板级/参考限制。早期检查点可保留前次working_raw，不解释为新频点已完成。[同步对照](../../../records/rf/lowband-v21-phase-comparison.json)。

共用`0x453c`已明确为表/上下文应用函数：索引`15×selector+slot`，半字表`0x8764`写`0x30448`、`0x9438`写`0x30474`，成对半字表`0xaf78/af7a`写`0x3200c/32010`；mode6与其他mode选择不同`0x3044c`字，上下文+0x16参与`0x32020`，另有固定控制写入。共14次读取、9次写入，无硬件状态读取或轮询；“calibration回调”是历史接口名，不代表等待PLL校准。A组完成流程已提取并复用`rf_core_rxon_apply_tables()`，B组保持显式回调边界，尚未部署。原始RISC-V与C在-O0/-O2各252个mode/selector/slot/control组合逐访问相符，各23个失败位置立即停止。slot/control字段的物理意义、表值校准单位及硬件自主动作仍未知；测试输入不开放为新合法设备配置。[证据](../../../records/rf/reference-b-prepare-prefix.json)的`shared_table_application`。

组合入口`rf_core_rxon_b()`对应原始0x4ecc..0x5360，按入口保存→读取mode/时钟helper→提交系数→MDLL/模拟前缀→模式中段→B组完成锁存→校准回调→重新读mode→mode回调执行。缺少总线或回调时在访问前拒绝；总线失败返回−2、校准回调失败−3、mode回调失败−4，立即停止，不宣称已回滚。

原始0x6122起的调用链已直接执行：0x6134调用0x37f0，将working_raw（b53c）计算结果写到b520；返回后按selector≤12或=17经0x6158进入B组0x4ec8，其余经0x614a进入A组0x46f6。21个selector×3个工作频率×两种MDLL使能，共126例均先写入正确系数后才到达对应组入口。**原始软件调用顺序已证实**，实际RFAD数据是否属于本次请求仍须硬件事务上下文保证。

### RXON 返回后的共用频率配置

组内返回后，`0x6164`读 context mode，`0x6168`传入未校正请求 raw，`0x616a`调用`0x38a8`；retune 在`0x66ce`复用同一 helper。新增离线实现 `rf_core_rxon_post_configure()`，与现有默认表 retune 规划器并存，保留原始查表顺序：先读`0x32004`，写32位`0x50109050`，读 selector `0xb538`；selector=5直接选 profile，否则依次读`0x8530`四个32位中心及`0x91a0+4*mode`宽度，命中后停止读取后续中心。随后写`0x3033c/340/30c/310`并更新`0x32004`bit8。参考名字或该位物理功能仍未据此确定，不称其为 PLL 范围控制。

镜像默认频率窗口为782–812、1762–1802、1960–2000、2158–2198、2356–2396、2554–2594MHz（含端点），控制`0x50109050`二选一；这些是软件配置窗口，**不是接收范围**。另一 profile 依中心1966.08/1843.2/2580.48/2396.16MHz与mode宽度选择，selector=1、mode>3另有1962.0001–1970MHz条件。B5 selector4/BW0在681.25与687.5MHz使用默认表时均选同一路径，不能解释两点的接收差异。

[现有综合差分](../../../records/rf/reference-b-prepare-prefix.json)新增-O0/-O2各1492例原始指令/C逐访问比较、各128个失败位置，涵盖频率边缘、非默认运行时表与非法mode访问前拒绝。当前固件通用 bulk_read 只支持AP RAM；尝试只读`0x50008530`被明确返回RANGE，未读取该表、未修改固件或RF。因此默认表规则有原始软件证据，**当前实机表值仍未知**，不为此单独生成新版PAC。后续调用者标志/上下文保存及其副作用仍需具体追踪。

组合验证在-O0/-O2各264组上下文比较全部总线访问/回调顺序与参数，各618个总线或回调失败位置验证立即停止。另以校准回调修改mode的合成情况，验证后续确实重新读取。原生0x453c/0x3a7c内部在本次组合测试中按同一回调合同拦截，未重新执行其内部，也不意味着把ARM回调地址当成RF核可调用入口。ABI保存/恢复跳板、真实MMIO延时、冷启动依赖和RF接收不由此证明。

新增集成入口`rf_core_rxon_b_with_helpers()`通过半字适配调用实际C表应用和mode实现，与原始`0x4ecc..0x5360`主体内执行两个helper比较。当前-O0/-O2各90例覆盖mode0–5、selector2/4/5/6/17与对应合成端口、analog/digital标志、因子7/8/9、slot0/7/14和context16；各883个失败位置验证主体−2、表helper−3、mode−4立即停止，3种非法总线在访问前拒绝。原始model真实执行`0x453c/0x3a7c`，C不再把它们简化成回调。

集成内存模型仅在启动时写入初值，后续读取观察实际写入；不逐操作回放期望读取值。比较保留动态表、上下文、MMIO读取和全部写入，仅省略原始mode加载保留镜像固定系数的私有读取（C已嵌入这些值，独立mode差分仍比较全部45次写入）。未证明实机mode表未被修改；完整差分仅覆盖保留镜像及合成上下文。mode6不在该集成接口支持范围，既有BW6/7无新增通带结论不变。这里的“完整主体”不含caller、ABI、冷启动、系数生产部署、CP/AP桥、自主校准或RF接收证明，不能据此替换厂商初始化。

### RXON 调用者的软件状态发布

本轮补齐`rf_core_rxon_request_b()`：从原始`0x602c`读取RFAD `30050/30054/30058/30008`四个半字，按原序发布上下文；mode0读取ZFIF `b4de`、写入并重读`b550`，按`7b70+2*index`的有符号校正修改`b53c`。然后执行`0x37f0`对应系数链：先写Q8，再读MDLL状态及运行时因子表，写并重读factor，最后写fraction low/high，再分派B主体。当前-O0/-O2各150例与原始请求、系数和实际共用helper逐访问比较通过，覆盖mode0–5、selector2/4/5/6/17、低频及倍频阈值；各340个失败位置、5种非法请求/索引/因子情况通过。非法值可能在上下文写入后发现，不回滚。32位频率访问与16位RF寄存器访问分别保留。

整链测试发现并修正原有mode重建遗漏：mode0在原始`3c1e/3c32`分别重读`b550`，从`7b84+4*index`读取两个半字并写`320fc/32100`；索引0/1/2/3对应`5555:0017`、`aaab:00e8`、`0000:0000`、`5556:00e5`，不能固定为索引0。mode4/5读取`b538`，selector5/15的`32000`低位分别为`6b/7b`，其他选择器为`6d/7d`（还需保留数字标志控制的高位）。独立mode差分现为每优化264例、584个失败位置及2种写入后非法索引拒绝。上述字段仅证明原始软件行为，不据此命名物理频移单位或判定低频截止原因。

这批代码未链接到采集固件、未部署。验证只省略经原镜像比对的私有常量加载，运行时上下文（包括`b550/b538`）、动态表、MMIO和全部写入均保留。原division私有字节查表由ARM libgcc等价算术替代；未证明实机表未改、RFAD新鲜度、地址桥或冷启动。此小任务收尾，下一步围绕具体接收问题选择最小诊断，不继续无限扩大定时日志或反汇编范围。

`rf_core_rxon_publish_state()`对应`0x616e..0x6200`，位于 A/B 组返回及`0x38a8`之后，不是 B 组专属硬件校准流程。顺序为：读`0xb4ee`，仅等于1时读改写`0xb4d2 OR 0x10`并调用`0xacc`；再读`0xb4f2`，仅等于1时重新读改写`0xb4d2 OR 0x20`并再次调用`0xacc`。不将非零都当1，也不缓存首次回调之前的状态。最后写`0xb52c=1`、重新读回该值存到`0xb4d8`，读校正索引`0xb550`存到`0xb4dc`。

两处`0xacc`在调用者组合测试中保留明确回调；其时间记录主体现已单独还原验证，见下节，但混合宽度总线适配、目标核ABI和部署仍未完成，不能省略原始调用。后续`0x6202/620a`调用、ABI恢复、所有标志生产条件及跨核原子性不在本实现内。此段没有ready/VCO读取，也没有`0xb4e0`访问；软件状态1不证明RF接收成功。

[综合差分](../../../records/rf/reference-b-prepare-prefix.json)新增-O0/-O2各288例原始调用者/C逐访问及回调比较，各281个失败位置、4种非法合同访问前拒绝。合成回调会修改下一标志及共享字，验证调用者确实重读；原始`0xacc`内部未执行，不把回调模型冒充硬件行为。

[有界引用扫描](../../../records/rf/reference-rf-dual-v17-flag-direct-references.json)新增这些上下文字段：`0xb4ee`已找到`0x36f2`置1、`0x3778`清0；`0xb4f2`在`0x3542`置1、`0x35d0`清0。`0xb52c`也在其他路径写0/1/2，不能把它整体命名为布尔PLL锁定。扫描仅保守传播基本块内常量指针，会漏掉间接或跨自定义指令的访问；未发现引用不构成不存在的证明。`0xb4e0`仍只有此前已证实的清零生产点，后续间接writer仍未知。

### 共用 `0xacc`：五槽时间记录，不是 RF 锁定检查

新增 `rf_core_rxon_record_timing()`对应原始`0xad0..0xb52`主体，并包含实际执行的`0x902` helper。它先向字面地址`0x500901f0`写`0x100000`，最多读10次直到bit20为0；若10次仍为1，原始程序仍继续，不能把返回解释为计数器已就绪。后续用最后值低17位除24，与`0x50090104`左移16后的值合并，写入`0x928c+4*index`。

索引是`0x92ce`半字，两个数组均五槽。`0x902`依次读取`0x500900b8/bc/c0`，结果为`(bc&0xff)<<16 | (c0&0xffff)`；首个读取虽不影响打包值，也保留其总线副作用。结果写`0x92a0+4*首次index`，随后重新读取`0x92ce`并按原始16位递增后模5写回。不能将其当作同一时刻的原子快照或有校准单位的时间戳。

这段主体及helper只读系统MMIO、写RF本地RAM环和索引，未读PLL状态、未写RF配置。它对RXON调用者的作用可收敛为时间记录，不能继续当作未解的PLL控制入口；是否可删除仍需要全局消费者和目标运行证据，不在本轮修改。ABI保存/恢复未纳入本次差分。

[原始/C差分](../../../records/rf/reference-b-prepare-prefix.json)新增-O0/-O2各100例、各63个失败位置，覆盖立即就绪、延迟1/9次、始终忙、低位截取/除法边缘、全部五槽和两次索引读取得到不同值。硬件循环模型按保留RI5CY rev4手册第38页：`lp.setup`起点PC+4、终点PC+(uimm<<1)、次数rs1，对此指令为`0xaec..0xaf8`、10次；PULPv2 `p.sw`按保留opcode表的寄存器索引形式建模。系统MMIO响应为合成输入，未证明物理时钟、地址桥或实机时延；源码仍未链接和部署。

## 状态解释修正与后续

2026-10-28针对低频转折补证：原有验证器新增36次原始指令执行，覆盖B3/B5/B8端口、mode0–5及`0x3036c/37c=0/0xffff`两种状态。此次从`0x4ecc`执行至`0x5360`，实际执行`0x453c`和`0x3a7c`内部，不拦截为回调；校准状态不被读取、两种状态下总线序列相同，`0x30364`仍仅写`0x33→0xb3`。因此该主体不消费ready/VCO结果来修正控制，也没有基于该状态的重试。作用域限于所测上下文，不含ABI跳板、调用者尾部或自主硬件校准；不是“芯片无需校准”或“软件整链从不等待”的证明。见[b-prepare-prefix.json 的 native_b_feedback_consumption](../../../records/rf/reference-b-prepare-prefix.json)。既有C组合差分仍保持共用helper回调边界，两种测试作用域分开。

主机ABI2解码新增参考头中状态bit12 `rx/txpll_cnt_enable`、bit13 `rx/txpll_cal_enable`，不增加固件读取或改变IQ。八种位组合及实际链接trace写入/读取模型通过。旧v17记录重解释显示881.5/700/675MHz在停RF前均为ready=1、cnt_enable=cal_enable=0，VCO结果1301/81/2；固定检查点未捕获活动校准，仍无法区分锁定/失锁或板级衰减。[离线对照](../../../records/rf/reference-rf-dual-v17-calibration-status-comparison.json)。不得把当前v20的687.5/681.25MHz参考结果与这些旧状态字拼成同一次观测。

历史v16的ABI1五阶段trace固定采集0x3037c，即A/TX命名校准状态，**没有采集B组0x3036c**。B5/675MHz等实验里0x3037c与正常点相同，不能据此推断B组已经锁定或未发生校准。bit11按参考标注cal_ready，低11位按参考标注vco_bits；物理生产条件、单位和硅版本适配仍需独立证据。旧ABI与原始读数保持。v17 (local-only research reference, omitted: `../../../archive/consolidation-2026-10-28/outputs/firmware/rf-dual-v17/README.md`)已刷入，ABI2双组记录实机可读取。

调查报告为FEM/RFFE提供线索，尚未确认Air724U器件型号、TRX接线和滤波器；不能把其他模组的RTM7916/RPM6743当成本板已知器件。先对应本机NV的slave/reg/value与板级连接，再解释低频衰减。

0xb4e0已找到明确清零生产者：原始0x10c2/10c6形成b468，0x10d6向+0x78半字写0；4组初值执行至0x10da均为0。这里只证明初始化清零，不证明没有后续写入，也未取得正式字段名。

### 本机NV到模拟表：当前已闭合的部分

已现场重新核对v16/generation0x52620501、接收停止排空、无SDR消费进程；只读取得同epoch278的NV前缀/信道表及完整前端NV，未发射或改变RF配置。[身份](../../../records/rf/reference-live-route-preflight.json)、[NV](../../../records/rf/reference-live-route-nv.json)、[前端NV](../../../records/rf/reference-live-frontend-nv.json)。这些是当时快照，不替代后续实时检查。

两种原始CP RXON打包前缀均按本机NV选定行的RX端口，将`selector<<8 | port<<4 | BW`送入RFAD参数。再执行RF原始0x602c..0x6080，确认低4位到context[0]、端口bits7:4到context+4、selector bits12:8到context+8。原来的独立C解码仅保留3位，已用0x0080复现丢失bit7并修正为4位；-O0/-O2各384组对照通过。当前本机端口0–3不受旧截断影响；8–15仅做解码边界测试，不开放为合法模拟表行。

| 路由 | NV行 / selector / RX端口 | 原始二进制模拟行 | 0x30480行值 | 0x30414行值 | 0x8184共享表→0x30468 |
| --- | --- | --- | --- | --- | --- |
| B3 | 2 / 2 / 1 | 0x8a54+10×1 | 0x0002 | 0xfe08 | 0x20ea |
| B5 | 4 / 4 / 2 | 0x8a54+10×2 | 0x0002 | 0xfd08 | 0x01ea |
| B8 | 6 / 6 / 3 | 0x8a54+10×3 | 0x0001 | 0xfd08 | 0x80ea |
| B40 | 22 / 15 / 0 | 0x84f0+8×0 | 0x00a0 | 0xfe08 | 0x10ea |

此表是**实际板级NV端口→原始CP打包→原始RF解码→保留RF二进制默认表**的对应，不是运行RF RAM/最终寄存器读回。应用时还有OR/掩码/锁存，A组0x30430还可能按0x92cc改用0x84b0表。B5/B8不仅使用不同的外部MIPI开关值（本机NV slave13/reg0值5与2），片内默认选路字也不同；不能仅凭共享系数算法把它们视为同一模拟路径。外部slave13对应哪个FEM、各bit对应哪个物理引脚仍未知。

以上链验证进入原有报告的retained_board_route_chain字段。复核命令：`python -B tools/verify/verify_rf_prepare_b_prefix.py --runtime-snapshot records/rf/reference-live-route-nv.json --frontend-snapshot records/rf/reference-live-frontend-nv.json`，只读已有文件、不访问设备。

进一步将上述本板端口与镜像默认模拟行用于完整B请求链，而非止于解包：新增B3/B5/B8各mode0–5、raw6812500/8815000共36组，在-O0/-O2逐访问比较原始请求→系数→B主体→实际共用helper；请求链现每优化186例、680失败位置、5种非法输入通过。30418/3040c/30480/30468按对应表行落地；30414依次写表值、表值OR0x40、表值OR0x60，属于锁存过程，最终值不是原表值。条件为模拟/数字flag0、MDLL bypass及合成复位寄存器；两个raw用于覆盖配置组合，不声称该路由实际能接收它们。无RF访问/写入，未证明实时RF RAM表、板级接线或物理频率范围，B40 A组另行判断。

v17 ABI2在原五阶段记录A/B校准、selector/端口、0x30468/480、0xb4e0/b52a及独立BBPLL状态，每阶段19读，不轮询或写RF；512B DDR和代码容量已检查。已实机读取完整记录：B5/881.5 MHz接收末期RX vco_bits=1302；700/675/650 MHz无参考的状态对照分别81/1/2，ready均1，selector4/端口2及0x30468/480相同。675/650接近数值下端，但2不支持简单称为恒定饱和；ready仍不能替代锁定或参考接收。[原始证据](../../../records/rf/reference-rf-dual-v17-hardware-summary.json)。当时B210未枚举；随后用户接入，实际参考对照见本文末更新。当前AP通用接口仍不开放RF总线直接读取。

## 复核入口

`python -B tools/verify/verify_rf_register_reference.py`生成[地址交叉表](../../../records/rf/reference-rf-register-crosswalk.json)：当前含新诊断共117项、51个参考声明匹配，两种视图各172个位域值经ARM对象检查。trace_abis保留历史ABI1/ABI2来源；当前部署为ABI2读取范围；不是硬件仿真或读写授权。

原生差分证据：[频率/前缀](../../../records/rf/runtime-frequency-native-verification.json)、[MDLL/NV](../../../records/rf/pll-verification.json)、[mode](../../../records/usb/rf-mode-rebuild-verification.json)、[RX_PRE](../../../records/usb/rx-pre-native-verification.json)。RX_BITSEL由DAGC调节，数值8不表示8位存储；数据仍是原生12位、LE16+16。

仅为具体缺失事实查历史完整反汇编 (local-only research reference, omitted: `../../../archive/legacy-2026-10-23/records/audits/2026-10-23-sdr-convergence-v1/before/docs/topics/rf/init-sequences.md`)。BCPU全ROM、GSM解调与ZSP研究继续暂停，不恢复旧实验分支。


2026-10-27 v17参考复核：B210重连后，B5 881.5和700 MHz参考及改频通过；675 MHz首音未识别。700/675的RX `0x3036c`为`0x851`/`0x802`，selector4/port2相同，尚不能解释为PLL锁定或芯片下限。所有有限TX结束。下一步需可控参考或板级资料区分弱信号成因，其他主线不受阻。[证据](../../../records/rf/reference-rf-dual-v17-reference-comparison.json)。

对v17 B5/BW0 881.5、700及675 MHz参考采集的15个阶段快照复核：0xb4e0和0xb52a在这些观测点均为0；这不是连续采样，不证明不存在瞬时写入、所有生产路径已知或675 MHz弱响应由这两个标志造成。[对照](../../../records/rf/reference-rf-dual-v17-runtime-flags-comparison.json)。

对原始RF代码做受限的AUIPC/ADDI直址扫描，定位0xb4e0的直接写入0x10d6（清零）与读取0x5128（B模式分支）。扫描不分析间接指针及legacy PULP指令，不能证明无其他写入，也不确定硬件字段名。[结果和范围](../../../records/rf/reference-rf-dual-v17-flag-direct-references.json)。

后续扩展同一扫描器：按原生指令长度推进，在基本块内追踪 LUI/AUIPC/ADDI、部分压缩指令的常量与寄存器复制，并检查跨越该半字的宽访问；未知/PULP/控制流指令立即清空推断。复制后偏移、未知/分支隔离、跨半字写入测试通过。扫描仍只得到上述两处，未新增写入来源。这个负结果不足以关闭间接别名、跨过程配置或外部写入，不能将标志命名为某个硬件使能。下一项仍采用 v21 同会话参考及阶段状态对照，不据此猜写该标志。
