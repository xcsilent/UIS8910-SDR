# 900 MHz 附近低频路径实测

> Historical research summary. Version/deployment/next-step labels below describe their original experiments. Current release and performance are defined by the active manifests and docs/performance.md; deleted raw and old firmware are unavailable.

最新v21：[900MHz共享发射窗口B5/B8对照](lowband-v21-b5-b8-shared-tx-900.json)，BW0/RX索引40/TX gain40。每个单音使用同一有限TX进程交替采集两路及+100kHz改频，八采集排空、两次TX退出0。B5开关58.77dB通过，B8开关7.37dB未达10dB门槛；两路双音199.92kHz/改频100.08kHz均跟随。减少了分开发射会话的变量，支持保留900MHz的B5 Auto优先，不证明校准灵敏度差或具体片内/板级原因。TX日志均出现无时间戳U标记，参考连续性未知。没有新增连续范围或芯片极限；该实测发生在v22刷入之前。

2026-10-28 v20补测：[687.5MHz](lowband-b5-6875-v20-reference.json)通过，开关13.43dB、双音199.922kHz、100kHz调频测99.844kHz；[681.25MHz](lowband-b5-68125-v20-reference.json)首音未识别，后续跳过。B5/BW0、RX索引40、TX gain60、既有天线，距离本轮未测。全部TX正常结束、六次采集排空，文件队列无丢块；681.25首音设备/主机差8192B，其余一致。不是连续范围或物理芯片极限。[汇总和下一步](lowband-v20-lower-transition.json)。不再沿相同条件反复二分，需要区分校准/VCO与模拟/FEM/参考限制。


**v17 参考对照：** B210序列号DEVICE_ID_REDACTED，已验证TRX1映射，两天线约30 cm为用户此前报告。B5/BW0、RX gain index40：881.5 MHz（TX gain40）与700 MHz（TX gain60）双单音及100 kHz改频跟随通过，开关差分别47.72/15.11 dB；675 MHz（TX gain60）首音未识别，停止后续发射。各TX均已结束，采集排空。三个点的`0x3036c`分别为`0xd15`、`0x851`、`0x802`，后两者低11位为81和2，同为selector4/port2；这不能证明锁定位、饱和或物理下限。当前条件非校准参考，不能区分天线、板级和片内因素。[对照及完整证据](reference-rf-dual-v17-reference-comparison.json)。
v17已部署并读取B组状态；B5/700、675、650 MHz的RX vco_bits为81、1、2，ready均为1，选路快照相同。该轮无B210发射，不能据此证明接收或芯片极限；当时UHD未枚举B210，随后用户已接入并完成参考测试。[条件和完整记录](reference-rf-dual-v17-hardware-summary.json)。

参考源码及原生指令复核修正：旧实验记录的0x3037c是A/TX命名校准状态，B5/B8调谐属于B组，旧状态相同不能用来排除B组校准/锁定问题。当前本机NV→CP打包→RF解码→默认模拟表对应已核对，B5/B8的片内默认路由字与外部MIPI命令均有区别；这仍未证明低端衰减原因或芯片极限。[当前分析](../../docs/topics/rf/init-sequences.md)。

v16配套SDR++的[BW5服务模式实机生命周期](lowband-v16-sdrpp-bw5-hardware.json)通过：约5秒测试收到5,142,000复数样点，活动100 kHz改频后应用881.6 MHz，停止排空、错误0；状态报告376次满环停止、累计观察间隙3622 ms及排空丢弃472,000字节。统计范围跨两次会话，样点丢失数量和位置未知；不能将平均收数率当30.72 Msps突发采样率或宣称连续IQ。本次无外部参考，服务模式跳过桌面FFT，未验证桌面频谱画面；不能据此单独证明有效通带或BW5参考通过。

v16 B3/1710 MHz软件下限补测：BW0、RX gain index40、B210 TX gain40时[首音不足](lowband-v16-b3-1710.json)；TX gain60时[双单音与改频通过](lowband-v16-b3-1710-gain60.json)，开关对比20.98 dB，100 kHz改频跟随99.84 kHz。全部有限TX已结束。该点为表外真实接收证据，且受参考强度和现有天线条件影响；不证明1710 MHz以下不可接收、连续覆盖或芯片极限。

