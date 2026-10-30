"""Read opt-in RF phase records from stopped/drained matching firmware only."""
import hashlib,json,struct,sys
from pathlib import Path
from datetime import datetime
from .rf_catalog import ROOT
from .rf_runtime import stopped

ADDRESS=0x8096dc00
STAGES={1:'after_prepare',2:'before_rx_request',3:'after_rx_request',4:'before_rf_stop',5:'after_rf_stop'}

def decode(data,generation):
    if len(data) not in (256,512):raise ValueError('RF trace must be256 or512bytes')
    w=struct.unpack('<'+str(len(data)//4)+'I',data)
    abi=w[1]
    if {1:256,2:512,3:512,4:512,5:512}.get(abi)!=len(data) or w[:3]!=(0x52535431,abi,generation) or w[3]>5:
        raise ValueError('RF trace identity/generation/count mismatch')
    rows=[]
    for i in range(w[3]):
        stride=8 if abi==1 else 16
        v=w[8+i*stride:8+(i+1)*stride]
        if v[0]!=i+1:raise ValueError('RF trace stage order mismatch')
        rows.append(dict(stage=STAGES[v[0]],status_3037c=v[1],status_bit11=bool(v[1]&0x800),
            control_30374=v[2]&65535,control_30364=v[2]>>16,
            mdll_control_30410=v[3]&65535,mdll_control_32a00=v[3]>>16,
            configured_divider=(v[3]>>11)&15,encoding_302e0=v[4]&65535,encoding_302c0=v[4]>>16,
            flow_enable_b464=v[5]&65535,context_factor_b526=v[5]>>16,
            working_raw=v[6],cp_phase=v[7]))
        if abi in (2,3,4,5):
            rows[-1].update(rx_status_3036c=v[8],rxpll_cal_ready_reference=bool(v[8]&0x800),
                rxpll_cnt_enable_reference=bool(v[8]&0x1000),rxpll_cal_enable_reference=bool(v[8]&0x2000),
                rxpll_vco_bits_reference=v[8]&0x7ff,txpll_cal_ready_reference=bool(v[1]&0x800),
                txpll_cnt_enable_reference=bool(v[1]&0x1000),txpll_cal_enable_reference=bool(v[1]&0x2000),
                txpll_vco_bits_reference=v[1]&0x7ff,selector=v[9]&65535,rx_port=v[9]>>16,
                route_30468=v[10]&65535,route_30480=v[10]>>16,
                analog_mode_flag_b4e0=v[11]&65535,digital_flag_b52a=v[11]>>16,
                bbpll1_status_30324=v[12]&65535,bbpll2_status_30354=v[12]>>16,
                bbpll1_lock_reference=bool(v[12]&0x4000),bbpll2_lock_reference=bool(v[12]&0x40000000))
            if abi==2 and any(v[13:]):raise ValueError('ABI2 reserved trace words must be zero')
            if abi in (3,4,5):
                if v[15]&~7:raise ValueError('ABI3 unknown FEM flags')
                rows[-1]['rffe_saved_result']=dict(target_slave=v[13]&65535,
                    manufacturer_id_low=v[13]>>16,product_id=v[14]&65535,configured_target_slave=v[14]>>16,
                    config_pointer_matches=bool(v[15]&1),stable_double_read=bool(v[15]&2),
                    target_matches_configuration=bool(v[15]&4),hardware_identity_verified=False,
                    completion_observed=False,timeout_known=False,
                    scope='Saved RF RAM only; zero may mean timeout, stale/absent or actual zero. No RFFE transaction, ACK or device variant confirmed.')
    commands=[]
    execution=[]
    if abi==5:
        for i in range(5):
            v=w[88+i*8:96+i*8]
            if i>=w[3]:
                if any(v):raise ValueError('unused RF execution row is nonzero')
                continue
            if v[0]!=i+1 or v[7] or v[6]&~3:raise ValueError('invalid RF execution row')
            matches=v[1]==0x0120506f
            if bool(v[6]&1)!=matches or (not matches and any(v[2:])):
                raise ValueError('invalid RF observer signature/flags')
            stable=matches and v[2:4]==v[4:6]
            if bool(v[6]&2)!=bool(stable):raise ValueError('RF observer consistency flags mismatch')
            execution.append(dict(stage=STAGES[v[0]],instruction_signature=hex(v[1]),
                matching_observer=matches,stable_double_read=bool(stable),
                count_before=v[2] if matches else None,count_after=v[4] if matches else None,
                last_pointer_before=hex(v[3]) if matches else None,last_pointer_after=hex(v[5]) if matches else None,
                scope='Helper entry count modulo2^32 and NV command pointer before controller writes; not completion/ACK or atomic live telemetry.'))
    if abi==4:
        objects=(0x804ee978,0x804efcc8,0x804edc98,0x804ee4a4,0x804ef320)
        for expected in (2,3):
            tail=w[88+(expected-2)*20:88+(expected-1)*20]
            if tail[0] not in (0,expected) or any(tail[16:]):raise ValueError('invalid command snapshot row')
            if bool(tail[0]) != (w[3]>=expected):raise ValueError('command snapshot stage/count mismatch')
            if not tail[0]:
                if any(tail):raise ValueError('incomplete command snapshot row')
                continue
            entries=[]
            for i,obj in enumerate(objects):
                pointer,value,valid=tail[1+3*i:4+3*i]
                allowed=not pointer%4 and (0x25101260<=pointer<=0x2510157c or 0x25102260<=pointer<=0x2510257c)
                if valid not in (0,1) or bool(valid)!=bool(allowed) or (not valid and value):raise ValueError('invalid command pointer observation')
                entries.append(dict(object=hex(obj),pointer=hex(pointer),valid=bool(valid),value=value if valid else None))
            commands.append(dict(stage=STAGES[expected],entries=entries))
    return dict(generation=hex(generation),trace_abi=abi,complete=w[3]==5,records=rows,command_observations=commands,execution_observations=execution,
        meaning='Phase observations only: reference bit11 cal_ready, bit12 cnt_enable, bit13 cal_enable are read-only status names; none is established RF LO lock or physical cutoff.',
        time_resolution='transaction checkpoints; no lock-time measurement',lost_samples_known=False)

def snapshot(port,cp_build,output):
    import serial
    sys.path.insert(0,str(ROOT/'tools/debug'))
    from uis_debug import Client
    build_path=Path(cp_build).resolve();output=Path(output).resolve()
    if not output.is_relative_to(ROOT) or output.exists() or not output.parent.is_dir():
        raise ValueError('choose a new JSON output in an existing project directory')
    build=json.loads(build_path.read_text(encoding='utf-8'));feature=build.get('rf_status_trace',{})
    abi=feature.get('abi',1);size={1:256,2:512,3:512,4:512,5:512}.get(abi)
    address=0x8096e000 if build.get('slot_bytes',8000)==8192 else ADDRESS
    if not feature.get('enabled') or feature.get('address')!=hex(address) or size is None or feature.get('bytes')!=size:
        raise ValueError('explicit matching RF diagnostic CP build required')
    generation=int(build['generation'],0)
    report=dict(recorded_at=datetime.now().astimezone().isoformat(),status='starting',device_accessed=False,
        read_only=True,firmware_changed=False,rf_transmitted=False,physical_lock_identified=False,trace_address_read=False)
    try:
        with serial.Serial(port,115200,timeout=.1,write_timeout=5) as transport:
            report['device_accessed']=True;c=Client(transport,5);info=c.info();report['firmware']=info
            if (info.get('firmware')!='uis8910-sdr-bw0-usb-v1' or not info.get('bulk_read') or
                info.get('cp_baseline_sha256')!='bd25923aa2fd2cde32fafe59305b6655a79645ad7ff447b74f0ffd4286a020d1'):
                raise ValueError('unsupported service identity/baseline')
            before=list(struct.unpack('<48I',c.request(44)));stopped(before)
            progress=struct.unpack('<16I',c.bulk_read(0x8096fec0,64,4))
            if progress[0]!=0x54524d31 or progress[1]!=generation or progress[2]&1 or progress[3]!=30 or progress[4]:
                raise ValueError('running CP generation/stopped proof differs; trace address not read')
            report['trace_address_read']=True;report['trace_address']=hex(address);raw=c.bulk_read(address,size,4)
            if raw!=c.bulk_read(address,size,4):raise ValueError('RF trace changed during read')
            after=list(struct.unpack('<48I',c.request(44)));stopped(after)
            if before[5]!=after[5]:raise ValueError('receiver epoch changed during read')
            decoded=decode(raw,generation)
            if decoded['trace_abi']!=abi:raise ValueError('trace ABI differs from matching CP build')
            report.update(status='passed',epoch=after[5],**decoded)
    except Exception as error:report.update(status='failed',error=str(error))
    report['dependencies']={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__),ROOT/'tools/sdr/rf_runtime.py',ROOT/'tools/debug/uis_debug.py',build_path)}
    output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');return report
