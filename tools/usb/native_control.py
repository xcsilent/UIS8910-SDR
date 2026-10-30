"""Windows SDR DLL control adapter. IQ remains on the independent WinUSB path."""
import ctypes
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DEVICE_STATUS={1:'BAD_REQUEST',2:'RANGE',3:'CRC',4:'UNSUPPORTED',5:'BUSY',
               6:'TIMEOUT',7:'BASELINE',8:'SEQUENCE',9:'DIGEST',10:'NOT_READY',11:'ACCESS_FAULT'}


class ControlClient:
    def __init__(self,port,timeout_ms=3000):
        self.api=ctypes.CDLL(str(ROOT/'outputs/host/windows/sdr_usb.dll'))
        pointer=ctypes.c_void_p
        uint=ctypes.c_uint32
        self.api.sdr_control_open.argtypes=[ctypes.POINTER(pointer),ctypes.c_wchar_p,uint]
        self.api.sdr_control_open.restype=uint
        self.api.sdr_control_close.argtypes=[pointer]
        self.api.sdr_control_close.restype=None
        self.api.sdr_control_request.argtypes=[pointer,uint,pointer,uint,pointer,ctypes.POINTER(uint)]
        self.api.sdr_control_request.restype=uint
        self.handle=pointer()
        self._check(self.api.sdr_control_open(ctypes.byref(self.handle),port,timeout_ms))
        self.capabilities={}

    @staticmethod
    def _check(error):
        if error & 0x20000000:
            status=error & ~0x20000000
            raise RuntimeError('device monitor: '+DEVICE_STATUS.get(status,str(status)))
        if error:
            raise ctypes.WinError(error)

    def request(self,operation,payload=b''):
        if not self.handle:
            raise RuntimeError('control port is closed')
        if len(payload)>4096:
            raise ValueError('control payload exceeds 4096 bytes')
        source=ctypes.create_string_buffer(payload,len(payload)) if payload else None
        target=ctypes.create_string_buffer(4096)
        size=ctypes.c_uint32(len(target))
        self._check(self.api.sdr_control_request(self.handle,operation,source,len(payload),target,ctypes.byref(size)))
        return target.raw[:size.value]

    def info(self):
        self.capabilities=json.loads(self.request(1))
        return self.capabilities

    def close(self):
        if self.handle:
            self.api.sdr_control_close(self.handle)
            self.handle=ctypes.c_void_p()

    def __enter__(self):
        return self

    def __exit__(self,*error):
        self.close()
