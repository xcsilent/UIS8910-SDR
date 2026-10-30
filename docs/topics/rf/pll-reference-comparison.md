# RDA8955与UIS8910：PLL、频率字与状态字段

技术解释以本页、本机原始二进制和固定ZW217参考为准。历史实验只证明各自输入；Goal执行状态见主计划。本次目录整理未操作硬件。

## 结论及证据层次

- 本地8910二进制证明软件如何校正频率、选MDLL因子、计算系数、选择寄存器组和等待bit11；这些原始指令证据保持。
- ZW217的UIX8910头为`0x3037c.bit11`提供名称`txpll_cal_ready`、低11位`txpll_vco_bits`；B组`0x3036c`对应rxpll_cal_ready/rxpll_vco_bits。不再以“完全无字段定义”描述它们，也不再把bit11优先称为锁定位。
- 头文件默认CP基址与现有CP trace地址相符，布局经ARM编译核对；它不是当前Air724U硅版本的完整适配证明。**cal_ready的参考名称不等于已测得RF LO锁定生产条件**。
- BBPLL状态的`0x30324/354.bit14`虽名为pll_lock_rx/tx，但属于BBPLL；不能替代RF LO锁定证据。芯片物理上下限仍未知。

固定参考提交及文件来源见[ZW217核对](investigations/zw217-reference-assessment.md)。自动化[交叉表](../../../records/rf/reference-rf-register-crosswalk.json)核对117条地址项、51个匹配声明和两种视图各172个位域值；保留 ABI1/ABI2 的布局来源区别；当前 v22 部署 ABI2，匿名模拟字段保持未知。

## 前代寄存器与SPI不能直接搬用

| 项目 | RDA8955本地参考 | UIS8910本地证据 |
| --- | --- | --- |
| XCV命令 | 9位地址、18位数据，`((addr&0x1ff)<<22)\|(data&0x3ffff)<<4`，高字节先发 | GGE打包15位地址、16位数据，`((addr&0x7fff)<<16)\|(data&0xffff)` |
| 控制器 | RFSPI物理0x01a0e000，MIPS用KSEG1 | GGE CP视图0x4002e000；LTE RFAD CP视图0x25100000，另有RF核本地寄存器 |
| RXPLL_LOCK | 参考头逻辑0x10.bit17 | 不存在有证据的位号平移；当前0x3037c是TXPLL校准状态参考定义 |
| FREQ_MODE | 逻辑0x30.bit6；显式频率字与ARFCN模式选择 | 没有证明为同名8910字段；0x30290的freq_offset_mode也不是该字段 |
| CDAC相关逻辑地址 | 0x19 | GGE开机命令中0x005c；8810又是0xa6，无统一线性换算 |

8955头文件仍使用XCV_8809_PAGE类型，存在与运行驱动矛盾的字段/注释。五页0xa2000000起的声明是头文件/工具视图；实际已确认访问是SPI，以及位于RAM的调试请求镜像，不能当作已验证CPU MMIO。

8955频率字拆分：`W=((R05&0x3fff)<<18)\|(R06&0x3ffff)`。R05高4位另有电源控制，不能整字覆盖。0x08的MDLL头定义遗漏驱动使用的bit16；驱动0x10000/14000/18000/1c000注为7/8/9/10，不能只依赖旧头重写。

8955 boot的CHANNEL_FREQUENCY_MODE分支写0x00555，另一分支写0x00515，仅差bit6；结合表写0x05/06，可支持“显式频率系数模式”解释。运行自校准写0x20f57时bit6实际为1，旧注释Freq_mode=0不可信；结束0x20715则bit6为0。8910的RFAD窗口mode、RF核mode及带宽helper不是这个位。

源：8955 XCV头 (local-only research reference, omitted: `../../../inputs/reference-source/predecessors/rda8955-w17.44-idh/soft/platform/chip/regs/8955/include/xcv.h`)、8955驱动 (local-only research reference, omitted: `../../../inputs/reference-source/predecessors/rda8955-w17.44-idh/soft/platform/edrv/rfd/xcv_8955/src/drv_xcv.c`)、[8910打包指令](../../../records/rf/pll-uis8910-xcv-pack.txt)。

## 频率算术与表示边界

8955四组条件RX表共971项精确满足：

