# Contributing / 贡献指南

Read [project rules](AGENTS.md), [documentation](docs/README.md), [build boundaries](docs/building.md) and [license scope](LICENSE-STATUS.md) first. Original code and documentation use GPL-3.0-or-later. Contributions use the same terms; preserve applicable third-party licenses and provenance. There is no separate CLA.

## A useful contribution

- Describe the concrete failure or missing capability, changed source and ABI impact.
- Run `python -B tools/check_publication.py` for portable documentation/metadata checks. On the retained workstation also run `python -B tools/sdr.py verify`; report missing external inputs rather than inventing a pass.
- For code changes run focused tests covering the changed behavior. Label mock/native/emulated/hardware results separately. A historical report from different source inputs is not a current test result.
- Link stable conclusions to final records. Report unknowns, failed cases and limitations alongside successes. Don't duplicate per-turn plans or restore frozen experiment runners.
- Record provenance for copied/derived source. Do not include vendor trees, PACs, calibration or executable releases merely because they exist locally.

## RF and streaming evidence

Record module/firmware generation, host artifact identity, frequencyHz, nominalFs/BW, RX gain **index**, TX gain setting and digital amplitude, route/Auto behavior, antenna/fixture and distance, reference on/off and retune tracking. Distinguish complete reference, conditional reception, data-path-only and software-only conclusions.

For streaming report device completion, host reception, file/consumer delivery, queue drops, drain, errors and CPU/wall time separately. Missing sample positions may be unknown. IQ remains raw: no application header/CRC/hash/ACK/retry. Waveform frame checking belongs to the RF experiment, not the USB payload format.

Do not assume ADC precision from storage width, RF lock from calibration-ready, continuous RF coverage from a sparse grid, or analog linearity from no digital clipping. Avoid writing unknown USID, PA or board calibration values.

## Keeping the repository maintainable

Use existing `docs/`, `records/` and manifests. New firmware candidates need independent directories; never mark them deployed without actual confirmation. Never upload, flash, delete protected builds or perform physical-device work as an incidental documentation check.

Raw captures were intentionally removed on2026-10-30 to keep final conclusions. Future measurements can retain a small justified fixture only with a documented retention decision; do not restore all old large waveforms. Report generators must work from final metadata and disclose that they do not replay old IQ.

中文：提交时说明具体问题、改动范围、验证类型和证据条件；不要把历史成功、软件推断或网格点当作完整硬件规格。源码、当前发布身份与文档保持一致，硬件实验和刷写按项目规则执行。