补充高频重叠路径对照：v16 BW0、1900 MHz、RX gain index40、B210 TX gain40、既有两天线条件，[B3](lowband-v16-b3-1900.json)与[B39](lowband-v16-b39-1900.json)均通过双单音、开关对照（46.69/46.63 dB）及100 kHz改频跟随（均99.84 kHz）。参考频点的未校准积分功率B39约为B3的2.34倍，但两次发射与噪声、AGC/前端并非校准测量，不能据此宣称灵敏度差或修改Auto；同一个点也不代表连续覆盖。全部有限发射结束。B3表外1900 MHz有实机接收证据，B39未证明新增覆盖或明显稳健性收益，因此不加入默认Auto。

后续部署：已将实机服务模式验证的v16 Auto插件及配套库安装到用户便携版，哈希核对一致，配置及旧文件已备份。安装记录 (`../../outputs/host/sdrpp-auto-v16/installation.json`; historical artifact removed during v0.1 consolidation)。桌面视觉验收仍未进行；下方“尚未安装”描述属于安装前记录。

共享Auto策略已构建到Soapy (`../../outputs/host/soapy-auto-v16/build.json`; historical artifact removed during v0.1 consolidation)和SDR++ (`../../outputs/host/sdrpp-auto-v16/build.json`; historical artifact removed during v0.1 consolidation)独立候选，均使用`outputs/host/auto-v16`库。v16上[Soapy CF32/CS16实机生命周期](lowband-v16-soapy-auto-hardware.json)与[SDR++核心服务BW0/BW1生命周期](lowband-v16-sdrpp-auto-hardware.json)通过；另以[SDR++核心服务实测](lowband-v16-sdrpp-hysteresis-hardware.json)从B5的917.5到920切B8，回917.5保持B8，到915切B5，改频后有数据且停止排空。无外部参考发射，不代表桌面画面验收；用户便携版尚未安装新候选。

920 MHz同条件对照：[B5](lowband-v16-b5-920.json)弱峰跟随但开关对比8.94 dB未通过；[B8](lowband-v16-b8-920.json)通过，对比49.95 dB。基于915/920/924.9 MHz离散证据，当前共享Auto源码改为B5向上到920 MHz切B8、B8向下到915 MHz切B5，中间维持当前路径；无当前路径时920 MHz起选B8。缺某路径时仍服从可用列表。它是经验性默认策略，不保证所有频率和板卡最优。[Windows DLL 32例](lowband-v16-auto-hysteresis.json)通过；[v16实机Auto 920 MHz](lowband-v16-auto-920-hardware.json)选择B8、短采排空通过，但未在该Auto短采中使用外部参考。Soapy/SDR++旧构建和用户便携插件尚未更新，不能声称已采用新策略。

v16同条件重叠路径对照：BW0、RX gain index40、B210 TX gain40、已报告双天线条件。915 MHz [B5](lowband-v16-b5-915.json)通过，开关对比36.20 dB；[B8](lowband-v16-b8-915.json)峰随改频移动但对比8.93 dB未达门槛。924.9 MHz [B5](lowband-v16-b5-9249.json)通过但对比11.65 dB，[B8](lowband-v16-b8-9249.json)通过且对比58.58 dB。各TX均有限并结束。两点表明现有在924.9 MHz继续选B5的策略值得优化；这不是标定增益或前端衰减比较，不能仅凭两点宣布整个区间的最佳阈值。下一步在920 MHz做同条件B5/B8对照及必要的相邻验证，再调整共用Auto并回归切换，避免频繁往返。

针对675 MHz弱参考的增益对照：保持B210 TX gain60及现有天线条件，将接收gain index从40提高至80，[首音仍未达到判据](lowband-v16-b5-675-rx80.json)，TX已结束。背景积分功率由约3.6万增至约1589万（未校准分析值），提高增益同时放大了噪声；不能将该变化解释为标定增益或判定芯片截止。700与675/650/600 MHz的阶段快照均观察到状态字3850、配置divider7，但状态bit11尚未确认是PLL锁定，无法据此排除PLL/校准问题。需要可控、已知电平的参考链路或板级前端信息才能进一步区分天线耦合和接收路径衰减；在当前无线条件下不重复相同盲扫。