`W = floor(f_Hz × L × 2^28 / (26,000,000 × 9))`

GSM850/900的L=2，DCS/PCS为1；范围分别869.2–893.8、925.2–959.8、1805.2–1879.8、1930.2–1989.8 MHz。将同频和合成factor9送入8910原生0x37f0，16个代表项完整32位输出相同，证明算法共性，不证明相同硬件配置。

用户补充8955实际RX也是7分频。本地原始xcvSetArfcn函数体经ARM编译/执行，971信道×U01/U02共1942例：默认RX最终覆盖为divider7；该源码仅PCS/ARFCN611特选divider8和SDM模式1，不代表用户正在使用。**旧条件表分母9与运行默认7不是已闭合的同一运行链。** 条件表还有旧变量引用，不能原样当7分频配置使用；外部构建是否定义宏也不能仅凭本地搜索否定。

8910使用校正后的working_raw，单位100Hz：

1. 小于10000000时effective_raw=2×working_raw，否则不乘2。它不是已证实的裸芯片1GHz截止；mode0/index0有+7000校正，对应请求分界999.3MHz，其他校正不同。
2. 因子状态不为1取7；为1则经selector→0x940c行索引→0xa714取因子。
3. `Q8=floor(effective_raw×256/260000)`；`W=floor(effective_raw×2^28/(260000×D)) mod 2^32`。
4. B组Q8/low/high写0x30360/302c4/302c8；A组写0x30370/32228/3222c。8955为14+18拆分，8910为16+16，不能当作兼容寄存器图。

D=7的Q4.28无回绕表示边界为2912MHz，D=9为3744MHz；原生函数的边界前/等于/后三点已验证。低频乘2分支另有自己的选择条件。**编码上限不是VCO物理上限**，也不能解释所有约2.79GHz响应转折；随意把7改9会破坏配套时钟/校准，不能作为扩频方案。

## NV→MDLL→硬件写入的闭合链

SDK DWARF原始`rf_lte_mdll_dyn_tag`：52字节，mdll_en在+0，mdll表在+4；它位于FEM结构+0xfc4，FEM的NV起点+0x2ac，因此使能在NV+0x1270、表在+0x1274。这是名称和原始搬运链的对应，不是根据分母猜名。

| 输入/寄存器 | 已证实的软件含义 | 参考头补充及边界 |
| --- | --- | --- |
| NV+0x1270 | 恰为1才采用动态MDLL表 | 0、2、0xffff均回退默认7 |
| NV+0x1274起 | selector查表所选MDLL配置 | 不能把整表存在当作实际启用 |
| 0x30410[14:11] | 写MDLL配置值D，保留其他位 | 参考只名ana_ctrl_reg4，内部匿名，物理拓扑未知 |
| 0x302c0/302e0[1:0] | 写D−7；D=7..10对应0..3 | 正式参考名dll_mode_rxsdm/txsdm |
| 0x32a00[7:6] | 可选完成路径写D−7并OR 0x9007 | DFE位图缺失；不能给0x9007各位随意命名 |
| NV+0x176.bit15 | 经RF配置0x96e0→运行RAM0xb464，控制额外配置/等待流程 | 软件开关，不是实时lock反馈，也不等于“PLL lock enable”的已知字段 |
| 0x30364/374.bit7 | 调谐系数更新前清零，之后置一 | 参考仍匿名，不升级为模拟电源/复位语义 |

原始RF发布配置指针0x96b0到共享0x7e18；CP从0x50007e18读取后形成CP视图。CP BIN在0x801b9ae0..e8搬NV+0x176到配置+0x30；另一片段将NV+0x2ac的0x117c字节搬至RF配置+0x9c。8例开关搬运、16例因子表端到端、128例A/B因子控制已验证，BIN入口与ELF地址分开处理。

8810的MDLL_DIV_NUM在bits15:12、RX驱动用7/8/9，结构上支持比较；8910字段位移不同，不能套用相邻位。8810参考 (local-only research reference, omitted: `../../../inputs/reference-source/predecessors/rda8810/modem/modem-dualmode-2g/soft/platform/chip/regs/8810/include/tranceiver.h`)。保留的历史NV快照使能为0，因子按规则取7；快照不是实时查询。

## 校准状态的当前解释

