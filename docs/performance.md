# Measured performance / SDR 性能测试结果

Snapshot2026-10-30. [中文技术报告](technical-report.md) · [English report](technical-report.en.md) · [Machine-readable final tables](data/sdr-capabilities.json).

These are historical measurements, not newly repeated tests. MB/s is decimal; rates are nominal complex samples/s. Native signed12 is stored as two LE int16 lanes (4 B/complex). Physical I/Q naming, ENOB and absolute power calibration are unknown. At the owner's request, raw IQ and generated waveforms were removed; final numerical records remain. Recomputing spectra requires new captures.

## Frequency evidence

Engineering envelopes: approximately687.5–1000 MHz and1375–2786 MHz. They are **not continuous verified coverage**.1000 MHz is a software envelope; lowband970/985 MHz passed,990 MHz was condition-dependent,995/999.9 MHz did not qualify. Exact silicon limits and the1.0–1.375 GHz gap remain unresolved.

| Measurement | Final result | Evidence |
| --- | --- | --- |
| Low boundary |687.5 MHz reference success;681.25 MHz first tone not identified | [687.5](../records/rf/lowband-b5-6875-v21-reference.json) |
| B3 extension |1375/1400/1447/1500/1600 MHz passed;1350/1300 MHz failed under recorded conditions | [Final lower summary](../records/rf/coverage-v32-b3-lower-summary.json) |
|2000–2390 MHz /10 MHz grid |40/40 complete off/on/tone/retune references | [Final summary](../records/rf/coverage-b40-grid-2000-2390-summary.json) |
|2400–2800 MHz /5 MHz grid |72/81 complete;2435/2440 user-accepted environment affected; partial cases retained | [Final summary](../records/rf/coverage-b40-grid-2400-2800-summary.json) |
| Upper refinement |2786 MHz complete;2787–2789 degraded;2800 weak/incorrect frequency tracking | same upper summary |

![Categorical measured grid](assets/rf-grid.svg)

Grid intervals are not interpolated. A failed/incomplete reference is not a proven unsupported frequency. Tests used uncalibrated Wi-Fi antennas; board filtering, PLL/dividers, interference and reference conditions are not isolated. C++ adapters and Windows C currently differ in their B40 Auto request cap; [review](maintainer-review.md) records this separately from RF results.

## Bandwidth and throughput

| BW | Msps | Full raw budget MB/s | Relative −3 dB total width MHz | Historical USB/device rate MB/s | Test duration |
| --- | ---: | ---: | --- | ---: | ---: |
|0 |1.92 |7.68 |1.05–1.10 |7.680 |10 s |
|1 |3.84 |15.36 |2.75–2.80 |15.360 |10 s |
|2 |7.68 |30.72 |4.55–4.65 |30.35 |10 s |
|3 |15.36 |61.44 |9.2–9.4 |31.55 |3 s |
|4 |30.72 |122.88 |13.6–13.8 |31.60 |3 s |
|5 |30.72 |122.88 |17.5–18.5 |31.94 |3 s |

![Measured bandwidth and raw budget](assets/bandwidth-usb.svg)

**Response method:** fixed RF tone, vary RX center, normalize relative tone power and check repeated-reference drift. Widths bracket sparse−3 dB crossings; they are end-to-end, uncalibrated and include tuning/analog/digital effects. BW0–4: B5,881.65 MHz RF tone, RX40, TX20 forBW0/1 andTX40 forBW2–4. BW5: B40,2000.15 MHz, RX40/TX40. Different firmware generations apply. They are neither uniform v32 specifications nor calibrated manufacturer filter bandwidths.

Response evidence: [BW0/1](../records/rf/bw01-summary.json), [BW2](../records/rf/mainline-bw2-passband-refined.json), [BW3/4](../records/rf/wideband-passband-fft-summary.json), [BW5](../records/usb/geometry-v20-bw5-passband-summary.json).

**USB method:** v29, B8/880 MHz, six8192 B output slots,32×64 KiB host reads; steady device-completed rates. [BW0](../records/usb/b8-880-bw0-10s-v29-20261029.json), [BW1](../records/usb/b8-880-bw1-10s-v29-20261029.json), [BW2](../records/usb/b8-880-bw2-10s-v29-20261029.json), [BW3](../records/usb/b8-880-bw3-3s-v29-20261029.json), [BW4](../records/usb/b8-880-bw4-3s-v29-20261029.json), [BW5](../records/usb/b8-880-bw5-3s-v29-20261029.json). The machine-readable table retains exact device/host bytes, differences and drain results.

BW0/BW1 fit the raw budget but are not certified gap-free. BW2 has inadequate sustained margin. BW3–5 are partial output: average USB bytes cannot be treated as a new continuous sample rate, and FFTs crossing gaps can have artifacts. BW6/7 produced no added passband evidence. USB's physical ceiling has not been measured.

One v32 paired Windows CLI B3/1375 MHz60 s run recorded7.680 MB/s device supply and7.658 MB/s host reception, drained successfully, with missing positions unknown: [record](../records/rf/coverage-current-windows-cli-b3-1375-60s.json). It is a data-path check, not a new RF reference/passband measurement.

## Real-time over-air demonstration

Condition: finite10 s source; B210 physicalTRX1=`A:A A:B/channel0/TX-RX`; approximately50 cm; existing2.4/5 GHz Wi-Fi antennas; RX index30; TX gain setting65, not65 dBm. Digital amplitudes differ. [Final acceptance](../records/communication/functional-acceptance.json).

| MHz | BW | Waveform | Frames | BER | EVM | Host pipe drop | Source-file frame yield |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
|2700 |0 |QPSK |2022 |0 |4.6846% |0 B |99.7533% |
|1900 |0 |OFDM |4157 |0 |3.1530% |0 B |99.7840% |
|1900 |1 |OFDM |8320 |1.5593e−5 |3.0440% |0 B |99.8440% |
|1900 |1 |QPSK |2866 |0 |10.3425% |59,179,008 B |70.6956% |

The last row is a **lossy wireless demonstration**, not clean real-time BW1 acceptance. BER is calculated on decoded data, not on lost frames. Source-file yield is not physical transmitted-frame count. Device-minus-host differences24,576/57,344/49,152/49,152 B remain separate from host queue drops. No measured exact RF sample loss is available.

| Row order above | Demodulator CPU s | Native receiver CPU s | Receiver wall s |
| --- | ---: | ---: | ---: |
|QPSK BW0 |4.297 |0.094 |14.887 |
|OFDM BW0 |7.109 |0.109 |14.799 |
|OFDM BW1 |6.547 |0.125 |14.955 |
|QPSK BW1 |14.438 |0.516 |15.057 |

CPU seconds are process accounting; startup/tail extends receiver wall time beyond the10 s waveform. Sampled native12 peaks26/110/109/68 had no near-rail events in sampled blocks; analog compression remains possible. Historic failed1000/2600/2786 MHz communications remain failed/unknown. Ten seconds met the owner's functional demonstration scope; no60 s sweep was added.

## Unmeasured specifications

No values are assigned to ENOB, noise figure, sensitivity in dBm, SFDR, IIP3, image rejection, absolute gain, phase noise, clock ppm, RF lock time, exact lost samples, chip tuning limits or absolute sample timestamps. Independent calibrated tests are needed before a receiver data sheet can claim them.

Regenerate tables/plots from final records with `python -B tools/generate_report_assets.py --figures`. This does not reanalyze IQ or reproduce hardware measurements.

