"""Inspect, or explicitly bind, inbox WinUSB for one present SDR interface.

Uses the compatible driver list and DiInstallDevice, never removes packages,
edits registry IDs, disables signature checks, or changes the composite parent.
Default is read-only. --install requires Windows administrator privileges.
"""
import argparse
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime
import json
import os
from pathlib import Path
import re


class Device(c.Structure):
    _fields_ = [('size', w.DWORD), ('guid', c.c_byte * 16),
                ('devinst', w.DWORD), ('reserved', c.c_size_t)]


class Driver(c.Structure):
    _fields_ = [('size', w.DWORD), ('kind', w.DWORD), ('reserved', c.c_size_t),
                ('description', w.WCHAR * 256), ('manufacturer', w.WCHAR * 256),
                ('provider', w.WCHAR * 256), ('date', w.FILETIME),
                ('version', c.c_uint64)]


class Detail(c.Structure):
    _fields_ = [('size', w.DWORD), ('date', w.FILETIME),
                ('compat_offset', w.DWORD), ('compat_length', w.DWORD),
                ('reserved', c.c_size_t), ('section', w.WCHAR * 256),
                ('inf', w.WCHAR * 260), ('description', w.WCHAR * 256),
                ('hardware_id', w.WCHAR * 1)]


def run(instance, install=False):
    if os.name != 'nt' or c.sizeof(c.c_void_p) != 8:
        raise OSError('requires native 64-bit Windows Python')
    if not re.fullmatch(r'USB\\VID_1782&PID_4E00&MI_[0-9A-F]{2}\\[^\\]+', instance, re.I):
        raise ValueError('specify one UIS8910 child interface instance, never the parent')
    api = c.WinDLL('setupapi', use_last_error=True)
    signatures = {
        'SetupDiGetClassDevsW': ([c.c_void_p, w.LPCWSTR, w.HWND, w.DWORD], w.HANDLE),
        'SetupDiEnumDeviceInfo': ([w.HANDLE, w.DWORD, c.POINTER(Device)], w.BOOL),
        'SetupDiGetDeviceInstanceIdW': ([w.HANDLE, c.POINTER(Device), w.LPWSTR, w.DWORD, c.POINTER(w.DWORD)], w.BOOL),
        'SetupDiGetDeviceRegistryPropertyW': ([w.HANDLE, c.POINTER(Device), w.DWORD, c.POINTER(w.DWORD), c.c_void_p, w.DWORD, c.POINTER(w.DWORD)], w.BOOL),
        'SetupDiBuildDriverInfoList': ([w.HANDLE, c.POINTER(Device), w.DWORD], w.BOOL),
        'SetupDiEnumDriverInfoW': ([w.HANDLE, c.POINTER(Device), w.DWORD, w.DWORD, c.POINTER(Driver)], w.BOOL),
        'SetupDiGetDriverInfoDetailW': ([w.HANDLE, c.POINTER(Device), c.POINTER(Driver), c.c_void_p, w.DWORD, c.POINTER(w.DWORD)], w.BOOL),
        'SetupDiDestroyDriverInfoList': ([w.HANDLE, c.POINTER(Device), w.DWORD], w.BOOL),
        'SetupDiDestroyDeviceInfoList': ([w.HANDLE], w.BOOL),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(api, name)
        fn.argtypes, fn.restype = args, result

    def check(ok):
        if not ok:
            raise c.WinError(c.get_last_error())

    devices = api.SetupDiGetClassDevsW(None, 'USB', None, 6)  # PRESENT | ALLCLASSES
    if devices == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    built = False
    device = Device()
    try:
        index = 0
        while True:
            device.size = c.sizeof(Device)
            if not api.SetupDiEnumDeviceInfo(devices, index, c.byref(device)):
                if c.get_last_error() == 259:
                    raise ValueError('specified child interface is not present')
                raise c.WinError(c.get_last_error())
            name = c.create_unicode_buffer(1024)
            check(api.SetupDiGetDeviceInstanceIdW(devices, c.byref(device), name, len(name), None))
            if name.value.casefold() == instance.casefold():
                break
            index += 1

        def prop(number):
            data = c.create_string_buffer(65536)
            size, kind = w.DWORD(), w.DWORD()
            check(api.SetupDiGetDeviceRegistryPropertyW(devices, c.byref(device), number,
                  c.byref(kind), data, len(data), c.byref(size)))
            if kind.value not in (1, 7):
                raise ValueError('unexpected device property type')
            return data.raw[:size.value].decode('utf-16le').rstrip('\0').split('\0')

        hardware, compatible = prop(1), prop(2)
        ids = [v.upper() for v in compatible]
        if ('USB\\MS_COMP_WINUSB' not in ids or
                'USB\\CLASS_FF&SUBCLASS_53&PROT_44' not in ids):
            raise ValueError('child does not advertise the SDR signature and WinUSB compatibility')
        report = dict(recorded_at=datetime.now().astimezone().isoformat(), instance=instance,
                      hardware_ids=hardware, compatible_ids=compatible,
                      previous_service=prop(4)[0], install_requested=install,
                      driver_installed=False, compatible_drivers=[])
        check(api.SetupDiBuildDriverInfoList(devices, c.byref(device), 2))
        built = True
        selected = []
        index = 0
        while True:
            driver = Driver()
            driver.size = c.sizeof(Driver)
            if not api.SetupDiEnumDriverInfoW(devices, c.byref(device), 2, index, c.byref(driver)):
                if c.get_last_error() == 259:
                    break
                raise c.WinError(c.get_last_error())
            detail_buffer = c.create_string_buffer(65536)
            detail = Detail.from_buffer(detail_buffer)
            detail.size = c.sizeof(Detail)
            check(api.SetupDiGetDriverInfoDetailW(devices, c.byref(device), c.byref(driver),
                  detail_buffer, len(detail_buffer), None))
            row = dict(description=driver.description, provider=driver.provider,
                       inf=detail.inf, section=detail.section)
            report['compatible_drivers'].append(row)
            if (Path(detail.inf).name.casefold() == 'winusb.inf' and
                    driver.provider == 'Microsoft'):
                selected.append((driver, row))
            index += 1
        if len(selected) != 1:
            raise ValueError('expected exactly one compatible Microsoft inbox winusb.inf')
        report['selected_driver'] = selected[0][1]
        if install:
            newdev = c.WinDLL('newdev', use_last_error=True)
            newdev.DiInstallDevice.argtypes = [w.HWND, w.HANDLE, c.POINTER(Device),
                                              c.POINTER(Driver), w.DWORD, c.POINTER(w.BOOL)]
            newdev.DiInstallDevice.restype = w.BOOL
            reboot = w.BOOL()
            check(newdev.DiInstallDevice(None, devices, c.byref(device),
                  c.byref(selected[0][0]), 0, c.byref(reboot)))
            report.update(driver_installed=True, reboot_required=bool(reboot.value))
        report['status'] = 'installed_pending_interface_verification' if install else 'inspected'
        return report
    finally:
        if built:
            api.SetupDiDestroyDriverInfoList(devices, c.byref(device), 2)
        api.SetupDiDestroyDeviceInfoList(devices)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', required=True)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Reserve the evidence path before any driver mutation.
    with args.output.open('x', encoding='utf-8') as stream:
        try:
            report = run(args.instance, args.install)
        except (OSError, ValueError) as error:
            report = dict(status='failed', instance=args.instance,
                          install_requested=args.install, error=str(error))
        stream.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return int(report['status'] == 'failed')


if __name__ == '__main__':
    raise SystemExit(main())
