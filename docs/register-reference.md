# UIS8910 RF 寄存器与反汇编参考

本页是工程研究索引，不是 UIS8910 官方寄存器手册。地址来自本地 SDK 二进制、DWARF/反汇编、ZW217 同代参考和当前 CP trace 的交叉证据。凡标为“参考名”的字段都不能单独当作芯片硬件语义；凡标为“未知”的字段不应写入实验固件。

## English reference and evidence levels

This is a reconstructed engineering reference, **not an official UIS8910 register manual or a list of safe writes**. Names from same-generation ZW217 declarations identify hypotheses. Software access sequences and bitfield layout checks do not independently prove hardware function. Original RDA8955/8810 bit positions must not be transplanted.

Final exported tables: [129 address entries](data/rf-registers.csv), [named bitfields](data/rf-fields.csv), [original crosswalk and provenance](../records/rf/reference-rf-register-crosswalk.json). The current source counts are129 entries,51 named declarations,172 ARM-compiled bitfield values per view and2 address views. Entries include runtime RAM as well as MMIO, and some are reference-only candidates.

The fieldCSV exports100 named fields present in the129-entry crosswalk. This is a different count from the172 initialization values checked by the original compiler-based verifier; theCSV does not claim to be a full chip register database.

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| Reference declaration | field name, slot/bit layout in a pinned source | same chip revision, board routing, writable values |
| Original binary access | specific instruction, width and sequence | undocumented electrical semantics |
| Native/emulated comparison | same software accesses/outputs for tested inputs | PLL lock, analog performance, timing on silicon |
| Bounded runtime snapshot | values at the recorded phase/epoch | all-time state, safe read at arbitrary phase |
| Reference RF experiment | reception/tracking under recorded setup | continuous coverage or physical chip limits |

### Address spaces must stay distinct

| Space | Example | Interpretation |
| --- | --- | --- |
| RF-local MMIO | `0x30000` | local RF instruction address; not an AP pointer |
| CP RF alias | `0x50030000` | CP-visible alias for the corresponding RF window |
| GGE reference view | `0x05030000` | conditional `REG_ADDRESS_FOR_GGE` declaration; not proven active on this module |
| RF runtime RAM | `0xb520`, `0xb53c` | software coefficient/state storage, not PLL registers |
| CP RFAD | `0x25100000`; GPO+8, command+0xc | RF command submission/control, not the PLL itself |
| External RFFE | slave/register/value tuple | off-chip bus transaction, not any of the above MMIO maps |

Reference APB blocks occupy0x1000 slots: CTRL_1=`0x30000`, CTRL_2=`0x31000`, DFE=`0x32000`, ET=`0x33000`, RTC=`0x34000`, SYS_CTRL=`0x35000`, TIMER_1/2/3=`0x36000/0x37000/0x38000`, UART=`0x39000`, WATCHDOG=`0x3a000`, TSEN_ADC=`0x3b000`, RFFE=`0x3c000`. A32-bit declaration slot does not permit replacing an original16-bit MMIO access with a32-bit write.

### PLL, divider and filter facts

| RF-local address / CP address where applicable | Recovered meaning | Remaining uncertainty |
| --- | --- | --- |
| `0x30360`, `0x302c4`, `0x302c8` | B-group RX coefficient Q8, low/high fractional words; used by B3/B5/B8 software paths | physical oscillator/divider topology and RF lock |
| `0x30370`, `0x32228`, `0x3222c` | A-group coefficient locations used by B40 software path | do not assign B-group analog semantics to unnamed DFE words |
| `0x30364[7]`, `0x30374[7]` | anonymous control bit in observed RXON sequence | power/reset/enable label not resolved |
| `0x3036c[10:0]`, `0x3037c[10:0]` | reference `vco_bits` / static calibration code | not a lock flag; small values are not proof of unlock |
| `0x3036c[11]`, `0x3037c[11]` | reference calibration-ready bit | not independently identified RF LO lock |
| `0x3036c[12:13]`, `0x3037c[12:13]` | reference count/calibration enable fields | use original sequence; no speculative override |
| `0x30324[14]`, `0x30354[14]` | named BBPLL RX/TX lock | BBPLL state, **not RF LO lock** |
| `0x30410[14:11]` | reconstructed MDLL factor D | physical output divider topology not established |
| `0x302c0[1:0]`, `0x302e0[1:0]` | software stores D−7 in RX/TX SDM mode fields | cannot infer arbitrary supported divider values |
| `0x31040[1:0]` | DLPF reset-related reference fields | release/reset sequence is not transparent filter bypass |
| CP `0x25000038[6]`, `[7]` | RX_PRE FIR_EN / FREQ_EN | current raw setup clears both; other filters may remain |

The raw preparation word is `(BW<<8)|8`. This does not show that all DFE or frontend filtering is disabled. No supported external digital-filter bypass has been identified. Across the compared B-group1350/1375 MHz RXON bodies,93 writes differ only in3 frequency words; the comparison does not reveal a hidden filter bypass.

### Frequency arithmetic and consumer chain

RF helper `0x37f0` consumes100 Hz units. Runtime coefficients occupy RAM halfwords including `0xb520`(Q8), `0xb524`(fraction low), `0xb522`(fraction high), `0xb526`(factor) and `0xb53c`(working raw). These are software context fields; order is not a packed host C structure assumption.

```text
working_raw = requested_hz / 100
effective_raw = 2 * working_raw if working_raw < 10,000,000 else working_raw
D = 7 by default; alternative NV factor only if its enable is exactly 1
Q8 = floor(effective_raw * 256 / 260,000)
W  = floor(effective_raw * 2^28 / (260,000 * D)) modulo 2^32
```

