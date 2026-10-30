# IQ 删除记录 / Capture retention policy

2026-10-30，用户明确要求“包括原始 IQ，只保留最终结论”。`work/` 和 `records/` 中原始 IQ、生成的发射波形和转换载荷已经删除：历史审计共记录 1,675 份文件、34,852,574,208 B，无删除错误。见[删除清单](../maintenance/open-source-preparation-capture-cleanup.json)和[当前政策](retention.json)。固件、SDK、工具链和二进制构建输入不属于 IQ 清理对象。

本目录只保留政策、历史迁移索引与验证结果，不含 `original-work/`、`communication/` 或 `transport-samples/` 载荷。[manifest.json](manifest.json)记录删除之前的来源、路径和长度，**不是现存原始数据清单**。旧索引内的 `records/iq/...` 是历史位置，不应重新创建。

[能力 JSON](../../docs/data/sdr-capabilities.json)、[性能页](../../docs/performance.md)和小型数值报告保存最终结果、条件、损失和未知项。表格与说明图可由摘要重建；旧频谱和解调不能直接重算，必须重新采集。不能把明确删除的载荷解释为偶发丢失、损坏或可替换数据。

`tools/sdr/artifacts.py` 会拒绝将已删除 IQ 解析为其他样本。目录收敛的本地元数据 ZIP 同样不包含这些 IQ，也不改变删除决定。
