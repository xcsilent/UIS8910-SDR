"""Inspect SDK RF NV and execute native CP channel/route selectors offline.

Default SDK NV is not the module's calibration. No device access or deployment.
Only integer division is simulated; the band/NV selection instructions are CP BIN.
"""
import hashlib
import argparse
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_PC,UC_ARM_REG_LR,UC_ARM_REG_SP

BASE=0x801ab000
ENTRY=0x802d043a
TABLE=0x80471944
RFNV=0x804f42b8
RETURN=0x70000000
SDK=ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp-build',type=Path,required=True)
    parser.add_argument('--runtime-snapshot',type=Path,help='also execute native selector and rebuilt guard against a retained runtime snapshot')
    parser.add_argument('--output',type=Path,default=ROOT/'records/usb/rf-channel-routes.json')
    args=parser.parse_args()
    cp_build=args.cp_build.resolve()
    cp_modules=json.loads(cp_build.read_text(encoding='utf-8'))
    resident=ROOT/cp_modules['resident']['path'];assert digest(resident)==cp_modules['resident']['sha256']
    resident_elf=resident.with_suffix('.elf')
    cp=SDK/'cpbin/cp.bin';nv_path=SDK/'nvbin/rf_nv.bin';elf_path=SDK/'cpbin/cp.axf'
    inventory_path=ROOT/'records/usb/rf-channel-inventory.json'
    inventory=json.loads(inventory_path.read_text(encoding='utf-8'))
    assert digest(cp)==inventory['cp_sha256']
    blob=cp.read_bytes();nv=nv_path.read_bytes()
    assert len(nv)==22528
    machine=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    machine.mem_map(0x80000000,0x1000000);machine.mem_map(RETURN,0x1000)
    machine.mem_write(BASE,blob)
    with resident_elf.open('rb') as stream:
        deployed=ELFFile(stream)
        compiled_symbols={s.name:s['st_value'] for s in deployed.get_section_by_name('.symtab').iter_symbols()}
        guard=compiled_symbols['terminal_profile_nv_row']
        for segment in deployed.iter_segments():
            if segment['p_type']=='PT_LOAD' and segment['p_filesz']:
                machine.mem_write(segment['p_vaddr'],segment.data())
    # Match every original table byte against the current SDK symbol data.
    with elf_path.open('rb') as stream:
        elf=ELFFile(stream)
        symbols={s.name:s for s in elf.get_section_by_name('.symtab').iter_symbols()}
        def symbol_data(name):
            s=symbols[name];section=elf.get_section(s['st_shndx'])
            at=s['st_value']-section['sh_addr']
            return section.data()[at:at+s['st_size']]
        band_data=symbol_data('g_u16_band_tab')
        assert len(band_data)==54
        assert blob[inventory['band_id_table_file_offset']:inventory['band_id_table_file_offset']+54]==band_data
        for name,delta in (('g_u16_band_tab',-54),('g_u16_noffsdl_tab',0),('g_u16_nmaxdl_tab',54),
                           ('g_u16_fdllow_tab',162),('g_u16_fuplow_tab',216)):
            data=symbol_data(name);offset=inventory['band_id_table_file_offset']+54+delta
            assert blob[offset:offset+54]==data
    table_offset=inventory['band_id_table_file_offset']
    # Seven contiguous 27-halfword arrays used by the original selector.
    table_image=blob[table_offset:table_offset+7*54]
    machine.mem_write(TABLE-54,table_image)
    # Reproduce the retained rfad_load_nv_parameters halfword-copy layout.
    rfnv=bytearray(16384)
    spans=((0,0x10),(0x20,0x146),(0x2ac,0x8be),(0x1428,0x2c4),(0x19cc,0x6c0),
           (0x274c,0x24e),(0x3e20,0x7e),(0x2be8,0x512),(0x373c,0x242),(0x3f1c,0x20),
           (0x3bc0,0x12c),(0x19b0,0xe),(0x3e18,4),(0x360c,0x2c),(0x3664,0x1a),(0x3698,0x1a))
    for dest,count in spans:
        source=dest+(0 if dest==0 else 0x1800)
        rfnv[dest:dest+2*count]=nv[source:source+2*count]
    machine.mem_write(RFNV,bytes(rfnv))
    sdk_bands=list(struct.unpack_from('<24H',rfnv,0x20))
    runtime_checks=None
    runtime_inputs=[]
    def check_runtime():
        snapshot_path=args.runtime_snapshot.resolve()
        snapshot=json.loads(snapshot_path.read_text(encoding='utf-8'))
        assert snapshot['status']=='passed' and snapshot['stable_repeated_reads']
        assert snapshot['firmware']['cp_baseline_sha256']==digest(cp)
        payloads={}
        for artifact in snapshot['artifacts']:
            source=ROOT/artifact['path'];assert digest(source)==artifact['sha256']
            payloads[int(artifact['address'],0)]=source.read_bytes();runtime_inputs.append(source)
        prefix=payloads[RFNV];live_tables=payloads[TABLE-54]
        assert len(prefix)==0x180 and len(live_tables)==378
        rfnv[:len(prefix)]=prefix
        machine.mem_write(RFNV,bytes(rfnv));machine.mem_write(TABLE-54,live_tables)
        selected=select(36275)
        assert selected['nv_row']==13 and selected['selector']==20 and selected['rx_port']==1
        assert selected['frequency_raw']==20175000 and guarded_row(36275)==14
        if 34 in cp_modules['rf_profiles']:assert compiled_anchor(36275)==20175000
        assert guarded_row(3100)==0
        missing=select(3100,13)
        assert missing['nv_row']==13 # Native stale-row behavior is still guarded.
        runtime_checks=dict(snapshot=snapshot_path.relative_to(ROOT).as_posix(),
            b34=selected,b34_compiled_anchor_available=34 in cp_modules['rf_profiles'],
            b34_guard_returns_row_plus_one=14,b7_guard_rejects=True,
            b7_native_retains_stale_row=missing,physical_reception_verified=False)
        runtime_inputs.append(snapshot_path)
        return runtime_checks
    info_base=struct.unpack_from('<I',blob,0x802d06dc-BASE)[0]+0x48
    assert 0x804e0000<=info_base<0x80500000
    division_calls=0
    def hook(uc,address,size,context):
        nonlocal division_calls
        if address==RETURN:uc.emu_stop()
        elif address==0x802e910c:
            a,b=uc.reg_read(UC_ARM_REG_R0),uc.reg_read(UC_ARM_REG_R1)
            assert b
            division_calls+=1
            uc.reg_write(UC_ARM_REG_R0,a//b);uc.reg_write(UC_ARM_REG_R1,a%b)
            uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    machine.hook_add(UC_HOOK_CODE,hook)
    def guarded_row(channel):
        machine.reg_write(UC_ARM_REG_SP,0x80eff000);machine.reg_write(UC_ARM_REG_LR,RETURN)
        machine.reg_write(UC_ARM_REG_R0,channel)
        machine.emu_start(guard|1,RETURN,count=10000)
        assert machine.reg_read(UC_ARM_REG_PC)==RETURN
        return machine.reg_read(UC_ARM_REG_R0)
    def compiled_anchor(channel):
        machine.reg_write(UC_ARM_REG_SP,0x80eff000);machine.reg_write(UC_ARM_REG_LR,RETURN)
        machine.reg_write(UC_ARM_REG_R0,channel)
        machine.emu_start(compiled_symbols['terminal_profile_anchor']|1,RETURN,count=10000)
        assert machine.reg_read(UC_ARM_REG_PC)==RETURN
        return machine.reg_read(UC_ARM_REG_R0)
    def select(channel,previous_nv=65535):
        machine.mem_write(info_base,bytes(64))
        machine.mem_write(info_base+4,struct.pack('<H',previous_nv))
        machine.reg_write(UC_ARM_REG_SP,0x80eff000);machine.reg_write(UC_ARM_REG_LR,RETURN)
        machine.reg_write(UC_ARM_REG_R0,channel)
        machine.emu_start(ENTRY|1,RETURN,count=10000)
        assert machine.reg_read(UC_ARM_REG_PC)==RETURN
        result=machine.mem_read(info_base,64)
        band=struct.unpack_from('<H',result,0)[0]
        nv_row,selector=struct.unpack_from('<2H',result,4)
        raw=struct.unpack_from('<I',result,28)[0]
        return dict(raw_band_id=band,nv_row=nv_row if nv_row!=65535 else None,
                    selector=selector,frequency_raw=raw,
                    rx_port=struct.unpack_from('<H',rfnv,0xf0+4*nv_row)[0] if nv_row<24 else None)
    rows=[]
    for row in inventory['rows']:
        low,high=row['channel_first'],row['channel_last']
        observations=[]
        for channel in (low,(low+high)//2,high):
            result=select(channel)
            assert result['raw_band_id']==row['raw_band_id']
            assert result['frequency_raw']==row['dl_first_hz']//100+(channel-low)*1000
            assert guarded_row(channel)==(result['nv_row']+1 if result['nv_row'] is not None else 0)
            observations.append(dict(channel=channel,**result))
        rows.append(dict(table_row=row['row'],raw_band_id=row['raw_band_id'],
            sdk_nv_match=observations[0]['nv_row'] is not None,observations=observations,
            proves_board_support=False))
    stale_routes=[dict(previous_nv_row=previous,**select(36275,previous)) for previous in (4,22)]
    assert [r['nv_row'] for r in stale_routes]==[4,22]
    assert all(r['raw_band_id']==34 for r in stale_routes)
    fixed_anchors=[]
    for channel,expected,selector,nv_row in ((300,21400000,0,0),(38000,25950000,13,11),
        (38450,19000000,14,12),(38950,23300000,15,22),(40640,25950000,16,23)):
        result=select(channel)
        assert compiled_anchor(channel)==result['frequency_raw']==expected
        assert result['selector']==selector and result['nv_row']==nv_row
        fixed_anchors.append(dict(channel=channel,**result))
    if 7 in cp_modules.get('rf_profiles',[]):
        for channel,expected,selector,nv_row in ((3100,26550000,5,5),(5925,8675000,4,4),
            (6075,8825000,4,4),(8865,8765000,4,4)):
            result=select(channel)
            assert compiled_anchor(channel)==result['frequency_raw']==expected
            assert result['selector']==selector and result['nv_row']==nv_row
            fixed_anchors.append(dict(channel=channel,**result))
    # Actual standalone table-rewrite interval has no external calls and
    # initializes its own registers. Stop at its original exclusive end.
    update=0x801d8ca6;update_end=0x801d8da2
    band41=[]
    default_flag=struct.unpack_from('<H',rfnv,0x52+4*23)[0]
    for flag,low,high,first in ((100,40240,41240,25550000),
                               (120,40040,41240,25350000),(140,40040,41440,25350000)):
        machine.mem_write(TABLE-54,table_image)
        machine.mem_write(RFNV+0x52+4*23,struct.pack('<H',flag))
        machine.reg_write(UC_ARM_REG_SP,0x80eff000)
        machine.emu_start(update|1,update_end,count=10000)
        assert machine.reg_read(UC_ARM_REG_PC)==update_end
        actual_low=struct.unpack('<H',machine.mem_read(TABLE+46,2))[0]
        actual_high=struct.unpack('<H',machine.mem_read(TABLE+54+46,2))[0]
        assert (actual_low,actual_high)==(low,high)
        observations=[dict(channel=channel,**select(channel)) for channel in (low,(low+high)//2,high)]
        assert all(r['nv_row']==23 and r['selector']==16 and r['raw_band_id']==41 for r in observations)
        assert observations[0]['frequency_raw']==first
        assert observations[-1]['frequency_raw']==first+(high-low)*1000
        assert select(40640)['frequency_raw']==25950000 and guarded_row(40640)==24
        assert all(guarded_row(r['channel'])==24 for r in observations)
        assert guarded_row(low-1)==0 and guarded_row(high+1)==0
        band41.append(dict(flag=flag,channel_first=low,channel_last=high,
            first_center_hz=first*100,last_center_hz=(first+(high-low)*1000)*100,observations=observations))
    # Missing/moved NV must be checked anew on every native initialization.
    machine.mem_write(RFNV+0x20+2*2,b'\0\0')
    assert guarded_row(1575)==0
    machine.mem_write(RFNV+0x20+2*1,struct.pack('<H',3))
    assert guarded_row(1575)==2 and select(1575)['nv_row']==1
    machine.mem_write(RFNV,bytes(rfnv))
    if args.runtime_snapshot:
        runtime_checks=check_runtime()
    report=dict(status='passed',device_accessed=False,hardware_tested=False,
        scope='CP BIN rf_get_freq native route selection at low/mid/high for all27 initial rows with SDK NV, plus optional retained runtime layout; unsigned division helper stubbed, no physical RF proof',
        entry=hex(ENTRY),entry_bytes=744,entry_sha256=hashlib.sha256(blob[ENTRY-BASE:ENTRY-BASE+744]).hexdigest(),
        info_address=hex(info_base),integer_division_calls=division_calls,
        sdk_nv_bands=sdk_bands,rows=rows,
        b34_missing_nv_keeps_previous_row=stale_routes,
        compiled_anchors_match_native=fixed_anchors,
        runtime_snapshot_checks=runtime_checks,
        compiled_guard=dict(resident=cp_modules['resident'],elf=resident_elf.relative_to(ROOT).as_posix(),
            entry=hex(guard),all_initial_rows_match_native_nv_resolution=True,
            post_nv_b41_boundaries_checked=True,missing_and_moved_nv_checked=True),
        band41_default_nv_flag=default_flag,band41_native_nv_table_updates=band41,
        table_update_interval=dict(start=hex(update),end_exclusive=hex(update_end),
            sha256=hashlib.sha256(blob[update-BASE:update_end-BASE]).hexdigest()),
        dependencies={p.relative_to(ROOT).as_posix():digest(p) for p in (Path(__file__),cp,nv_path,elf_path,inventory_path,
            ROOT/'firmware/rf_rebuild/rfad_control.c',ROOT/'firmware/capture/rxcapt_profile_nv.h',
            ROOT/'firmware/capture/rf_terminal_rx.c',ROOT/'firmware/capture/rxcapt_profile.c',
            ROOT/'firmware/capture/rxcapt_profile.h',cp_build,resident,resident_elf,*runtime_inputs)})
    path=args.output.resolve()
    if not path.is_relative_to(ROOT/'records') or not path.parent.is_dir():
        raise ValueError('output must be inside an existing records directory')
    path.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=report['status'],info_address=report['info_address'],
        sdk_nv_bands=report['sdk_nv_bands'],routes=[dict(id=r['raw_band_id'],nv_match=r['sdk_nv_match'],
        nv_row=r['observations'][0]['nv_row'],selector=r['observations'][0]['selector'],port=r['observations'][0]['rx_port']) for r in rows]),indent=2))

if __name__=='__main__':main()
