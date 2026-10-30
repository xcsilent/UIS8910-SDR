#!/usr/bin/env python3
"""UIS8910 resident monitor client. Uses USB serial or physical UART (8N1)."""
from __future__ import annotations
import argparse
import hashlib
import json
import secrets
import struct
import sys
import time
import zlib
from pathlib import Path

MAGIC=b"UDG1"
HEADER=struct.Struct("<4sBBHIII")
MAX_PAYLOAD=4096
BASELINE="bd25923aa2fd2cde32fafe59305b6655a79645ad7ff447b74f0ffd4286a020d1"
FIRMWARES=('uis8910-debug-v1','uis8910-debug-v2-bulk')
OPS={"info":1,"read":2,"write":3,"status":4,"begin":16,"data":17,"end":18,"activate":19,"rollback":20,"call":21,"call_async":22,"bulk_read":32,"rx_stream":33}
STATUS={0:"OK",1:"BAD_REQUEST",2:"RANGE",3:"CRC",4:"UNSUPPORTED",5:"BUSY",6:"TIMEOUT",7:"BASELINE",8:"SEQUENCE",9:"DIGEST",10:"NOT_READY",11:"ACCESS_FAULT"}
CORES={"ap":0,"cp":1,"bcpu":2}
SPACES={"ram":0,"rom":1,"mmio":2,"flash":3}

class DebugError(RuntimeError):
    pass

def frame(op:int,seq:int,payload:bytes=b"",status:int=0)->bytes:
    if len(payload)>MAX_PAYLOAD:
        raise ValueError("payload exceeds 4096 bytes")
    prefix=struct.pack("<4sBBHII",MAGIC,1,op,len(payload),seq,status)
    return prefix+struct.pack("<I",zlib.crc32(prefix+payload)&0xffffffff)+payload

class Decoder:
    def __init__(self):
        self.buffer=bytearray()
    def feed(self,data:bytes):
        self.buffer.extend(data)
        packets=[]
        while True:
            at=self.buffer.find(MAGIC)
            if at<0:
                self.buffer[:]=self.buffer[-3:]
                break
            if at:
                del self.buffer[:at]
            if len(self.buffer)<HEADER.size:
                break
            magic,version,op,n,seq,status,crc=HEADER.unpack_from(self.buffer)
            if version!=1 or n>MAX_PAYLOAD:
                del self.buffer[0]
                continue
            if len(self.buffer)<HEADER.size+n:
                break
            payload=bytes(self.buffer[HEADER.size:HEADER.size+n])
            if zlib.crc32(bytes(self.buffer[:16])+payload)&0xffffffff!=crc:
                del self.buffer[0]
                continue
            del self.buffer[:HEADER.size+n]
            packets.append((op,seq,status,payload))
        return packets