**v16已刷入并实测。** 用户确认刷入，BW1短采排空通过，[generation核对](lowband-v16-postflash-identity.json)为`0x52620501`。B5/BW0、RX gain index40、B210 TX gain60，现有天线约30 cm条件下：[700 MHz](lowband-v16-b5-700.json)双单音和调频通过，开关对比13.10 dB；[675](lowband-v16-b5-675.json)、[650](lowband-v16-b5-650.json)、[600 MHz](lowband-v16-b5-600.json)首音未达到判据，其后采集跳过。每次有限发射均结束。700通过与675未通过是当前参考条件下的离散观测，不证明连续区间、单调转折或芯片物理下限，尚不能区分天线/发射、板级和片内影响。v16实验软件下限500 MHz也不是物理能力承诺；先分析条件及可用更强参考，再决定是否继续低端扫描。以下v16待刷为历史。

**v16待刷低频候选：** PAC (`../../outputs/firmware/lowband-v16/Air724U_UIS8910_SDR_BW0_USB_v16.pac`; historical artifact removed during v0.1 consolidation)，SHA256 `9c375bd8997c3eef191ca53927d0d5e006158c949f60825d0fda899274be4055`，generation `0x52620501`，未部署。B5请求范围扩展至500–925 MHz；500 MHz是有界实验下限，不是物理能力。厂商NV/CP/RF/boot保留，B5表外初始化锚点仍是channel2400，运行时NV门禁保留。正常连续服务不变。匹配主机在`outputs/host/lowband-v16/`。

[原生500–700 MHz系数30例](lowband-native-sub700.json)、[AP](lowband-v16-ap.json)、[CP](lowband-v16-cp.json)、[NV门禁](lowband-v16-nv.json)、[USB描述符](lowband-v16-descriptor.json)、[候选PAC](lowband-v16-candidate.json)及[Windows选路](lowband-v16-host.json)离线通过，未证明实机RF或USB。刷后先核对generation及BW1短采排空，再以700 MHz参考复核并向低频探测；有限发射结束即停。用户便携版插件仍是旧版，实验使用配套CLI。

最新参考强度对照：B5在[712.5 MHz](lowband-v15-b5-7125-gain60.json)及[700 MHz](lowband-v15-b5-700-gain60.json)，B210 TX增益60、接收gain index40时均通过双单音和100 kHz改频跟随，开关对比分别15.98/13.92 dB。700 MHz已到v15软件下限，并非物理截止；同点TX增益50不足，说明参考条件显著影响判定，不能分离天线、板级与片内衰减。两个有限发射均已结束。下一步研究并构建进一步扩展请求范围的候选，不移植未知校准。

v15连续软件生命周期已实测：[Soapy](lowband-v15-soapy-hardware.json)在BW1下CF32/CS16分别收到18,438,000和18,284,000复数样点，自动B5→B40改频、停止排空和重启通过；[SDR++原生插件](lowband-v15-sdrpp-hardware.json)在隔离运行目录加载真实目标核心，BW0/BW1分别收到8,786,000/17,638,000复数样点，改频、跨路径Auto和停止排空通过。该SDR++测试为服务模式，不是桌面画面或频谱质量验收，便携版插件未安装；样点数量不是无间隙证明。本轮无B210发射。

**v15已刷入并实测（2026-10-27）。** 用户确认刷写，BW1 500 ms短采通过并排空，设备及主机各7,648,000字节；[实时CP generation](lowband-v15-postflash-identity.json)为`0x52610501`。以下“待刷”是构建时记录。

BW0 B5、接收gain index40、B210有限发射，仍为已报告的TRX1/两天线约30 cm条件：

