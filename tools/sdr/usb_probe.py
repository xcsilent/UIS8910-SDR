"""Read USB speed/interfaces/endpoints via the hub, without driver rebinding."""
import argparse
import ctypes
from datetime import datetime
import json
import os
from pathlib import Path
import struct
import uuid

ROOT = Path(__file__).resolve().parents[2]
GET_DESCRIPTOR = 0x220410


def parse_configuration(raw):
    if len(raw) < 9 or raw[0:2] != b'\x09\x02':
        raise ValueError('configuration descriptor header differs')
    total = struct.unpack_from('<H', raw, 2)[0]
    if len(raw) != total:
        raise ValueError('configuration descriptor length differs')
    interfaces = []
    at = 0
    active = None
    while at < len(raw):
        length, kind = raw[at:at+2]
        if length < 2 or at+length > len(raw):
            raise ValueError('descriptor escapes configuration')
        part = raw[at:at+length]
        if kind == 4 and length >= 9:
            active = dict(number=part[2], alternate=part[3], endpoint_count=part[4],
                          interface_class=part[5], subclass=part[6], protocol=part[7], endpoints=[])
            interfaces.append(active)
        elif kind == 5 and length >= 7:
            if active is None:
                raise ValueError('endpoint without interface')
            active['endpoints'].append(dict(address=hex(part[2]),
                direction='in' if part[2]&128 else 'out',
                transfer_type={0:'control',1:'isochronous',2:'bulk',3:'interrupt'}[part[3]&3],
                maximum_packet_bytes=struct.unpack_from('<H',part,4)[0]&2047, interval=part[6]))
        at += length
    return dict(total_bytes=total, configuration_value=raw[5], interfaces=interfaces,
                descriptor_hex=raw.hex())


def query_configuration(kernel, handle, port):
    from ctypes import wintypes
    def get(length):
        request = ctypes.create_string_buffer(12+length)
        struct.pack_into('<IBBHHH',request,0,port,0x80,6,0x200,0,length)
        returned = wintypes.DWORD()
        if not kernel.DeviceIoControl(handle,GET_DESCRIPTOR,request,len(request),request,len(request),
                                      ctypes.byref(returned),None):
            raise ctypes.WinError(ctypes.get_last_error())
        return request.raw[12:returned.value]
    short = get(9)
    if len(short) != 9 or short[:2] != b'\x09\x02':
        raise ValueError('short configuration request failed')
    length = struct.unpack_from('<H',short,2)[0]
    if not 9 <= length <= 65535:
        raise ValueError('configuration size outside USB descriptor bounds')
    return parse_configuration(get(length))


def probe(output):
    output = Path(output).resolve()
    if not output.is_relative_to(ROOT) or output.exists():
        raise ValueError('choose a new output file inside the project')
    if os.name != 'nt':
        raise OSError('USB hub queries require Windows')
    report = query_hubs()
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x', encoding='utf-8') as target:
        target.write(json.dumps(report,indent=2)+'\n')
    if not report['matches'] and any(row['error']==5 for row in report['errors']):
        raise PermissionError('USB hub read-only query was denied')
    return report


def query_hubs():
    """Use hub IOCTLs only; never open the target's data/control interfaces."""
    from ctypes import wintypes
    class InterfaceData(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('guid',ctypes.c_ubyte*16),
                  ('flags',wintypes.DWORD),('reserved',ctypes.c_size_t)]
    setup=ctypes.WinDLL('setupapi',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    setup.SetupDiGetClassDevsW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR,wintypes.HWND,wintypes.DWORD]
    setup.SetupDiGetClassDevsW.restype=wintypes.HANDLE
    setup.SetupDiEnumDeviceInterfaces.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.c_void_p,
        wintypes.DWORD,ctypes.POINTER(InterfaceData)]
    setup.SetupDiGetDeviceInterfaceDetailW.argtypes=[wintypes.HANDLE,ctypes.POINTER(InterfaceData),
        ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
    setup.SetupDiDestroyDeviceInfoList.argtypes=[wintypes.HANDLE]
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,
        wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.DeviceIoControl.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,
        ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    guid=ctypes.create_string_buffer(uuid.UUID('f18a0e88-c30c-11d0-8815-00a0c906bed8').bytes_le)
    device_set=setup.SetupDiGetClassDevsW(guid,None,None,0x12)
    if device_set==ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    report=dict(recorded_at=datetime.now().astimezone().isoformat(),read_only=True,
                usb_resets=0,serial_ports_opened=0,hub_queries=0,matches=[],errors=[])
    try:
        index=0
        while True:
            interface=InterfaceData()
            interface.size=ctypes.sizeof(interface)
            if not setup.SetupDiEnumDeviceInterfaces(device_set,None,guid,index,ctypes.byref(interface)):
                if ctypes.get_last_error()==259:
                    break
                raise ctypes.WinError(ctypes.get_last_error())
            index+=1
            required=wintypes.DWORD()
            setup.SetupDiGetDeviceInterfaceDetailW(device_set,ctypes.byref(interface),None,0,
                ctypes.byref(required),None)
            if required.value < 8:
                raise ctypes.WinError(ctypes.get_last_error())
            detail=ctypes.create_string_buffer(required.value)
            struct.pack_into('<I',detail,0,8 if ctypes.sizeof(ctypes.c_void_p)==8 else 6)
            if not setup.SetupDiGetDeviceInterfaceDetailW(device_set,ctypes.byref(interface),detail,
                    required.value,ctypes.byref(required),None):
                raise ctypes.WinError(ctypes.get_last_error())
            path=ctypes.wstring_at(ctypes.addressof(detail)+4)
            handle=kernel.CreateFileW(path,0,3,None,3,0,None)
            if handle==ctypes.c_void_p(-1).value:
                report['errors'].append(dict(hub=path,error=ctypes.get_last_error()))
                continue
            try:
                report['hub_queries']+=1
                node,returned=ctypes.create_string_buffer(4096),wintypes.DWORD()
                if not kernel.DeviceIoControl(handle,0x220408,node,len(node),node,len(node),
                                               ctypes.byref(returned),None):
                    report['errors'].append(dict(hub=path,error=ctypes.get_last_error()))
                    continue
                for port in range(1,node.raw[6]+1):
                    data=ctypes.create_string_buffer(4096)
                    struct.pack_into('<I',data,0,port)
                    if not kernel.DeviceIoControl(handle,0x220448,data,len(data),data,len(data),
                                                   ctypes.byref(returned),None):
                        report['errors'].append(dict(hub=path,port=port,error=ctypes.get_last_error()))
                        continue
                    raw=data.raw
                    if (returned.value < 24 or raw[4:6]!=bytes((18,1)) or
                            struct.unpack_from('<HH',raw,12)!=(0x1782,0x4e00)):
                        continue
                    speed=raw[23]
                    match=dict(hub=path,port=port,vid='0x1782',pid='0x4e00',speed_value=speed,
                        speed={0:'low',1:'full',2:'high',3:'super',4:'super-plus'}.get(speed,'unknown'),
                        descriptor_and_connection_hex=raw[:min(returned.value,36)].hex())
                    report['matches'].append(match)
                    try:
                        match['configuration']=query_configuration(kernel,handle,port)
                    except (OSError,ValueError) as error:
                        match['configuration_error']=str(error)
            finally:
                kernel.CloseHandle(handle)
    finally:
        setup.SetupDiDestroyDeviceInfoList(device_set)
    report['status']='matched' if report['matches'] else 'not_found'
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    probe(args.output)
