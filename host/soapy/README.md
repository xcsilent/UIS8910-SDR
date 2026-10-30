# Windows SoapySDR

当前组件 `outputs/host/soapy`，固定SoapySDR 0.8.1源码commit `1cf5a539a21414ff509ff7d0eedfc5fa8edb90c6`，复用Windows接收库和共享Auto。单RX0，支持CF32/CS16；当前 BW5、Auto改频、重复启停和停止排空见[实机证据](../../records/host/soapy-current-hardware-auto-b3-bw5.json)。

当前B3 Auto请求包络为1375–1920 MHz，来自共用C表；[BW0 CF32/CS16在1375→1447 MHz改频及重复采集](../../records/host/soapy-b3-coverage-auto.json)通过。该包络不是已证明的连续接收范围；离散RF参考见`tools/sdr.py rf-catalog`输出。

```powershell
$env:PATH="$PWD\outputs\host\soapy;$env:PATH"
$env:SOAPY_SDR_PLUGIN_PATH="$PWD\outputs\host\soapy"
.\outputs\host\soapy\SoapySDRUtil.exe '--find=driver=uis8910,port=COM9'
.\outputs\host\soapy\SoapySDRUtil.exe '--probe=driver=uis8910,port=COM9'
```

端口是示例。设备参数`driver=uis8910,port=COM9`；Soapy用户接口只暴露`antenna=Auto`，应用只需调用`setFrequency`，内部按中心频率自动选路。手动B1/B3/B5/B40等信道不再暴露；Windows CLI的`--band`仅用于诊断。增益用`writeSetting("gain_index","40")`，0–124为未校准索引。

名义采样率1.92/3.84/7.68/15.36/30.72Msps。BW4/BW5同速率，BW5需显式设置：

```cpp
device->setSampleRate(SOAPY_SDR_RX, 0, 30720000);
device->writeSetting("bw_mode", "5");
```

重复相同采样率保留BW5；从其他模式直接选30.72Msps默认BW4。无独立滤波宽度：getBandwidth返回0，范围为空，setBandwidth只接受0保持模式，非零明确拒绝。

setupStream→activateStream→readStream→deactivateStream；活动改频或改参同步stop/drain/config/start并清队列，单stream方法由调用者串行安排。没有绝对样点时间戳，允许丢块及间隙，采样率与有效通带见[能力表](../../docs/status.md)。

CF32为(lane0-j*lane1)/2048，CS16为完整12位数值对应的16位输出；负极值/取反边界和任意字节分片由队列测试覆盖。USB本体仍是原始4B/复数。

下载源码后按[WSL依赖与构建](../../docs/building-wsl.md)安装 Ubuntu 包，运行
`python3 -B tools/build_host_components.py --toolchain-root /usr`。此入口从随项目提供的
Soapy0.8.1 源码编译 SDK、接收 DLL、模块及离线队列测试，不需要历史实验记录。
完整配对运行库在 `outputs/host/build-v0.1/soapy`，测试程序在
`work/wsl-host-v0.1/soapy-module/queue-test.exe`。原 work/soapysdr SDK 保留。
Windows 离线验证需向 `verify_soapy.py` 显式传入上述 `--area`、`--queue-test`，详见构建指南；
未加 `--hardware` 不打开设备。第三方应用的插件ABI和搜索路径需匹配此构建。