| 接收中心 MHz | TX增益 dB | 结果 | 开关对比 dB | 100 kHz改频跟随 kHz |
| --- | ---: | --- | ---: | ---: |
| [824](lowband-v15-b5-824.json) | 40 | 通过 | 12.82 | 99.84 |
| [800](lowband-v15-b5-800.json) | 40 | 通过 | 14.96 | 100.08 |
| [750](lowband-v15-b5-750.json) | 40 | 首音不足，后续跳过 | — | — |
| [750](lowband-v15-b5-750-gain50.json) | 50 | 通过 | 11.98 | 100.08 |
| [725](lowband-v15-b5-725-gain50.json) | 50 | 通过 | 11.50 | 99.84 |
| [712.5](lowband-v15-b5-7125-gain50.json) | 50 | 弱峰跟随，但开关对比不足 | 7.36 | 99.84 |
| [700](lowband-v15-b5-700-gain50.json) | 50 | 首音不足，后续跳过 | — | — |

所有TX子进程均已退出；测量为单点、未经校准的近场无线对照，频率指接收中心。712.5与725 MHz只是TX增益50、当前板卡及天线条件下的检测判据差异，不证明单调、连续覆盖或物理边界。750 MHz提高TX增益后由未通过变为通过，强调参考强度影响；不能据700 MHz结果判断芯片不支持。700 MHz以下仍受软件门限约束；目前不为追求数字边界盲扫或直接改PLL。下一步可量化发射/天线与板级前端影响，并把v15连续软件入口做实机生命周期验证。

**待手动刷写候选 v15：** PAC (`../../outputs/firmware/lowband-v15/Air724U_UIS8910_SDR_BW0_USB_v15.pac`; historical artifact removed during v0.1 consolidation)，SHA256 `5784e9403feb3854e64f922a34acc47fa3b378ce40f560d406efe09819e07208`，generation `0x52610501`。尚未部署。B5软件请求扩展至700–925 MHz，原生channel2400锚点、NV门禁及厂商CP/RF/NV/启动内容保留；该范围不是实际接收保证。采用正常BW0–BW5及连续服务，不加入PRE6/7。匹配的Windows程序位于`outputs/host/lowband-v15/`，原安装主机程序没有覆盖。

已通过[AP ARM](lowband-v15-ap.json)、[CP ARM](lowband-v15-cp.json)、[NV原生选择及门禁](lowband-v15-nv-guard.json)、[USB描述符](lowband-v15-descriptor.json)、[PAC配对](lowband-v15-candidate.json)、[主机选路](lowband-v15-host.json)和规划器与C表118例对照。NV运行快照是历史记录，并非刷后设备实时状态。所有测试是构建或仿真，不证明物理RF、DMA或USB。刷后先核对固件身份和generation、BW1短采及排空，再用BW0在824 MHz做已知点对照，然后按受控点向下探测；B210有限发射、结束后停发。参考实验须指定`--receiver-executable outputs/host/lowband-v15/sdr_receive.exe`和`--rf-status-cp-build work/lowband-cp-v15/build.json`。

等待刷写期间补充当前源码的[Windows会话17例](lowband-v15-host-session.json)、[raw文件队列及同步输出](lowband-v15-host-file.json)和[候选DLL自动选路27例](lowband-v15-auto.json)。包括700 MHz门限、低于门限拒绝、原有频段交叠、INFO和连续采集能力门禁；这些是替身控制/USB的离线测试，不代表已部署或真实传输性能。

配套消费软件也已隔离构建：Soapy候选 (`../../outputs/host/soapy-lowband-v15/build.json`; historical artifact removed during v0.1 consolidation)及SDR++候选 (`../../outputs/host/sdrpp-lowband-v15/build.json`; historical artifact removed during v0.1 consolidation)均绑定v15 Windows库和当前共享频率表，没有安装到便携版。Soapy API不打开设备时通过700/800/823.9999 MHz配置和低于700 MHz拒绝；SDR++通过包含低频边界的共享选路、队列及真实核心FFT机制测试。[离线证据](lowband-v15-consumers-offline.json)。这些入口尚未在v15上验收，不能把软件允许请求当作实测RF覆盖。

2026-10-27 使用 v14（实时 generation `0x52600301`，见 [preflight](lowband-preflight.json)），BW0、接收增益索引40；B210 serial `DEVICE_ID_REDACTED`，子设备 `A:A A:B`、channel 0、TX/RX、发射增益40 dB，有限单音。用户先前报告两天线约30 cm、B210物理 TRX1，现场距离和连接未由软件测量。每次发射结束进程退出，全部测试停止并排空，无刷写或复位。单音对比用 TX 关闭与150 kHz偏移，另测350 kHz及接收中心+100 kHz；不保证绝对电平校准。