class Client:
    def __init__(self,transport,timeout:float=5.0):
        self.transport=transport
        self.timeout=timeout
        self.seq=secrets.randbelow(0xfffffffe)+1
        self.decoder=Decoder()
        self.capabilities={}
        self.last_async_cp_sequence=None
    def request(self,op:int,payload:bytes=b"")->bytes:
        self.seq=(self.seq+1)&0xffffffff or 1
        wire=frame(op,self.seq,payload)
        # Retries keep the same sequence and bytes; AP replays its last response.
        for attempt in range(3):
            offset=0
            deadline=time.monotonic()+self.timeout
            while offset<len(wire):
                written=self.transport.write(wire[offset:])
                if written is None or written<=0 or written>len(wire)-offset:
                    raise DebugError("transport could not send complete request")
                offset+=written
                if time.monotonic()>deadline:
                    raise DebugError("write timeout")
            while time.monotonic()<deadline:
                for response,seq,status,body in self.decoder.feed(self.transport.read(8192)):
                    if response!=(op|0x80) or seq!=self.seq:
                        continue
                    if status:
                        suffix="; use status to inspect the outstanding CP request" if status in (5,6) else ""
                        raise DebugError(STATUS.get(status,f"ERROR_{status}")+suffix)
                    return body
        raise DebugError("no valid response after three retries")
    def begin_call(self,argument:int)->int:
        """Send one CP_CALL and return without waiting for its completion.

        With advertised CP_CALL_ASYNC support, wait only for the AP queue ACK.
        Its duplicate-response cache makes retries safe. Older firmware uses a
        one-shot legacy CALL; AP servicing then waits for its internal timeout.
        """
        if not isinstance(argument,int) or not 0<=argument<=0xffffffff:
            raise ValueError("CP_CALL argument must be uint32")
        self.last_async_cp_sequence=None
        if self.capabilities.get("cp_call_async"):
            response=self.request(OPS["call_async"],struct.pack("<I",argument))
            if len(response)!=4 or not struct.unpack("<I",response)[0]:
                raise DebugError("invalid asynchronous CP_CALL acceptance sequence")
            self.last_async_cp_sequence=struct.unpack("<I",response)[0]
            return self.seq
        self.seq=(self.seq+1)&0xffffffff or 1
        sequence=self.seq
        wire=frame(OPS["call"],sequence,struct.pack("<I",argument))
        offset=0
        deadline=time.monotonic()+self.timeout
        while offset<len(wire):
            written=self.transport.write(wire[offset:])
            if written is None or written<=0 or written>len(wire)-offset:
                raise DebugError("transport could not send complete asynchronous CP_CALL")
            offset+=written
            if time.monotonic()>deadline:
                raise DebugError("asynchronous CP_CALL write timeout")
        return sequence
    def info(self):
        info=json.loads(self.request(OPS["info"]))
        self.capabilities=info
        return info
    def bulk_read(self,address:int,length:int,width:int=4)->bytes:
        """Read a bounded AP RAM snapshot through sequenced, CRC-protected chunks."""
        if (not 0<length<=65536 or width not in (1,2,4) or address<0 or
            address+length>0x100000000 or address%width or length%width):
            raise ValueError("bulk read needs 1..65536 aligned bytes of AP RAM")
        self.seq=(self.seq+1)&0xffffffff or 1
        wire=frame(OPS['bulk_read'],self.seq,struct.pack('<IIIBB2x',0,address,length,width,0))
        collected=bytearray()
        for attempt in range(3):
            sent=0;deadline=time.monotonic()+self.timeout;retry=False
            while sent<len(wire):
                n=self.transport.write(wire[sent:])
                if n is None or not 0<n<=len(wire)-sent:
                    raise DebugError('transport could not send complete bulk request')
                sent+=n
                if time.monotonic()>deadline:raise DebugError('bulk write timeout')
            while time.monotonic()<deadline:
                for op,seq,status,body in self.decoder.feed(self.transport.read(8192)):
                    if op!=(OPS['bulk_read']|0x80) or seq!=self.seq:continue
                    if status:raise DebugError(STATUS.get(status,f'ERROR_{status}'))
                    if len(body)<16:raise DebugError('short bulk chunk metadata')
                    offset,total,n,flags=struct.unpack_from('<4I',body)
                    if (total!=length or not 0<n<=4080 or n!=len(body)-16 or
                        offset+n>length or flags not in (0,1) or
                        bool(flags)!=(offset+n==length) or offset%width or n%width):
                        raise DebugError('invalid bulk chunk offset/length/final marker')
                    if offset>len(collected):
                        # A frame may have failed CRC or been lost. Drain the
                        # attempt, then replay the same cached snapshot.
                        if flags:retry=True;break
                        continue
                    overlap=min(n,len(collected)-offset)
                    if bytes(collected[offset:offset+overlap])!=body[16:16+overlap]:
                        raise DebugError('bulk retry returned different cached bytes')
                    collected.extend(body[16+overlap:])
                    if flags:
                        if len(collected)!=length:raise DebugError('incomplete bulk snapshot')
                        return bytes(collected)
                if retry:break
        raise DebugError('incomplete bulk read after three retries')
    def status(self):
        raw=self.request(OPS["status"])
        if len(raw)!=40:
            raise DebugError("invalid status size")
        names=("abi","heartbeat","active_entry","active_generation","previous_entry","last_result","request_seq","response_seq","cp_status","pending")
        return dict(zip(names,struct.unpack("<10I",raw)))
    def read(self,core:str,space:str,address:int,length:int,width:int=1)->bytes:
        if length<1 or length>1024 or width not in (1,2,4) or address%width or length%width:
            raise ValueError("read needs 1..1024 bytes aligned to its width")
        payload=struct.pack("<IIIBB2x",CORES[core],address,length,width,SPACES[space])
        data=self.request(OPS["read"],payload)
        if len(data)!=length:
            raise DebugError(f"short memory read: wanted {length}, got {len(data)}")
        return data
    def write(self,core:str,space:str,address:int,data:bytes,width:int=1):
        if not 0<len(data)<=1024 or width not in (1,2,4) or address%width or len(data)%width:
            raise ValueError("write needs 1..1024 bytes aligned to its width")
        self.request(OPS["write"],struct.pack("<IIIBB2x",CORES[core],address,len(data),width,SPACES[space])+data)
    def upload(self,package:dict,blob:bytes):
        validate_package(package,blob)
        self.request(OPS["begin"],struct.pack("<III",len(blob),package["entry_offset"],package["generation"])
                     +bytes.fromhex(package["baseline_sha256"])+hashlib.sha256(blob).digest())
        for offset in range(0,len(blob),1024):
            self.request(OPS["data"],struct.pack("<I",offset)+blob[offset:offset+1024])
        self.request(OPS["end"])

