"""Offline tests of raw-IQ queue ownership; does not open USB or serial ports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def verify(output):
    if os.name == 'nt':
        raise RuntimeError('run this verifier with WSL python3 (native gcc and ARM gcc required)')
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise ValueError('choose a new output file inside the project')
    build = ROOT / 'work/sdr-usb-ring-v1'
    build.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'firmware/sdr_receiver/iq_usb_ring.c'
    header = source.with_suffix('.h')
    harness = Path(__file__).with_name('iq_usb_ring_harness.c')
    cases = []
    for optimization in ('O0', 'O2'):
        executable = build / ('host-' + optimization)
        subprocess.run(['gcc', '-std=c11', '-'+optimization, '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=undefined', '-fno-sanitize-recover=all', '-I'+str(source.parent),
                        str(source), str(harness), '-o', str(executable)], check=True)
        result = subprocess.check_output([str(executable)], text=True).strip()
        arm = build / ('arm-' + optimization + '.o')
        subprocess.run(['arm-none-eabi-gcc', '-mcpu=cortex-a5', '-mthumb', '-mfloat-abi=soft',
                        '-std=c11', '-'+optimization, '-Wall', '-Wextra', '-Werror', '-ffreestanding',
                        '-fno-builtin', '-c', str(source), '-o', str(arm)], check=True)
        undefined = subprocess.check_output(['arm-none-eabi-nm', '-u', str(arm)], text=True).strip()
        if undefined:
            raise ValueError('unexpected runtime dependency: '+undefined)
        cases.append(dict(optimization=optimization, host_test=result,
                          arm_object=arm.relative_to(ROOT).as_posix(), undefined_symbols=[]))
    adapter = source.with_name('iq_udc_adapter.c')
    adapter_harness = harness.with_name('iq_udc_adapter_harness.c')
    adapter_executable = build/'host-udc-adapter'
    subprocess.run(['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all', '-I'+str(source.parent),
                    str(source), str(adapter), str(adapter_harness), '-o', str(adapter_executable)], check=True)
    adapter_result = subprocess.check_output([str(adapter_executable)], text=True).strip()
    adapter_arm = build/'arm-udc-adapter.o'
    subprocess.run(['arm-none-eabi-gcc', '-mcpu=cortex-a5', '-mthumb', '-mfloat-abi=soft',
                    '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-ffreestanding',
                    '-fno-builtin', '-c', str(adapter), '-o', str(adapter_arm)], check=True)
    adapter_undefined = subprocess.check_output(['arm-none-eabi-nm', '-u', str(adapter_arm)], text=True).strip()
    imports = [line.split()[-1] for line in adapter_undefined.splitlines()]
    allowed_imports = {'memset', 'iq_usb_complete', 'iq_usb_drained', 'iq_usb_stop', 'iq_usb_take'}
    if set(imports)-allowed_imports:
        raise ValueError('unexpected UDC adapter runtime dependency: '+adapter_undefined)
    files = (source, header, harness, adapter, adapter.with_suffix('.h'),
             source.with_name('udc_8910.h'), adapter_harness, Path(__file__))
    report = dict(status='passed', hardware_integrated=False, device_accessed=False,
                  test_cases=cases, payload_cpu_reads=0, payload_cpu_copies=0,
                  application_crc=False, wire_header=False, application_retries=False,
                  dma_payload_memory_mapped_in_host_test=False,
                  udc_adapter=dict(host_test=adapter_result,
                    arm_object=adapter_arm.relative_to(ROOT).as_posix(), undefined_symbols=imports,
                    controller_private_requests=True, actual_completion_required=True),
                  scope='ring and UDC ABI adapter compiled for ARM and host-tested; exclusive endpoint/cache/capture platform integration still required',
                  dependencies=[dict(path=p.relative_to(ROOT).as_posix(),
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    verify(parser.parse_args().output)
