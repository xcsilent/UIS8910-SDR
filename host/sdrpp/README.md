# SDR++ 原生插件

当前交付 `outputs/host/sdrpp`，直接调用Windows DLL，无需Soapy。目标为`D:\Tools\sdrpp_windows_x64`便携版；核心SHA256 `5cc72ceb770e64646855ade781a59642d2e9be68dc6325a094c74a5fd4df6328`，源码commit `f10fb98af8b80de01de94e60c17608e4281e2515`，不保证任意版本C++ ABI兼容。

当前交付保留快速调参恢复，B3 Auto请求包络扩至1375–1920 MHz；核心协议已有 BW0–BW5、Auto往返、快速改频和停止排空回归。便携版插件及配对运行库已与当前发布目录同步，并补BW0/RX30真实核心接收、Auto和停止排空，见[安装及回归](../../records/host/sdrpp-portable-release-delivery-20261030.json)。

## 使用

当前安装对应的隔离测试副本为`work/sdrpp/portable-release-check`，配对构建`outputs/host/sdrpp/build.json`；验证器检查DLL与核心身份。服务模式不包含桌面或外部RF参考。

关闭目标SDR++后，安装计划和执行分别为：

```powershell
python -B tools/install_sdrpp.py --sdrpp-root D:\Tools\sdrpp_windows_x64
python -B tools/install_sdrpp.py --sdrpp-root D:\Tools\sdrpp_windows_x64 --apply
```

插件进入modules，配套sdr_usb.dll在根目录；安装器备份配置/旧文件。启动sdrpp.exe，Source选UIS8910，Control COM填现场端口，BW0，从gain索引30开始，设置中心频率后播放。插件不显示信道选择框，内部按中心频率自动选路。其他消费者必须退出。

BW0–BW5均可选，换采样档位先停止。频率与增益可在采集中调整：回调仅发布请求，后台排空并等待最新请求稳定120ms再配置重采。连续拖动合并到最后值；越界后排空等待，回到有效频率再采。停止仍要等待本机会话清理，不承诺无缝切频。

Wideband FFT pacing默认开启，减少有损宽档的FFT输入跳样，保持采样率与频率轴；停采/换源恢复用户设置。真实核心固定输入曾从1帧变31帧并恢复，这是核心测试，不是桌面实际帧率。较大FFT跨丢块仍可能产生伪影。

## 数据与状态

输出CF32=(lane0-j*lane1)/2048，USB仍为LE16+16高12位。预分配4MiB队列、回调一次拷贝，独立消费者转换；满队列丢整复数样点。

uis8910_source_config.json保存请求参数；uis8910_source_status.json约每秒更新统计。frequency/band是请求值；applied频率/路径/gain/BW/revision只在相应会话交付IQ后更新，停止后保留，不能当PLL锁定证明。排空丢弃、改频清队列、未消费尾部分列。增益索引非dB，无绝对时间戳。

Auto采用共享B5/B8滞回与B3/B40重叠保护；范围和1890MHz阈值是软件策略，不是连续覆盖或物理界限。缺NV明确拒绝，不猜写校准。仅支持一台设备。

## 构建

现有work/sdrpp保留固定源码、MSVC和Windows SDK，无需重复下载。`python -B tools/build_sdrpp.py --output-dir outputs/host/sdrpp-candidate --build-dir work/sdrpp-candidate --runtime --runtime-dir work/sdrpp-candidate-runtime`生成独立候选和测试副本。编译器与目标DLL不可当普通缓存删除。

verify_sdrpp使用真实核心服务模式做数据流/生命周期验证，会访问设备；不将其等同桌面验收。数值、队列和FFT核心测试在构建时执行。遵循SDR++上游许可；COPYING随对应构建保留。
