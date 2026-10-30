# AP USB 证据入口

当前实现与后续优化统一见[USB raw链路](../../plans/usb-raw-stream.md)，实测能力见[状态](../../status.md)。此页仅保留专题入口，避免另维护一套版本状态。

厂商UDC ABI及地址由本机SDK ELF与PAC字节核对，不能仅用符号名推定兼容。采集DMA写DDR后交UDC DMA，保留cache和所有权；Windows经WinUSB异步读取，IQ无应用层头/CRC/ACK。固定缓冲吞吐与真实采集供给分别报告。