The helper produces RAM coefficients; later A/B RXON code consumes them and writes RF-local registers. Arithmetic input doubling does not prove a hardware doubler. The D=7 coefficient encoding rolls at effective2912 MHz, not a measured physical tuning limit. `freq_mode`/mode selectors must be interpreted in their consumer paths, not assigned a universal hardware meaning from their names.

Relevant implementation: [frequency reconstruction](../firmware/rf_rebuild/rf_core_frequency.c), [RF reconstruction overview](../firmware/rf_rebuild/README.md), [PLL comparison](topics/rf/pll-reference-comparison.md), [native coefficient evidence](../records/rf/coverage-coefficient-chain-verification.json).

### RFFE and hardware identity

NV expectations, RFFE bus commands and saved ID results are different evidence. Air724UG is compatible with a RTM7916-51 initialization hypothesis, but no reliable physical ID/BOM confirms the exact suffix or wiring. Zero saved results can mean a genuine zero or a timeout. A matching expected constant is not a chip readback. B3/B5/B8 switch values and B40's extra slave15 path are software relationships until board transactions are independently observed.

RDA8955's9+18 SPI framing and UIS8910 GGE's15+16 framing differ. Neither their addresses nor bit positions can be ported by name. Details and pinned source references are in the [ZW217 assessment](topics/rf/investigations/zw217-reference-assessment.md).

The following Chinese tables retain the concise working reference. They express the same evidence boundaries.

## 地址空间

| 视图 | 地址 | 证据与限制 |
| --- | --- | --- |
| RF 本地寄存器 | `0x30000 + offset` | RF 原始指令和 `rf_core_*` 半字访问；不是 AP 裸指针 |
| CP RF 别名 | `0x50030000 + offset` | 当前 CP trace 与参考基址一致 |
| GGE 参考视图 | `0x05030000 + offset` | 由 `REG_ADDRESS_FOR_GGE` 条件头得到，不能证明当前设备启用 |
| RF 运行 RAM | 例如 `0xb464`、`0xb520`、`0xb53c` | 软件上下文、系数和状态镜像，不是硬件寄存器 |
| CP RFAD | `0x25100000`（GPO `+8`，命令口 `+0xc`） | 提交和时序控制，不等于 PLL 本体 |
| CP 系统选择器 | `0x50080020/24/28/48/58` | 参考命名存在，但各 bit 的实际选择值尚未全部闭合 |

## 调谐和状态字段

| 地址 | 当前解释 | 证据等级 |
| --- | --- | --- |
| `0x30360` | B 组 RXPLL Q8/fraction 写入 | 软件行为已验证，硬件物理单位未知 |
| `0x302c4/0x302c8` | B 组 RXSDM 频率字段低/高半字 | 软件行为已验证，物理分频拓扑未知 |
| `0x302c0[1:0]` | B 组 `dll_mode_rxsdm` 分频编码 | 参考命名/原始写入，未证明完整硬件语义 |
| `0x30364` | B 组 RXPLL 控制；写系数前清零、之后置位 | 写序列已确认，bit 的电源/复位语义未知 |
| `0x3036c[10:0]` | `rxpll_vco_bits` 参考字段 | 可读静态 VCO 码；不能作为 LO lock 判据 |
| `0x3036c[11]` | `rxpll_cal_ready` 参考字段 | 校准完成指示，不能替代真实锁定 |
| `0x30370` | A 组对应 Q8/fraction 写入 | 软件行为已验证，物理拓扑未知 |
| `0x32228/0x3222c` | A 组 DFE 频率字段低/高半字 | 参考头未命名，不能套用 B 组语义 |
| `0x30374` | A 组对应控制寄存器 | 写序列已确认，bit 语义未完全闭合 |
| `0x30324/0x30354[14]` | BBPLL1/2 `pll_lock_rx/tx` 参考字段 | 这是 BBPLL 状态，不是 RF LO lock |
| `0x31040[1:0]` | DLPF reset 参考字段 | 代码中有释放序列，不等于透明旁路 |

## 执行链

频率请求经过 100 Hz raw 解包、低于 1 GHz 的算术系数乘二、Q8/fraction 生产、A/B RXON 分派、SDM 和模拟表锁存，再由 RF 核异步执行。`0x37f0` 本身只计算并写运行 RAM，不直接写 RF 硬件；因此不能把该函数的乘二分支当成芯片物理倍频器或上下限。

当前 C 重构已对多个优化级、mode、selector、slot 和失败路径完成原生逐访问对照，但不包含完整冷启动、真实动态校准表、RFAD/CP/AP 互斥、真实 MMIO 延时和板级硬件锁定。它用于定位和验证软件行为，不能替代厂商初始化。

## 外部 RFFE

RFFE 命令是 `slave_id / reg_addr / reg_value` 的外部器件访问，与 UIS8910 片内 RF MMIO 分开。现有 NV/ZW217 证据显示 B3/B5/B8 使用不同的接收 switch 值，B40 还有额外 slave15 路径。当前物理器件只能声明为 RTM7916-51 兼容性假设；ID 读取结果存在全零、超时和有效零值无法区分的问题。

## 使用规则

1. 先以当前 PAC、当前 NV 和当前 trace 复核地址；历史寄存器表不是实时状态。
2. 不把 RDA8810/RDA8955 的 bit 位直接复制到 UIS8910。
3. 不写匿名 bit、未知校准值、未知 USID 或板级 PA 配置。
4. 反汇编结论只能支撑对应的软件路径；声称硬件能力必须另外有实机参考信号和改频跟随证据。