滤波控制需分层：SDK DWARF定义CP `0x25000038.bit6=FIR_EN`、bit7=FREQ_EN；当前raw准备入口调用`rxcapt_rx_pre_profile`写`(BW<<8)|8`，两位均清零。实际CP更新与DAGC指令的离线验证通过，DAGC只改bits4:0并保留FIR_EN。因此复制FIR系数不等于启用该级，也不应重复以“清零FIR_EN”作为扩频实验。这仍不证明独立RF核DFE/模拟滤波已旁路，亦不是本轮实时寄存器读回。[字段及原生更新验证](../../../records/rf/coverage-v32-filter-rx-pre-native.json)、[分层核对](../../../records/rf/coverage-v32-filter-assessment.json)。

1350/1375 MHz成对请求的原生对比进一步缩小范围：保留本板B3 selector2/port1，mode0–5每组均93次MMIO写，顺序与地址完全一致，仅`0x30360/0x302c4/0x302c8`三个频率字不同。当前v32 PAC的B主体`0x4ecc..0x5360`及端口模拟表与SDK逐字节相同，当前PAC mode helper的六档实际写序列与SDK一致，且当前PAC系数helper已对两点BW0校正后及未校正输入单独验证。因此被测B主体不存在两点间的滤波/端口开关跳变；这不是当前RF RAM全量快照，也不覆盖完整冷启动、修改过的请求入口或物理模拟响应。固定滤波器响应和LO故障仍可能存在。[成对差异与范围](../../../records/rf/coverage-v32-boundary-controls.json)、[当前PAC系数](../../../records/rf/coverage-v32-boundary-pac-coefficients.json)。未找到独立可控旁路前，不为此生成只改匿名位的固件。

跨路径线索：[将历史B5与v32 B3转折归一到软件系数输入域](../../../records/rf/coverage-cross-route-lower-domain.json)，B5 687.5 MHz成功对应working688.2 MHz、倍频后1376.4 MHz，B3 1375 MHz成功对应1375.7 MHz；B5 681.25 MHz未检出对应1363.9 MHz，B3 1350 MHz未检出对应1350.7 MHz。两者selector/port不同，但默认factor均7、成功和失败的VCO码均接近低值。这支持优先研究共享PLL/LO域，不能证明系数输入就是物理VCO频率或共同物理截止：固件generation、日期、参考条件不同，尚非同条件跨路对照。下一步追踪实际LO输出分频/校准消费者，不依据接近数值直接改倍频阈值或MDLL。

当前PAC原生RISC-V频率函数 `0x37f0` 的反汇编给出明确边界：加载常量 `0x98967f`（9,999,999），当 `working_raw <= 9,999,999` 时执行 `slli s0,a0,1`，而 `10,000,000` 及以上直接使用原值；随后只计算Q8/fraction并写运行RAM，另写一次频率见证值，没有RF-local寄存器写入。该“乘二”是软件系数归一化，不能命名为硬件RX分频或模拟选路。后续RXON调用者才把系数送入 `0x30360/0x302c4/0x302c8` 等RF控制链；不能仅修改阈值或把MDLL factor 7 改成其他值来扩频。[原生验证及反汇编结论](../../../records/rf/coverage-lo-domain-native.json)。

v32反例：B3 1375 MHz在BW0完整参考通过时，RXPLL低11位为1；1350/1300 MHz未检出时为4/2，cal_ready均为真。因此不得将低VCO码或ready单独作为失锁/物理下限判据。1375 MHz BW5同样通过，而1350 MHz换BW5未恢复接收；尚不能排除固定模拟滤波或PLL/LO配置问题。[实测对照](../../../records/rf/coverage-v32-filter-assessment.json)。

四处原始循环0x4a78、0x631c、0x6578、0x6bd8读0x3037c并检查0x800，原生没有次数上限；16组合成状态只证明等待控制流，不证明硬件置位条件。重构实现保留有界budget，不能为试验强开无界循环。

ZW217参考名使该字可标注TXPLL_CAL_REG4：低11位txpll_vco_bits，bit11 txpll_cal_ready，bit12/13为cnt_enable/cal_enable。B组RXPLL_CAL_REG4在0x3036c，已由声明布局确认，不再只是排列对称猜测；v17起已进入ABI2双组trace，也没有证明B组有相同轮询顺序。