def validate_package(package:dict,blob:bytes):
    if package.get("format")!="uis8910-cp-module-v1" or package.get("abi")!="u32-u32-thumb-pic":
        raise ValueError("unsupported package format / ABI")
    if package.get("baseline_sha256")!=BASELINE:
        raise ValueError("package uses a different CP baseline")
    if not 2<=len(blob)<=8192 or package.get("size")!=len(blob) or package.get("sha256")!=hashlib.sha256(blob).hexdigest():
        raise ValueError("invalid payload size / SHA256")
    entry=package.get("entry_offset")
    if not isinstance(entry,int) or not entry&1 or not 0<=entry&~1<=len(blob)-2:
        raise ValueError("entry_offset must include the Thumb bit and be inside the payload")
    if not isinstance(package.get("generation"),int) or not 0<=package["generation"]<=0xffffffff:
        raise ValueError("generation must be uint32")

def dump(client:Client,core:str,space:str,address:int,length:int,path:Path,width:int=1):
    if length<=0 or address<0 or address+length>0x100000000 or length%width or address%width:
        raise ValueError("invalid dump range / alignment")
    temporary=path.with_name(path.name+".partial")
    digest=hashlib.sha256()
    with temporary.open("wb") as stream:
        for offset in range(0,length,1024):
            data=client.read(core,space,address+offset,min(1024,length-offset),width)
            stream.write(data);digest.update(data)
    temporary.replace(path)
    report={"core":core,"space":space,"address":hex(address),"length":length,
            "sha256":digest.hexdigest(),"output":str(path),"firmware":client.info()}
    path.with_suffix(path.suffix+".json").write_text(json.dumps(report,indent=2)+"\n")
    return report

def make_package(binary:Path,manifest:Path,entry:int,generation:int):
    blob=binary.read_bytes()
    p={"format":"uis8910-cp-module-v1","abi":"u32-u32-thumb-pic","baseline_sha256":BASELINE,
       "size":len(blob),"sha256":hashlib.sha256(blob).hexdigest(),"entry_offset":entry,
       "generation":generation,"binary":binary.name}
    validate_package(p,blob)
    manifest.write_text(json.dumps(p,indent=2)+"\n")
    return p

