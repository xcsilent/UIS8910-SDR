"""Offline8955 RX table arithmetic vs original UIS8910 RF coefficient code.

No hardware, no frequency-range or PLL-lock claim. The factor9 contexts are
synthetic; they do not assert the installed8910 calibration selects9.
"""
import argparse,hashlib,json,re,sys,struct,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'work/host-test-deps'))
from verify_rf_frequency_native import Native
from capstone import Cs,CS_ARCH_RISCV,CS_MODE_RISCV32,CS_MODE_RISCVC
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_MEM_READ
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from elftools.elf.elffile import ELFFile
from elftools.dwarf.dwarf_expr import DWARFExprParser
from verify_rf_mode_native import X

def sdk_field_semantics(axf):
    """Positive type definitions; similar PLL names are not address mappings."""
    names={};other={};source=None;block_size=None;fem_offset=None
    with axf.open('rb') as stream:
        elf=ELFFile(stream);dwarf=elf.get_dwarf_info();parser=DWARFExprParser(dwarf.structs)
        for cu in dwarf.iter_CUs():
            attr=cu.get_top_DIE().attributes.get('DW_AT_name')
            path=attr.value.decode(errors='replace') if attr else ''
            if not path.endswith(('rf_lte_nv.h','hal_lps.h','calib_pc_msg.h')):continue
            for die in cu.iter_DIEs():
                attr=die.attributes.get('DW_AT_name');name=attr.value.decode(errors='replace') if attr else ''
                if name=='rf_lte_mdll_dyn_tag' and not names:
                    source=path;block_size=die.attributes['DW_AT_byte_size'].value
                    for child in die.iter_children():
                        a=child.attributes;attr=a.get('DW_AT_name');member=attr.value.decode(errors='replace') if attr else ''
                        if member not in ('mdll_en','reserve','mdll'):continue
                        expression=parser.parse_expr(a['DW_AT_data_member_location'].value)
                        assert len(expression)==1 and expression[0].op_name=='DW_OP_plus_uconst'
                        names[member]=expression[0].args[0]
                if name=='lte_mdll' and fem_offset is None:
                    parent=die.get_parent();pn=parent.attributes.get('DW_AT_name')
                    if pn and pn.value==b'rf_lte_nv_fem_mipi_tag':
                        expression=parser.parse_expr(die.attributes['DW_AT_data_member_location'].value)
                        fem_offset=expression[0].args[0]
                if name=='LTE_NV_TYPE_FAST_PLLLOCK' and name not in other:
                    other[name]=dict(value=die.attributes['DW_AT_const_value'].value,kind=die.tag,source=path,
                        scope='calibration message type identifier; not a bit mask or RF register address')
                if name in ('puWaitPllLock','puRfClkReadyStateToPllClockReadyState') and name not in other:
                    other[name]=dict(bit_size=die.attributes['DW_AT_bit_size'].value,
                        bit_offset=die.attributes['DW_AT_bit_offset'].value,source=path,
                        scope='HAL low-power system timing; not mapped to RF3037c')
    assert names=={'mdll_en':0,'reserve':2,'mdll':4} and block_size==52
    assert fem_offset==0xfc4 and 0x2ac+fem_offset==0x1270
    assert other['LTE_NV_TYPE_FAST_PLLLOCK']['value']==2
    # These macros coexist with older addresses, so only independently verified
    # transport masks are confirmed. Legacy address names are retained, not used.
    raw=axf.read_bytes();macro_names=('RDA8910_ADDR_MASK','RDA8910_ADDR_OFFSET','RDA8910_DATA_MASK',
        'RDA8910_DATA_OFFSET','RDA8910_PAGE_OFFSET','RDA8910_PAGE_REG_ADDR','RDA8910_SYS_CTRL_REG','RDA8910_FREQ_CTRL_MDLL_REG')
    macros={name:sorted(set(x.decode() for x in re.findall(name.encode()+rb' [^\x00\r\n]{1,64}',raw))) for name in macro_names}
    return dict(mdll_type='rf_lte_mdll_dyn_tag',source=source,bytes=block_size,member_offsets=names,
        fem_member_offset=hex(fem_offset),nv_fem_base='0x2ac',nv_mdll_enable_offset='0x1270',
        nv_mdll_values_offset='0x1274',unrelated_pll_names=other,retained_macros=macros,
        formal_rf_register_bit_names_present=False,rxpll_lock_address_mapping_proved=False)

