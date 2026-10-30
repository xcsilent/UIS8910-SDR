# 工具入口

开源整理：`check_publication.py`为纯离线、标准库文档/表格/源码语法检查；`generate_report_assets.py --figures`从最终JSON生成能力表/CSV/性能图；`repository_audit.py`提供目录元数据、文档链接及本地allowlist源码评审导出。不访问设备、不上传。原始IQ已删除，`verify_recorded_artifacts.py`只检查删除策略和历史解析，不再重算频谱。详见[构建与复现边界](../docs/building.md)。

日常使用 `python -B tools/sdr.py --help`：status/verify/plan/rf-catalog离线；receive和明确的诊断/参考命令才访问硬件。Goal暂停期间不自动运行硬件命令。

当前固件构建：`python -B tools/build_firmware.py`，固定依赖在`build-support`，无需旧work/seed/历史测试报告。build_capture为旧B5研究入口；build_capture_bridge/build_receiver/observer为分组件研究工具。
WSL主机统一入口 `python3 -B tools/build_host_components.py --toolchain-root /usr`，
构建配对的Windows DLL/CLI、计时器、Soapy SDK/模块及离线队列测试；依赖和离线缓存见
[WSL构建指南](../docs/building-wsl.md)。`prepare_host_toolchain.py`复用本地或系统MinGW，
缺失时下载/解包发行版匹配的包；`prepare_soapy_sdk.py`校验/解包随项目固定的源码。
build_host/build_soapy/build_sdrpp/build_tune_benchmark保留为分组件入口，见[构建指南](../docs/building.md)。

verify目录保留按功能组织的原生ARM/RF差分、队列/所有权、主机生命周期测试，不把历史版本报告全部重跑设为门禁。旧快照与源码身份分别记录。

实时通信使用`comm_waveform.py`生成有限发射文件，`comm_realtime.py`连接UHD和Windows接收器并在线解调。按用户要求默认10秒、RX索引30，以证明无线能力收尾；不继续要求60秒。当前仅支持BW0/BW1，分别自动选择1.92/3.84 Msps；显式`--tx-rate`必须匹配，波形metadata及文件长度须一致。BW1保持样点几何，QPSK符号率升为480 ksym/s、RRC占用约600 kHz，OFDM子载波间隔升为15 kHz、96子载波占用约1.44 MHz；这不是整个BW1通带测量。配置和统计独立于纯raw IQ。

示例先生成`python -B tools/comm_waveform.py --modulation ofdm --sample-rate 3840000 --seconds 10 --output work/comm-ofdm-bw1-v1-10s.fc32`；接收运行`python -B tools/comm_realtime.py --port COM9 --frequency-hz 1900000000 --gain-index 30 --bandwidth-index 1 --duration-s 10 --modulation ofdm --tx-file work/comm-ofdm-bw1-v1-10s.fc32 --serial DEVICE_ID_REDACTED --tx-gain 65 --output work/communication-test.json`。省略receiver时从host manifest选择正式Windows产物，显式`--receiver`仍可用于独立候选；端口/身份必须按实时连接核对。[发布证据](../records/communication/host-release.json)包含重新构建与RX30长测。正常使用有限TX自然退出，不用repeat强制结束代替释放。输出分别报告生命周期、主机队列、载荷质量、有效序号跨度和有限源文件获取率；精确RF源丢样不计作已验证。

QPSK接收采用前导拟合的分数定时插值，不用载荷真值拟合增益或定时。`verify_comm_protocol.py`验证全部采样相位、双向20ppm漂移、缺口重同步、噪声和载荷反相负对照；`verify_comm_ofdm.py`验证BW0/BW1频偏、多径和载荷独立指标；`verify_comm_realtime.py`验证读管线及停止，不替代实机通信。

OFDM接收使用主机33tap Hamming选带、8192样点连续去DC和单精度训练/导频运算，保持0.7周期门限、0.48模板及独立帧头/载荷验证。状态跨任意输入分块延续，缺口reset同时清空滤波状态；FIR16样点延迟计入样点位置，重置后有有限过渡。滤波仅作用于解调副本，USB/raw文件及native12电平统计不变。当前10秒OFDM BW0/BW1和QPSK BW0无主机队列丢弃；QPSK BW1证明无线载荷但丢弃59.2 MB、源帧获取率70.7%，不作为无损组合。见[10秒交付](../records/communication/functional-acceptance.json)与[定位及回归](../records/communication/ofdm-conditioning.json)。旧长测失败保留为限制，不继续设为门槛；新报告附源码/接收器身份，不对IQ内容hash。

