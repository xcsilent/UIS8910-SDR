# Windows 接收库与 CLI

当前交付目录 `outputs/host/windows`，配对 `sdr_usb.dll` 和 `sdr_receive.exe`。默认Auto按频率选择B5/B8/B3/B40；13条软件配置由共享表生成，INFO及运行时NV仍决定请求能否启动。可请求范围不证明物理接收范围。

当前正式接收器已包含`--stdout-raw`：stdout为二进制纯IQ，最终JSON只写stderr，不能同时指定`--output`或`--list`。`comm_realtime.py`默认跟随host manifest并以RX30启动，显式receiver用于候选回归。有限采集自行排空后仍执行STOP释放保留会话，避免下一次启动BUSY。构建、模拟/实机范围及回退见[发布记录](../../records/communication/host-release.json)。其他SDR组件保留各自manifest身份。

```powershell
python -B tools/sdr.py receive --port COM9 --frequency-hz 881500000 --gain-index 40 --bandwidth-index 0 --milliseconds 10000 --iq-output work/capture-new.raw --output work/capture-new.json
.\outputs\host\windows\sdr_receive.exe --help
```

端口现场核对。Python入口的output为独立JSON，iq-output为纯raw；原生CLI的output为raw，stdout为JSON。省略raw输出只接收到内存，输出路径必须新建。单设备独占，不能与SDR++或其他消费者争用。

## API 与生命周期

`sdr_session.h`提供带宽、观察统计和完整会话API；`sdr_control.h`为独立COM控制；`sdr_usb.h`为WinUSB读取。先INFO核对协议/路径/BW能力，再配置读回、提交异步读池、START。调用期间由会话独占控制和USB句柄；数据回调不能等待串口控制。

BW0–BW5；有限会话100–60000ms，0为持续直到STOP。控制约200ms续期，失联保护约5秒。正常停止保持读池活动直至排空，再改参重采，不复位芯片。START超时可能已生效，必须查询状态并安全停止。close控制句柄本身不发送STOP。

COM控制协议保留既有校验与重试，仅用于控制；IQ纯raw，LE16+16高12位signed值、算术右移4。主机正频偏约定 `(lane0-j*lane1)/2048`，物理I/Q命名与ENOB未知。

USB绑定指定GUID `{5D6BCE91-4F8A-4D42-9A0D-A9E6F8AC8910}`，核对HS、vendor接口、Bulk IN及512B最大包。默认32个64KiB请求，按提交顺序交付，不能用完成事件顺序充当样点顺序。8192B请求可用于当前几何的短采尾部对照，但CPU较高，不作为全局默认。

## 写盘、所有权与统计

回调缓冲仅在返回前有效。CLI用预分配有界队列拷贝一次，写线程写raw；默认32槽，可用file-queue-blocks配置。队列满丢新块并计数，写盘错误停止；sync-file用于同步对照。主机这里不是零拷贝。

分别报告设备完成、主机收到、写盘/消费者、排空丢弃、队列丢弃、控制/清理错误及观测间隙。进程CPU与写线程CPU有重叠，不相加。字节一致不证明采集无间隙；无法精确计算的总丢样数保持未知。宽档允许部分传输，名义Fs不能由平均USB字节率代替。95%供给评估只是完整输出统计，不是宽档可用性的接入门槛。

停止事件或Ctrl+C走STOP/排空；OS驱动取消及磁盘阻塞没有硬性返回上界。写完不等于断电持久化。固定源诊断只在CP未接管时可用；CP已持有时明确拒绝，不强制释放或复位来跑测速。

## 构建与验证

下载源码后按[WSL依赖与构建](../../docs/building-wsl.md)安装 Ubuntu 包，再执行
`python3 -B tools/build_host_components.py --toolchain-root /usr`，接收库/CLI 位于
`outputs/host/build-v0.1/windows`，与其他新编译组件自动配对。只需接收器时加
`--without-soapy`；已有本地工具链仍可复用，不要直接覆盖当前交付。
单组件入口 `build_host.py` 支持 `--toolchain-root` 和独立输出目录；当前发布的手动频率请求策略用
`--unrestricted-frequency`。针对性入口为verify_host_receive、verify_host_control、verify_host_session、verify_host_file_sink和verify_daily_receive。
使用说明见[Windows交接](../../docs/windows-handoff.md)。

调谐计时 `python -B tools/sdr.py tune-benchmark --port COM9 --bandwidth-index 5 --request-bytes 8192 --output work/tune-new.json`，默认使用outputs/host/tune。它测主机交付间隙，不测RF锁定；执行前核对设备独占。