class ConfigNative(Native):
    def observe(self,cpu,access,address,size,value,context):
        if 0x7e00<=address<0x7e20:return
        return super().observe(cpu,access,address,size,value,context)

def config_transfer(cp,image,rules):
    """Original retained CP BIN slice, not ELF VMA or rewritten copier."""
    blob=cp.read_bytes();base=0x801ab000;entry=0x801b9ae0;stop=0x801b9ae8
    code=blob[entry-base:stop-base]
    # LDR r1,[r5,#8]; LDRH r0,[r1,#0x176]; STRH r0,[r4,#0x30].
    assert code==bytes.fromhex('a968b1f876012086'),code.hex()
    assert struct.unpack_from('<I',blob,0xee78)[0]==0x50007e00
    assert struct.unpack_from('<I',blob,0xee80)[0]==0x804713d8
    cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    cpu.mem_map(0x801b9000,0x1000);cpu.mem_write(entry,code)
    cpu.mem_map(0x200000,0x20000);cpu.mem_map(0x50009000,0x2000)
    cpu.mem_write(0x200008,struct.pack('<I',0x210000));cases=[]
    # RF publishes its local configuration pointer in the shared header.
    published=ConfigNative(image,rules);published.run(0x874,{0x8a6})
    pointer=struct.unpack('<I',published.cpu.mem_read(0x7e18,4))[0];assert pointer==0x96b0
    for value in (0,1,0x40,0x4000,0x7fff,0x8000,0x8041,0xffff):
        cpu.mem_write(0x210176,struct.pack('<H',value))
        cpu.reg_write(UC_ARM_REG_R4,0x500096b0);cpu.reg_write(UC_ARM_REG_R5,0x200000)
        cpu.emu_start(entry|1,stop,count=20);assert cpu.reg_read(UC_ARM_REG_PC)==stop
        copied=struct.unpack('<H',cpu.mem_read(0x500096e0,2))[0];assert copied==value
        native=Native(image,rules);native.put16(0x96e0,copied);native.run(0x1e58,{0x1e88})
        flag=struct.unpack('<H',native.cpu.mem_read(0xb464,2))[0];assert flag==value>>15
        cases.append(dict(nv_halfword=value,rf_config_halfword=copied,rf_poll_flag=flag))
    return dict(cp_bin_entry=hex(entry),cp_bin_offset=hex(entry-base),instruction_bytes=code.hex(),
        nv_pointer_table='0x804713d8',nv_pointer_member_offset=8,source_nv_offset='0x176',
        rf_header='0x7e00',published_pointer_offset='0x18',published_local_config_pointer=hex(pointer),
        cp_destination='0x500096e0',rf_destination='0x96e0',cases=cases,
        address_scope='retained CP BIN and RF local software views, not live hardware reads')