用户最新测试范围只推进USB能持续承载的BW0/BW1；BW2暂不安排，BW3–BW5不做新增通信/吞吐测试。波形生成器可用`--amplitude-scale`调整离线源电压幅度，默认1；QPSK幅度4/6峰值约0.620/0.930，分别比默认增加12.04/15.56dB，不等于校准发射功率。源峰值超过数字满量程时拒绝生成有效metadata。只在已有低电平证据的点使用放大源，硬件增益与接收削顶另行记录。

`source_file_accounting`使用有限唯一序号源的完整帧作分母，有界位图分别计独立获取帧和无误码帧，包含首尾、内部及主机缺口，不把未知首尾从分母剔除。它与`frame_tracking`的有效序号跨度不同，既不是实际RF发射帧计数，也不定位样点损失。旧源缺少明确唯一序号metadata时保持未知，repeat模式不启用该统计。

RF镜像核对：`python -B tools/verify/verify_rf_pac_payload.py` 从current PAC提取/解码并验证AP消费者；`verify_rffe_init_native.py --current-pac` 和 `verify_rf_frequency_native.py --current-pac` 明确使用该镜像，默认仍为SDK参考。`build_rf_observer.py --output-dir <新目录>` 生成未部署的RF命令入口观察镜像，随后用 `verify_rffe_init_native.py --observer-build <目录>/build.json` 验证；它不生成PAC、不修改硬件，不能直接刷入。

`package_rf_observer.py` 将已验证AP/CP候选与RF观察镜像组合，使用既有modem页分配、逐文件校验及最终解压回读；`verify_rf_observer_candidate.py` 检查最终相对部署基线的变化、布局证据和错误容器拒绝。这些是历史研究构建；当前发布统一为v0.1，历史PAC已移除。当前构建入口`tools/build_firmware.py`保留平台PAC中的RF观察镜像，无需重建历史v28/v29链。`sdr.py fem-override --port COMx --value default|2|5 --output <新JSON>`要求固件声明operation53/ABI1，设置须在首次默认采集成功停止排空后；省略value仅查询。只选择下次采集模板，不是外部芯片读回；实验结束恢复default。`verify_fem_control.py`离线覆盖不支持固件拒绝、BUSY及读回不一致。

`rf_reference.py --fem-compare 2|5`复用既有B210有限参考流程，限单一路径B5/B8、BW0及显式匹配的`--rf-status-cp-build`（experimental_fem_override、trace ABI5）。初始mode须default；默认TX-off短采及trace匹配后才允许切换，在同次有限TX内交替默认/指定值，分别检查开关对照、双音和改频跟随。每次采集必须有停止排空证据；结束恢复default并读回，异常未排空时拒绝继续写选路并报告恢复未完成。记录模式选择不等于外部器件读回；相对功率仅为同条件顺序对照，不是校准灵敏度。`verify_rf_reference.py`覆盖七种模拟流程及signed12/有间隙FFT分析；无硬件接收证明。

有限TX进入streaming后，采集、trace或选路控制失败均先等待当前有限burst自然退出，观察每次至多1秒，总等待不超过剩余burst加5秒；此前未进入streaming或超时才执行terminate/kill。记录forced_shutdown及退出确认；退出无法确认即报失败、禁止第二次TX。此行为有模拟流程验证，不保证失联硬件一定已关闭RF。

rf_reference/rf_response/rf_stability为有限参考与响应分析；不是常驻发射服务。实验前核对硬件身份和占用，实验后停止发射。raw数据不加应用头或CRC。

`rf_reference.py --sweep-end-hz <终点Hz> --sweep-step-hz <步进Hz>`复用完整参考实验生成有界网格，起点沿用`--frequency-hz`，每点独立报告/raw及有限TX。未识别参考可继续；控制/传输错误、排空或TX退出未确认立即停止整批。`--rf-snapshot-policy first`在每点首次采集后核对generation和停止状态，省略后续重复RF快照；参考判据及每次采集排空检查仍保留，FEM/双路比较必须使用默认`all`。v32须显式`--dma-block-bytes 8192`；步进和未测空隙必须报告，不能把网格当所有频率连续通过的证明。

`python -B tools/sdr.py rf-execution --trace <ABI5报告.json> --output <新报告.json>` 离线解释helper计数和最后参数指针；不访问设备，不证明ACK或器件型号。
## 接收电平

通信工具 `comm_realtime.py`、双音参考 `rf_reference.py` 和通带测试 `rf_response.py` 默认接收增益索引30。双音/通带报告记录源数字幅度0.3，`spectrum.iq_amplitude`为选定原始窗口、去直流前的native12峰值/RMS/近轨比例，不代表整段采集均未削顶。所有收发实验先降低接收电平并记录峰值、RMS、近轨比例和解调质量；不能用无数字削顶排除模拟压缩，也不能因无同步自动增大发射/接收增益。历史RX40/60仅为对应实验条件。