def bulk_dump(client:Client,address:int,length:int,path:Path,width:int=4):
    info=client.info()
    if not info.get('bulk_read'):raise DebugError('firmware does not advertise AP bulk reads')
    started=time.monotonic();data=client.bulk_read(address,length,width)
    elapsed=time.monotonic()-started
    temporary=path.with_name(path.name+'.partial')
    temporary.write_bytes(data);temporary.replace(path)
    report={'core':'ap','space':'ram','address':hex(address),'length':len(data),'output':str(path),
            'sha256':hashlib.sha256(data).hexdigest(),'seconds':elapsed,'payload_bytes_per_second':len(data)/elapsed,
            'firmware':info,'protocol':'cached-bulk-snapshot-v1','iq_format_calibrated':False}
    path.with_suffix(path.suffix+'.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return report

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port",help="Windows COM14 or Linux /dev/ttyUSB0, etc.")
    parser.add_argument("--baud",type=int,default=115200)
    parser.add_argument("--timeout",type=float,default=5)
    sub=parser.add_subparsers(dest="command",required=True)
    for name in ("info","status","patch-activate","patch-rollback","selftest","bcpu-rom"):
        p=sub.add_parser(name)
        if name=="selftest":p.add_argument("--cycles",type=int,default=100)
        if name=="bcpu-rom":p.add_argument("output",type=Path)
    for name in ("read","write","dump"):
        p=sub.add_parser(name);p.add_argument("address",type=lambda x:int(x,0));p.add_argument("--core",choices=CORES,default="ap")
        p.add_argument("--space",choices=SPACES,default="ram");p.add_argument("--width",type=int,choices=(1,2,4),default=1)
        if name=="write":p.add_argument("hex_data")
        else:p.add_argument("length",type=lambda x:int(x,0))
        if name=="dump":p.add_argument("output",type=Path)
    p=sub.add_parser("call");p.add_argument("argument",type=lambda x:int(x,0),default=0,nargs="?")
    p=sub.add_parser("patch-upload");p.add_argument("manifest",type=Path)
    p=sub.add_parser("package");p.add_argument("binary",type=Path);p.add_argument("manifest",type=Path)
    p.add_argument("--entry",type=lambda x:int(x,0),default=1);p.add_argument("--generation",type=int,default=1)
    p=sub.add_parser('bulk-dump');p.add_argument('address',type=lambda x:int(x,0));p.add_argument('length',type=lambda x:int(x,0))
    p.add_argument('output',type=Path);p.add_argument('--width',type=int,choices=(1,2,4),default=4)
    args=parser.parse_args()
    try:
        if args.command=="package":
            print(json.dumps(make_package(args.binary,args.manifest,args.entry,args.generation),indent=2));return 0
        if not args.port:parser.error("--port is required for device commands")
        import serial
        with serial.Serial(args.port,args.baud,timeout=.1,write_timeout=args.timeout) as transport:
            c=Client(transport,args.timeout)
            if args.command=="info":result=c.info()
            elif args.command=="status":result=c.status()
            elif args.command=="read":result=c.read(args.core,args.space,args.address,args.length,args.width).hex()
            elif args.command=="write":c.write(args.core,args.space,args.address,bytes.fromhex(args.hex_data),args.width);result="OK"
            elif args.command=="dump":result=dump(c,args.core,args.space,args.address,args.length,args.output,args.width)
            elif args.command=='bulk-dump':result=bulk_dump(c,args.address,args.length,args.output,args.width)
            elif args.command=="bcpu-rom":result=dump(c,"ap","rom",0x400a0000,0x28000,args.output,4)
            elif args.command=="call":result=struct.unpack("<I",c.request(OPS["call"],struct.pack("<I",args.argument)))[0]
            elif args.command=="patch-upload":
                p=json.loads(args.manifest.read_text());c.upload(p,(args.manifest.parent/p["binary"]).read_bytes());result="uploaded; use patch-activate"
            elif args.command=="patch-activate":c.request(OPS["activate"]);result=c.status()
            elif args.command=="patch-rollback":c.request(OPS["rollback"]);result=c.status()
            elif args.command=="selftest":
                if not 1<=args.cycles<=10000:raise ValueError("cycles must be 1..10000")
                info=c.info();reports=[]
                for core,key in (("ap","ap_test_ram"),("cp","cp_test_ram")):
                    address=info[key]
                    original=c.read(core,"ram",address,64)
                    try:
                        for cycle in range(args.cycles):
                            pattern=hashlib.sha256(struct.pack("<I",cycle)).digest()*2
                            c.write(core,"ram",address,pattern)
                            if c.read(core,"ram",address,64)!=pattern:raise DebugError(core+" readback mismatch")
                    finally:c.write(core,"ram",address,original)
                    reports.append({"core":core,"cycles":args.cycles,"memory_readback":"passed"})
                result=reports
            print(json.dumps(result,indent=2));return 0
    except (ValueError,OSError,DebugError,ImportError,KeyError) as exc:
        print(f"uis_debug: {exc}",file=sys.stderr);return 1

if __name__=="__main__":raise SystemExit(main())
