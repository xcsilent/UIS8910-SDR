# Stop 异常看门狗支线

## 现有保护

当前固件已经有两层内部停止保护：

- `firmware/capture/rf_terminal_rx.c` 在连续采集循环中检查 DMA 错误、停止请求、DMA idle、frame time 和活动 cursor；无活动超过约 5000 个原生时间单位时请求 `STREAM_REASON_TIMEOUT`，并进入 RF/DMA 停止和排空路径。
- `firmware/sdr_receiver/raw_usb_function.c` 在 USB 关闭、采集停止或终端错误时取消 UDC 请求；排空超时保留 buffer ownership，不在未知状态下强行复用 DMA 槽。
- Windows `host/windows/sdr_session.c` 已有控制线程、lease keepalive、STOP、状态轮询和有限排空等待。主机 STOP 超时会保留错误并禁止把会话当作可复用成功。

这些保护可以自动停止 RF/DMA，避免异常时继续发射或复用未确认的 buffer。它们不等于物理芯片复位。

## 当前已观察到的异常

当主机或串口会话异常中断后，服务可能返回 `0x20000005`，其低位 `5` 是设备 BUSY。独立发送 operation46 STOP 可以返回成功，但后续状态仍可能保持 BUSY；此时重复启动接收器或 B210 会增加句柄和设备占用问题。该状态需要关闭所有消费者后重新拔插或断电重启 UIS8910，不能由普通主机 API 安全地强制清除。

## 支线实现决策

首版 watchdog 采用“停止/排空/状态确认”的非复位策略：

1. 主机控制线程发现 START、状态轮询、keepalive 或 STOP 超时时，只发送一次 STOP；
2. 在有限窗口内继续读取状态和 recovery，确认 RF/DMA idle、epoch 对齐和无错误；
3. 确认成功才释放会话并允许下一次配置；
4. STOP 返回成功但设备仍 BUSY 时，报告 `watchdog_escalation_required`，禁止自动重试；
5. 只有明确的外部复位接口或用户物理重启动作才执行芯片复位；当前未实现 USB 远程硬复位。

不在采集热路径加入逐样点 watchdog，不在 DMA 所有权未知时清空槽，不把 `pending=6` 单独当成卡死证据。设备 watchdog 的超时阈值必须基于当前 native frame time 和 stop/drain 证据校准，不能用主机 wall clock 直接解释成芯片时间。

## 验收

支线完成需要分别验证：正常停止、主机取消、USB 读失败、CP 超时、DMA 错误、STOP 超时、BUSY 后恢复。每种情况必须记录 watchdog 原因、STOP 结果、设备排空、recovery 状态和是否需要物理重启。BUSY 持续时保持 Goal 未完成，不能标记为自动恢复成功。