def factor_table_transfer(cp,image,rules,frontend_snapshot=None):
    blob=cp.read_bytes();base=0x801ab000
    copier,source,destination,length=struct.unpack_from('<4I',blob,0x2bc4dc)
    assert (copier,source,destination,length)==(0x8025b8e8,0x804750bc,0x804000,0x29724)
    assert struct.unpack_from('<I',blob,0x802e9158-base)[0]==0x804388
    cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    cpu.mem_map(0x801b9000,0x1000);cpu.mem_write(0x801b9aba,blob[0xeaba:0xeacc])
    cpu.mem_map(0x802e9000,0x1000);cpu.mem_write(0x802e9154,blob[0x802e9154-base:0x802e915c-base])
    # Execute the actual scatter-loaded ARM memcpy helper as well as its caller.
    cpu.mem_map(destination,0x30000);cpu.mem_write(destination,blob[source-base:source-base+length])
    cpu.mem_map(0x200000,0x20000);cpu.mem_map(0x50009000,0x3000)
    cpu.mem_write(0x200008,struct.pack('<I',0x210000));cases=[]
    for enabled in (0,1,2,0xffff):
        for factor in (7,8,9,10):
            nv=bytearray((i*37+11)&255 for i in range(0x4000))
            struct.pack_into('<H',nv,0x1270,enabled);struct.pack_into('<H',nv,0x1274,factor)
            cpu.mem_write(0x210000,bytes(nv));cpu.reg_write(UC_ARM_REG_R4,0x500096b0)
            cpu.reg_write(UC_ARM_REG_R5,0x200000);cpu.reg_write(UC_ARM_REG_SP,0x21f000)
            cpu.emu_start(0x801b9aba|1,0x801b9acc,count=10000)
            assert cpu.reg_read(UC_ARM_REG_PC)==0x801b9acc
            copied=bytes(cpu.mem_read(0x5000974c,0x117c));assert copied==bytes(nv[0x2ac:0x1428])
            native=Native(image,rules);native.cpu.mem_write(0x974c,copied)
            # Selector-to-NV-row mapping is synthetic0, not an assertion about a band.
            native.put16(0x940c+2*6,0)
            native.cpu.reg_write(X[10],23300000);native.cpu.reg_write(X[11],0x102000);native.cpu.reg_write(X[12],6)
            native.run(0x37f0,{0xf000});values=struct.unpack('<4H',native.cpu.mem_read(0x102000,8))
            selected=factor if enabled==1 else 7
            assert values[3]==selected
            assert (values[1]<<16)|values[2]==23300000*(1<<28)//(260000*selected)
            cases.append(dict(nv_enable=enabled,nv_factor=factor,selected_factor=values[3]))
    board=None
    if frontend_snapshot is not None:
        snapshot=json.loads(frontend_snapshot.read_text(encoding='utf-8'))
        assert snapshot['status']=='passed' and snapshot['stable_repeated_reads']
        artifact=snapshot['artifacts'][0];nv_path=ROOT/artifact['path'];nv=nv_path.read_bytes()
        assert len(nv)==16384 and hashlib.sha256(nv).hexdigest()==artifact['sha256']
        enabled=struct.unpack_from('<H',nv,0x1270)[0]
        # This proof intentionally covers the observed bypass, not an invented
        # mapping for enabled dynamic MDLL. Refuse a changed board state.
        if enabled==1:raise ValueError('dynamic MDLL enabled: actual selector lookup mapping needs separate evidence')
        cpu.mem_write(0x210000,nv);cpu.reg_write(UC_ARM_REG_R4,0x500096b0)
        cpu.reg_write(UC_ARM_REG_R5,0x200000);cpu.reg_write(UC_ARM_REG_SP,0x21f000)
        cpu.emu_start(0x801b9aba|1,0x801b9acc,count=10000)
        assert cpu.reg_read(UC_ARM_REG_PC)==0x801b9acc
        copied=bytes(cpu.mem_read(0x5000974c,0x117c));assert copied==nv[0x2ac:0x1428]
        rows=[]
        for band,selector in ((3,2),(5,4),(8,6),(40,15)):
            nv_row=next(i for i in range(24) if struct.unpack_from('<H',nv,0x20+2*i)[0]==band)
            stored=struct.unpack_from('<H',nv,0x1274+2*nv_row)[0]
            for working in (6757000,7007000,8815700,9907000,20007000):
                native=Native(image,rules);native.cpu.mem_write(0x974c,copied)
                # Deliberately invalid indices must not be consumed while
                # enable!=1. Hook all reads to prove the bypass positively.
                native.put16(0x940c+2*selector,65535);reads=[]
                native.cpu.hook_add(UC_HOOK_MEM_READ,lambda c,a,p,n,v,x:reads.append((p,n)))
                native.cpu.reg_write(X[10],working);native.cpu.reg_write(X[11],0x102000);native.cpu.reg_write(X[12],selector)
                native.run(0x37f0,{0xf000})
                values=struct.unpack('<4H',native.cpu.mem_read(0x102000,8))
                assert (0xa710,2) in reads and (0x940c+2*selector,2) not in reads
                assert not any(0xa714<=address<0xa744 for address,size in reads)
                effective=working*2 if working<10000000 else working
                expected=(effective*(1<<28)//1820000)&0xffffffff
                assert values[3]==7 and (values[1]<<16)|values[2]==expected
                rows.append(dict(band=band,selector=selector,nv_row=nv_row,stored_nv_factor=stored,
                    working_raw=working,effective_arithmetic_raw=effective,selected_factor=values[3],
                    selector_lookup_read=False,dynamic_factor_table_read=False,coefficient_words=list(values)))
        board=dict(snapshot=frontend_snapshot.relative_to(ROOT).as_posix(),epoch=snapshot['epoch'],
            observed_nv_enable=enabled,cases=rows,
            scope='Captured board NV copied by original CP code, then original RF arithmetic under synthetic working inputs; no live RF RAM readback or physical PLL/lock proof.',
            actual_enabled_selector_mapping_verified=False,
            conclusion='enable!=1 bypasses both lookup tables; stored per-row8 does not select factor8. Default factor7 applies regardless of selector lookup content.')
    return dict(cp_bin_entry='0x801b9aba',cp_bin_return='0x801b9acc',
        source_nv_offset='0x2ac',destination_local='0x974c',bytes_copied=0x117c,
        enable_mapping=dict(nv='0x1270',rf_local='0xa710'),
        factor_table_mapping=dict(nv='0x1274',rf_local='0xa714'),
        scatter_loaded_memcpy='0x804388',actual_copy_and_coefficient_code_executed=True,
        selector_lookup_is_synthetic=True,cases=cases,retained_board_bypass=board)

def actual_8955_rx(driver,build):
    """Compile the verbatim xcvSetArfcn body, not a rewritten model."""
    text=driver.read_text();start=text.index('VOID RFD_FUNC_INTERNAL xcvSetArfcn (')
    opening=text.index('{',start);depth=1;end=opening+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    body=text[start:end]
    prefix='''typedef unsigned int UINT32; typedef unsigned short UINT16;
typedef int RFD_RFDIR_T; typedef int GSM_RFBAND_T;
#define VOID void
#define RFD_FUNC_INTERNAL
#define RFD_DIR_RX 0
#define RFD_DIR_TX 1
#define GSM_BAND_GSM850 0
#define GSM_BAND_GSM900 1
#define GSM_BAND_DCS1800 2
#define GSM_BAND_PCS1900 3
#define HAL_SYS_CHIP_METAL_ID_U02 2
#define RDA6220_ARFCN_MASK 0x3ff
#define XCV_PLL_SDM_MODE
unsigned int g_xcvChipId; unsigned int g_XcvRxSdmMode;
struct { unsigned int freqCtrl; } g_xcvCmdCtx;
'''
    suffix='''
unsigned int probe(unsigned int band,unsigned int arfcn,unsigned int metal) {
g_xcvChipId=metal; g_XcvRxSdmMode=0x20;
xcvSetArfcn(RFD_DIR_RX,band,(UINT16)arfcn);
return g_xcvCmdCtx.freqCtrl | (g_XcvRxSdmMode<<24);
}
'''
    source=build/'8955_rx.c';source.write_text(prefix+body+suffix)
    gcc=ROOT/'inputs/repositories/rda8910-csdk-hotelec/prebuilts/win32/gcc-arm-none-eabi/bin/arm-none-eabi-gcc.exe'
    output=build/'8955_rx.elf'
    subprocess.run([str(gcc),'-mcpu=cortex-a5','-mthumb','-Os','-ffreestanding','-fno-builtin','-nostdlib',
        '-Wl,--build-id=none','-Wl,-Ttext=0x100000','-Wl,-e,probe',str(source),'-o',str(output)],check=True)
    cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB);cpu.mem_map(0x100000,0x20000)
    with output.open('rb') as stream:
        elf=ELFFile(stream)
        for segment in elf.iter_segments():
            if segment['p_type']=='PT_LOAD':cpu.mem_write(segment['p_vaddr'],segment.data())
        entry=next(s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name=='probe')
    cases=0;exceptions=[]
    channels=[range(128,252),list(range(125))+list(range(975,1024)),range(512,886),range(512,811)]
    for band,values in enumerate(channels):
        for arfcn in values:
            for metal in (1,2):
                cpu.reg_write(UC_ARM_REG_SP,0x11f000);cpu.reg_write(UC_ARM_REG_LR,0x110001)
                for register,value in [(UC_ARM_REG_R0,band),(UC_ARM_REG_R1,arfcn),(UC_ARM_REG_R2,metal)]:cpu.reg_write(register,value)
                cpu.emu_start(entry|1,0x110000,count=1000)
                assert cpu.reg_read(UC_ARM_REG_PC)==0x110000
                actual=cpu.reg_read(UC_ARM_REG_R0);divider=8 if band==3 and arfcn==611 else 7
                expected=(0x14000 if divider==8 else 0x10000)|(band<<12)|0x800|arfcn
                assert actual==expected|((divider==8)<<24),(band,arfcn,metal,actual)
                cases+=1
                if divider!=7:exceptions.append(dict(band='PCS1900',arfcn=arfcn,metal=metal,divider=divider,sdm_mode=1))
    return dict(compiled_source='verbatim xcvSetArfcn body with scalar type/global stubs; RX invocation',
        cases=cases,default_divider=7,exceptions=exceptions,physical_hardware_tested=False)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frontend-snapshot',type=Path,help='saved stable runtime frontend NV; no hardware access')
    args=parser.parse_args()
    base=ROOT/'inputs/reference-source/predecessors/rda8955-w17.44-idh/soft'
    header=base/'platform/edrv/rfd/xcv_8955/src/drv_xcv.h'
    text=header.read_text();defs=ROOT/'inputs/reference-source/riscv-pulp-legacy/riscv-opc.h'
    macros={k:int(v,16) for k,v in re.findall(r'#define\s+((?:MATCH|MASK)_\w+)\s+(0x[0-9a-fA-F]+)',defs.read_text())}
    rules=[(n,macros['MATCH_'+n],macros['MASK_'+m]) for n,m in [('EXTHZ','PALUS'),('BCLR','PALU2'),('BNEM1','BNEM1')]]
    source=ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/modemgen/cat1_UIS8915DM_BB_RF_SS_NoVolte_cus/cpbin/riscV.bin'
    image=source.read_bytes()
    cp=source.with_name('cp.bin')
    axf=source.with_name('cp.axf');semantics=sdk_field_semantics(axf)
    transfer=config_transfer(cp,image,rules)
    factor_transfer=factor_table_transfer(cp,image,rules,args.frontend_snapshot.resolve() if args.frontend_snapshot else None)
    retained_path=ROOT/'records/rf/runtime-frontend-current.rfnv.bin'
    retained=retained_path.read_bytes()
    retained_config=dict(artifact=retained_path.relative_to(ROOT).as_posix(),point_in_time_only=True,
        live_device_query=False,poll_source_word=hex(struct.unpack_from('<H',retained,0x176)[0]),
        table_enable=struct.unpack_from('<H',retained,0x1270)[0],
        factor_rows=list(struct.unpack_from('<24H',retained,0x1274)))
    predecessor_header=ROOT/'inputs/reference-source/predecessors/rda8810/modem/modem-dualmode-2g/soft/platform/chip/regs/8810/include/tranceiver.h'
    predecessor_driver=ROOT/'inputs/reference-source/predecessors/rda8810/modem/modem-dualmode-2g/soft/platform/edrv/rfd/xcv_8810/src/drv_xcv.c'
    alternative_header=ROOT/'inputs/reference-source/predecessors/rda8810/modem/modem-dualmode-2g/soft/platform/chip/regs/8850e/include/tranceiver.h'
    assert '#define TRANCEIVER_MDLL_DIV_NUM(n) (((n)&15)<<12)' in predecessor_header.read_text()
    assert 'reg_bch = 0x7ca8;' in predecessor_driver.read_text()
    assert '#define TRANCEIVER_RXPLL_LOCK      (1<<0)' in alternative_header.read_text()
    predecessor_semantics=dict(rda8810_mdll_div_num_bits=[12,15],rda8810_rx_example=dict(divider=7,register='0xbc',value='0x7ca8'),
        rda8850e_rxpll_lock_bit=0,rda8955_header_rxpll_lock_bit=17,
        scope='positive predecessor field names; shifts differ, no numeric transplant to8910')
    build=ROOT/'work/rf-pll-reference';build.mkdir(exist_ok=True)
    driver=base/'platform/edrv/rfd/xcv_8955/src/drv_xcv.c'
    actual_rx=actual_8955_rx(driver,build)
    groups=[('GSM850_RX',2,[869200000+i*200000 for i in range(124)]),
        ('GSM900_RX',2,[935000000+i*200000 for i in range(125)]+[925200000+i*200000 for i in range(49)]),
        ('DCS_RX',1,[1805200000+i*200000 for i in range(374)]),
        ('PCS_RX',1,[1930200000+i*200000 for i in range(299)])]
    tables=[];native_cases=[]
    for name,multiplier,frequencies in groups:
        section=text.split('#define '+name+'_FREQUENCY')[1].split('#define')[0]
        entries=[tuple(int(v,16) for v in m) for m in re.findall(r'\{\s*(0x[0-9a-f]+)\s*,\s*(0x[0-9a-f]+)\s*\}',section)]
        assert len(entries)==len(frequencies)
        for (high,low),hz in zip(entries,frequencies):
            assert high<=0x3fff and low<=0x3ffff
            assert (high<<18)|low == hz*multiplier*(1<<28)//234000000
        for index in sorted({0,1,len(entries)//2,len(entries)-1}):
            hz=frequencies[index];values=Native(image,rules).coefficients(hz//100,6,1,9)
            actual=(values[1]<<16)|values[2];expected=(entries[index][0]<<18)|entries[index][1]
            assert actual==expected and values[3]==9
            native_cases.append(dict(table=name,index=index,working_hz=hz,q28=actual,factor=values[3]))
        tables.append(dict(name=name,entries=len(entries),minimum_hz=min(frequencies),maximum_hz=max(frequencies),
            multiplier=multiplier,denominator_hz=234000000,all_entries_exact=True))
    wrap=[]
    for hz in (2911999900,2912000000,2912000100):
        values=Native(image,rules).coefficients(hz//100,6,0,7)
        actual=(values[1]<<16)|values[2];wide=(hz//100)*(1<<28)//1820000
        assert actual==wide&0xffffffff
        wrap.append(dict(working_hz=hz,wide_coefficient=wide,stored_u32=actual,
            warning='coefficient representation wrap only; not physical tuning/lock limit'))
    factor_registers=[]
    for entry,stop in [(0x4b54,0x4b78),(0x6d88,0x6dac)]:
        for factor in (7,8,9,10):
            native=Native(image,rules);native.put16(0xb526,factor);native.run(entry,{stop})
            assert native.writes==[(0x32a00,0x9007|((factor-7)<<6),2)]
            factor_registers.append(dict(entry=hex(entry),factor=factor,address='0x32a00',value=hex(native.writes[0][1])))
    bank_controls=[]
    for bank,entry,stop,field,pointer_reg in [('A',0x4760,0x47a6,0x302e0,12),('B',0x4fc4,0x500a,0x302c0,13)]:
        for factor in (7,8,9,10):
            for first in (0,0xffff,0xaaaa,0x5555):
                for second in (0,0xffff,0xaaaa,0x5555):
                    native=Native(image,rules);native.cpu.reg_write(X[8],0x30000)
                    native.cpu.reg_write(X[pointer_reg],0xb520);native.put16(0xb526,factor)
                    native.put16(0x30410,first);native.put16(field,second)
                    native.run(entry,{stop})
                    expected=[(0x30410,(first&0x87ff)|(factor<<11),2),(field,(second&0xfffc)|(factor-7),2)]
                    assert native.writes==expected,(bank,factor,native.writes,expected)
                    bank_controls.append(dict(bank=bank,factor=factor,before=[first,second],after=[v[1] for v in expected]))
    flags=[]
    for config in (0,0x40,0x7fff,0x8000,0x8040,0xffff):
        native=Native(image,rules);native.put16(0x96e0,config);native.run(0x1e58,{0x1e88})
        observed=struct.unpack('<H',native.cpu.mem_read(0xb464,2))[0]
        assert observed==config>>15
        flags.append(dict(source_address='0x96e0',source_value=hex(config),flag_address='0xb464',flag_value=observed))
    polls=[]
    for entry,stop in [(0x4a78,0x4a84),(0x631c,0x6328),(0x6578,0x6584),(0x6bd8,0x6be4)]:
        for initial in (0,0x7ff,0x800,0xffff):
            native=Native(image,rules);native.cpu.reg_write(X[13],0x3037c);native.cpu.reg_write(X[14],0x800)
            native.put16(0x3037c,initial);reads=[0]
            def read_hook(cpu,access,address,size,value,context):
                if address==0x3037c:
                    reads[0]+=1
                    if reads[0]==3:cpu.mem_write(address,struct.pack('<H',initial|0x800))
            native.cpu.hook_add(UC_HOOK_MEM_READ,read_hook)
            native.run(entry,{stop});assert reads[0]==(1 if initial&0x800 else 3)
            polls.append(dict(entry=hex(entry),initial=hex(initial),reads_until_exit=reads[0],synthetic_ready_set_on_third_read=True))
    # Keep exact instruction bytes and explicit undecoded legacy instructions.
    decoder=Cs(CS_ARCH_RISCV,CS_MODE_RISCV32|CS_MODE_RISCVC);instructions=[];pc=0x6554
    while pc<0x6586:
        size=2 if image[pc]&3!=3 else 4;raw=image[pc:pc+size];decoded=list(decoder.disasm(raw,pc))
        instructions.append(dict(address=hex(pc),bytes=raw.hex(),instruction=(decoded[0].mnemonic+' '+decoded[0].op_str) if decoded else 'legacy extension; see pinned decoder'))
        pc+=size
    assert image[0x6578:0x657c]==bytes.fromhex('83d70600')
    dependencies=[Path(__file__),header,source,cp,axf,defs,retained_path,predecessor_header,predecessor_driver,alternative_header,ROOT/'tools/verify/verify_rf_frequency_native.py',ROOT/'tools/verify/verify_rf_mode_native.py',
        base/'platform/chip/regs/8955/include/xcv.h',base/'platform/chip/boot/src/boot_xcv.c',
        base/'platform/edrv/rfd/xcv_8955/src/drv_xcv.c',base/'env/link/spi_reg_debug.ld']
    if args.frontend_snapshot:
        snapshot=args.frontend_snapshot.resolve()
        dependencies.extend([snapshot,ROOT/json.loads(snapshot.read_text(encoding='utf-8'))['artifacts'][0]['path']])
    report=dict(status='passed',device_accessed=False,hardware_tested=False,scope='source table exact arithmetic and original RF function under synthetic contexts; optional captured-board NV bypass proof',
        table_cases=sum(t['entries'] for t in tables),tables=tables,native_cases=native_cases,
        actual_8955_rx=actual_rx,native_factor_register_cases=factor_registers,
        cp_nv_to_rf_poll_config=transfer,native_ab_factor_control_cases=bank_controls,
        cp_nv_to_rf_factor_table=factor_transfer,
        retained_nv_observation=retained_config,
        sdk_field_semantics=semantics,
        predecessor_hardware_semantics=predecessor_semantics,
        native_poll_enable_source=flags,native_poll_loop_cases=polls,
        factor7_wrap_cases=wrap,ready_poll_instructions=instructions,
        original_native_entry='0x37f0',modeled_extensions=['EXTHZ','BCLR','BNEM1'],
        physical_pll_range_proven=False,uis8910_rxpll_lock_identified=False,
        dependencies={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies})
    out=ROOT/'records/rf';out.mkdir(exist_ok=True)
    (out/'pll-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status='passed',table_cases=report['table_cases'],native_cases=len(native_cases),wrap_cases=len(wrap),
        compiled_8955_rx_cases=actual_rx['cases'],factor_register_cases=len(factor_registers),
        poll_enable_cases=len(flags),poll_loop_cases=len(polls),cp_rf_config_transfer_cases=len(transfer['cases']),
        ab_factor_control_cases=len(bank_controls),cp_rf_factor_transfer_cases=len(factor_transfer['cases']))))

if __name__=='__main__':main()