| 路径 | 中心 MHz | 结果 | 150 kHz 开/关 dB | 改频跟随 kHz |
| --- | ---: | --- | ---: | ---: |
| B5 | 824 | 通过 | 12.55 | 99.84 |
| B5 | 900 | 通过 | 58.25 | 99.84 |
| B8 | 900 | 未通过：弱峰跟随，但对比不足 | 7.40 | 99.84 |
| B8 | 970 | 通过 | 47.01 | 100.08 |
| B8 | 985 | 通过 | 17.90 | 99.84 |
| B8 | 990 | 未通过：弱峰跟随，但对比不足 | 7.37 | 99.84 |
| B8 | 999.9 | 首音未检出，后续停止 | 未达判据 | 未测 |

每点的原始报告、采集统计、阶段状态和发射日志位于本目录，IQ 文件位于可再生 `work/rf-lowband/`。通过判据详见 `tools/rf_reference.py`；发射频率为中心加单音偏移，表中值是接收中心。弱峰及开关对比由本次测量得到，不是接收灵敏度或校准的传输函数。不同 RF 路由的增益、前端和天线响应可能不同，不能把开关对比差直接当作前端衰减值。

在该参考、板卡和天线条件下，985 MHz通过而990 MHz未通过，提供一次检测判据转折的离散夹界；不能证明两点间单调、连续覆盖或硬截止。B5 的824 MHz已在软件下限，故低端物理转折未到达；固件 `rxcapt_profile.c` 将B5限制824–925 MHz、B8限制880–1000 MHz，这些是软件实验包络。PLL/分频、芯片模拟路径、板级前端、天线和参考电平的贡献尚未分离，芯片物理极限未知。后续以保留原厂NV锚点和门禁为条件，分析并构建能向824 MHz以下请求的最小实验候选；同条件向下分段测试并适时改变参考条件定位衰减来源。不要将未检出直接标成芯片不支持。

后续增益对照：B210 TX增益由40提高到50 dB，B8/990 MHz参考通过，开关对比16.24 dB、改频跟随99.84 kHz；[999.9 MHz](lowband-b8-9999-gain50.json)首音仍未检出，余下采集跳过，发射已结束。[990 MHz详情](lowband-b8-990-gain50.json)。因此上面的985–990 MHz夹界只适用于TX增益40的检测条件，不能作为物理截止。50 dB条件下990通过、999.9未检出，同样只限定本次条件，不证明单调变化或极限。

同样TX增益50下，[995 MHz](lowband-b8-995-gain50.json)两个参考峰与100.08 kHz改频跟随可见，但开关对比7.96 dB不足以通过。运行时working为995.7 MHz，仍在1 GHz算术切换前；因此本次弱响应不必依赖999.3 MHz请求处的算术分支变化来解释。状态观察不等于PLL锁定证明，未确定衰减来源。所有发射已结束。

[离线原生指令对照](lowband-native-sub824.json)对700、729、750、780、800、810、824 MHz对应的working值，在selector4/6及三种合成factor条件下共42例执行原生系数计算并与编译C实现比较，一致；其输入为working频率而不是未经修正的实际请求。低于1 GHz分支将算术输入乘2，实验不能证明PLL物理锁定、校准可用或模拟前端通带。`terminal_profile_channel`对表外B5请求固定使用channel2400作为初始化锚点，频率值独立传递；突破软件下限需要AP、CP和主机共同一致地修改范围并分别验证，不能只修改一端。

[隔离候选ARM测试](lowband-profile-candidate.json)临时生成B5 700–925 MHz软件实验表，实际编译并执行11个通道选择、原始频率门限和锚点用例。700–824 MHz选择原有channel2400/869 MHz锚点，699.9999 MHz拒绝；700 MHz仅为有界实验请求下限，不是接收承诺。该文件在`work/`中生成，活动源码、运行中固件与主机能力没有改变；尚未验证AP/CP配对、运行时NV门禁或打包PAC。
