# 开发过程与复现指南

完整构建依赖和候选命令见[Building](building.md)。本页保留研发路线，不是当前待执行硬件计划。原始IQ/发送波形已按用户要求删除，历史频谱不能直接重算；最终结论保留在[性能页](performance.md)和小型JSON记录中。

## 研发路线

1. 从调试监控和 RAM 接管建立可读写、可恢复的实验入口。
2. 通过 SDK 二进制反汇编、DWARF、ZW217 同代源码和 RDA 前代精选资料还原 RF 请求、PLL 算术、NV/RFFE 和 RXON 局部路径。
3. 将采集点从蜂窝解调链前移到 RXCAPT，建立 CP 环缓冲、UDC DMA 和 USB Bulk IN raw 数据面。
4. 建立 Windows CLI/DLL、SoapySDR 和 SDR++ 入口，共享频率 Auto 表和 IQ 格式。
5. 用 B210 有限双音和通信波形验证频率跟随、QPSK/OFDM 实时解调、停止排空和过饱和控制。
6. 收敛为当前 v32 基线、证据等级和明确未决项。

## 本地校验

```powershell
python -B tools/sdr.py verify
python -B tools/check_publication.py
python -B tools/generate_report_assets.py --check
```

硬件命令需要现场核对 COM 端口、UIS8910 身份和 B210 序列号；历史记录不替代实时查询。有限发射实验结束后应等待自然退出并停止设备，不用强杀作为正常流程。

便携检查不依赖SDK，不构建或访问设备。完整verify依赖保留工作站，检查身份/结构与证据新鲜度；原生RF或Soapy/SDR++测试只在对应代码改变时按作用域执行，不能把本轮文档检查冒充运行时回归。

## 证据记录原则

- 每个实测记录保存频点、BW、RX/TX 增益、天线和参考条件、源文件、设备完成量、主机接收量和错误。
- 反汇编记录保存原始 binary/scatter/binding、地址、访问宽度、成功/失败输入和 C 对照版本。
- 未验证参数写 `unknown` 或 `not measured`，不用历史默认值补齐。
- 仅有软件包络、静态 VCO 码或“有响应”时，不写成硬件锁定、连续覆盖或芯片极限。