历史v10实机记录保留如下：

| B40中心MHz | 接收末期0x3037c | 低11位 | 当时参考结果 |
| ---: | ---: | ---: | --- |
| 1884.375 | 0x0801 | 1 | 仅状态/USB，无参考 |
| 2000 | 0x0958 | 344 | 双音和频移通过 |
| 2330 | 0x0cc8–0x0cca | 1224–1226 | 本轮对比不足，不推翻历史通过点 |
| 2790 | 0x0fa0 | 1952 | 单音门槛不足，但开TX带功率有提升 |

参考定义与数值随频率变化相容，可将其解释为VCO校准结果字段；**并未测出电容单位、调谐电压ADC或物理频率上下限**。bit11在各CP检查点为1，仅说明这些阶段采到了ready高，不能证明全部过渡窗口稳定锁定。

B5活动时0x3037c可保留A组旧值。早期 trace 只采 A 状态，因此包括 v16/B5 低端的“状态相同”不能用于排除 B 组校准/锁定问题。[早期结果](../../../records/rf/status-hardware-summary.json)。v21 已同步采两组状态：[687.5/681.25MHz 对照](../../../records/rf/lowband-v21-phase-comparison.json)中，成功与首音未识别两种结果均出现 RX ready=1、VCO=1/2，仍没有可判别成败的静态字段。CP RF_RX 返回后 working_raw 也可能仍为旧值，五阶段快照没有捕获 RF 内部最短过渡窗口。

SDK的LTE_NV_TYPE_FAST_PLLLOCK=2是消息类型编号，puWaitPllLock等是低功耗时序字段；它们没有映射到0x3037c。旧宏名也不能代替实际地址/位图。

## 已有验证与剩余边界

2026-10-28校准反馈消费检查：36次原始B RXON主体执行含共用helper内部，所测B3/B5/B8 mode0–5均不读`0x3036c/37c`，状态零/全1不改变操作序列，控制仍为33→b3。不能靠给这一段擅加ready等待解决低端转折。参考头的cnt_enable/cal_enable已加入主机解码；旧881.5/700/675MHz停RF前两位均0，ready均1，未提供活动校准时间过程。[对照](../../../records/rf/reference-rf-dual-v17-calibration-status-comparison.json)。需面向成功/失败新点的同步诊断或受控测量，匿名控制字段不猜写。

2026-10-28更新：B组组合与原始先计算后分派已有证据，不再重做。当前v20稳定NV快照的动态MDLL enable为0，虽B8/B40存储因子8，原始CP复制→RF系数计算的20例读跟踪证明跳过selector和动态因子表、选择默认7。`--frontend-snapshot records/rf/reference-rf-dual-v17-v20-frontend-mdll.json`可复核该配置分支；启用动态表后的真实selector映射仍未证明，不修改NV来猜测。该结果仅证明软件规则，非实时RF因子或锁定读回。

B5/BW0新离散点687.5MHz通过，681.25MHz首音未识别；当前无线参考检测转折不是芯片极限。[本轮证据](../../../records/rf/lowband-v20-lower-transition.json)。下一步只针对这一转折分析B组VCO/校准控制，或改变有依据的参考/板级条件，不继续无收益细扫。

B 组请求→系数→主体→模拟表组合与 NV/端口传递已有原始/C 差分证据，双组 cal_ready/vco_bits 和独立 BBPLL 状态已进入当前服务。剩余问题是间接 writer、匿名控制字段的物理含义和状态生产条件；仅在具体故障需要时开展有界诊断，不写未知校准，不重复最终恒 1 的快照。

调查报告涉及的板外FEM仍须本板器件与连接证据；不能依据675MHz未检出，直接判定裸芯片或某颗FEM截止。RF LO物理锁定判据、低频乘2对应的完整时钟拓扑及芯片上下限保留未决，不增加新的全寄存器覆盖门槛。

复核：`python -B tools/verify/verify_rf_register_reference.py`。前代/原生算术、NV和MDLL证据由`python -B tools/verify/verify_rf_pll_reference.py`生成，见[原报告](../../../records/rf/pll-verification.json)；该旧报告的“缺正式定义”只限定当时检查的本地SDK，不能否定此次新增参考头。两类报告都不等于硬件兼容性认证。
