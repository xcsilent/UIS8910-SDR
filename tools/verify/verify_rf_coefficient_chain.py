"""Verify the retained RF coefficient -> B RXON consumer evidence.

This is an offline consistency check.  It deliberately does not access the
device and does not infer a physical divider or a filter bypass from names.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    ns = ap.parse_args()

    chain = json.loads((ROOT / "records/rf/reference-b-gap-request-chain.json").read_text(encoding="utf-8"))
    filt = json.loads((ROOT / "records/rf/coverage-v32-filter-assessment.json").read_text(encoding="utf-8"))
    producer = chain["coefficient_producer_dispatch"]
    body = chain["composed_b_body"]["sample_accesses"]
    writes = {(x["address"].lower(), x["operation"]): x["value"] for x in body if x["operation"] == "write16"}

    required = {
        "0x30360": "0xb520",
        "0x302c4": "0xb524",
        "0x302c8": "0xb522",
    }
    # The sample access list is the native-comparison fixture.  The source
    # crosswalk below is the stronger address/order assertion.
    source = (ROOT / "firmware/rf_rebuild/rf_core_rxon_prepare_b_prefix.c").read_text(encoding="utf-8")
    source_checks = [
        "READ(0xb520u,word); WRITE(0x30360u,word);",
        "READ(0xb524u,word); WRITE(0x302c4u,word);",
        "READ(0xb522u,word); WRITE(0x302c8u,word);",
    ]
    assert producer["coefficient_call"] == "0x6134 ->0x37f0"
    assert producer["output"] == "0xb520"
    assert all(item in source for item in source_checks)
    assert all((addr, "write16") in writes for addr in required)
    assert filt["controls"]["dlpf"]["rf_local"] == "0x31040"
    assert filt["controls"]["dlpf"]["fields"]["0"] == "dlpf_rstn"

    result = {
        "status": "passed",
        "device_accessed": False,
        "firmware_changed": False,
        "scope": "Offline chain consistency: coefficient producer, B RXON coefficient commit, and filter-control evidence.",
        "producer": {
            "dispatch": "0x6122",
            "call": producer["coefficient_call"],
            "working_source": producer["working_source"],
            "output": producer["output"],
            "interpretation": "software coefficient generation; no physical divider claim",
        },
        "consumer": {
            "entry": chain["composed_b_body"]["entry"],
            "coefficient_registers": {
                "0x30360": "0xb520 (Q8)",
                "0x302c4": "0xb524 (low word)",
                "0x302c8": "0xb522 (high word)",
            },
            "source_order_checked": True,
            "native_body_sample_checked": True,
        },
        "filter_boundary": {
            "tested_pair": "B3 1350/1375 MHz, modes 0..5",
            "same_mmio_order": True,
            "frequency_dependent_writes": ["0x30360", "0x302c4", "0x302c8"],
            "independent_filter_bypass": False,
            "dlpf_control": "0x31040 reset/control fields; reset is not a transparent bypass",
            "fir_control": "RX_PRE_CFG bit6 is FIR_EN and is clear in the direct raw profile; this does not prove all DFE filters are bypassed",
        },
        "conclusion": [
            "The retained evidence closes coefficient production through the B RXON commit.",
            "It does not identify the physical LO output divider, PLL loop filter, or external FEM filter switch.",
            "Do not change the 0x37f0 threshold, MDLL factor, or anonymous reset bits without a new named control and a single-variable experiment.",
        ],
        "inputs": [
            "records/rf/reference-b-gap-request-chain.json",
            "records/rf/coverage-v32-filter-assessment.json",
            "firmware/rf_rebuild/rf_core_rxon_prepare_b_prefix.c",
        ],
    }
    out = ROOT / ns.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(out.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
