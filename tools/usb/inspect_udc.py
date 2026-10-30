"""Extract the SDK UDC ABI and compare function bytes with the installed PAC.

Offline only. SDK addresses are usable in a PAC only when the code comparison
passes; the report does not imply that a live endpoint or DMA buffer is ready.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[2]
PAC_HEADER = struct.Struct('<48sI512s512s7I200s3I800sI2H')
PAC_ENTRY = struct.Struct('<I512s512s512s6I5I996s')


def text(die, attribute='DW_AT_name'):
    item = die.attributes.get(attribute)
    if item is None:
        for link in ('DW_AT_abstract_origin', 'DW_AT_specification'):
            if link in die.attributes:
                return text(die.get_DIE_from_attribute(link), attribute)
        return ''
    return item.value.decode('utf-8', errors='replace') if isinstance(item.value, bytes) else item.value


def prototype(die):
    for link in ('DW_AT_abstract_origin', 'DW_AT_specification'):
        if link in die.attributes:
            return prototype(die.get_DIE_from_attribute(link))
    return die


def type_name(die, seen=()):
    if die is None:
        return 'void'
    if die.offset in seen:
        return text(die) or die.tag
    seen = seen + (die.offset,)
    name = text(die)
    if name:
        return name
    target = die.get_DIE_from_attribute('DW_AT_type') if 'DW_AT_type' in die.attributes else None
    if die.tag == 'DW_TAG_pointer_type':
        return type_name(target, seen)+'*'
    if die.tag == 'DW_TAG_subroutine_type':
        arguments = [type_name(c.get_DIE_from_attribute('DW_AT_type'), seen)
                     for c in die.iter_children() if c.tag == 'DW_TAG_formal_parameter'
                     and 'DW_AT_type' in c.attributes]
        return type_name(target, seen)+'('+', '.join(arguments)+')'
    return type_name(target, seen) if target is not None else die.tag


def describe(die, depth=0, seen=()):
    if die is None:
        return {'name': 'void'}
    result = {'name': text(die), 'tag': die.tag, 'die_offset': hex(die.offset)}
    for attribute, key in [('DW_AT_byte_size', 'bytes'), ('DW_AT_encoding', 'encoding')]:
        if attribute in die.attributes:
            result[key] = die.attributes[attribute].value
    if depth >= 2 or die.offset in seen:
        return result
    seen = seen + (die.offset,)
    if 'DW_AT_type' in die.attributes:
        target = die.get_DIE_from_attribute('DW_AT_type')
        result['type'] = type_name(target)
        if die.tag == 'DW_TAG_typedef' and target.tag in ('DW_TAG_structure_type', 'DW_TAG_union_type'):
            result['definition'] = describe(target, depth+1, seen)
    if die.tag in ('DW_TAG_structure_type', 'DW_TAG_union_type'):
        result['members'] = []
        for child in die.iter_children():
            if child.tag != 'DW_TAG_member':
                continue
            member = {'name': text(child)}
            location = child.attributes.get('DW_AT_data_member_location')
            if location is not None:
                member['offset'] = location.value
            for attribute in ('DW_AT_bit_size', 'DW_AT_bit_offset', 'DW_AT_data_bit_offset'):
                if attribute in child.attributes:
                    member[attribute.removeprefix('DW_AT_')] = child.attributes[attribute].value
            if 'DW_AT_type' in child.attributes:
                member['type'] = type_name(child.get_DIE_from_attribute('DW_AT_type'))
            result['members'].append(member)
    if die.tag == 'DW_TAG_subroutine_type':
        result['arguments'] = [type_name(c.get_DIE_from_attribute('DW_AT_type'))
                               for c in die.iter_children() if c.tag == 'DW_TAG_formal_parameter'
                               and 'DW_AT_type' in c.attributes]
    return result


def pac_ap(path):
    raw = path.read_bytes()
    header = PAC_HEADER.unpack_from(raw)
    if header[4] > 1024 or header[5] + header[4]*PAC_ENTRY.size > len(raw):
        raise ValueError('PAC table outside file')
    entries = {}
    for index in range(header[4]):
        row = PAC_ENTRY.unpack_from(raw, header[5]+index*PAC_ENTRY.size)
        name = row[2].decode('utf-16le').split('\0', 1)[0]
        if not row[4]:
            continue
        if row[7]+row[4] > len(raw) or name in entries:
            raise ValueError(f'PAC duplicate name or payload outside file: index={index}, name={name!r}, size={row[4]}, offset={row[7]}')
        entries[name] = raw[row[7]:row[7]+row[4]]
    return entries['8915DM_cat1_CSDK.img']


def inspect(elf_path, pac_path):
    ap = pac_ap(pac_path)
    if struct.unpack_from('>I', ap)[0] != 0x27051956:
        raise ValueError('AP is not a uImage')
    load = struct.unpack_from('>I', ap, 16)[0]
    payload = ap[64:]
    selected = re.compile(r'(?:cops|prvDwc|prvEp|drvDwc|dwc|usbSerial|udcEp|udcGet|udc[A-Z]|createSerialFunc|drvUsb|drvSerial|prvUserial)')
    report = dict(elf=str(elf_path.relative_to(ROOT)), pac=str(pac_path.relative_to(ROOT)),
                  pac_sha256=hashlib.sha256(pac_path.read_bytes()).hexdigest(),
                  ap_sha256=hashlib.sha256(ap).hexdigest(), ap_load_address=hex(load),
                  hardware_tested=False, functions=[], declarations=[], types=[])
    with elf_path.open('rb') as source:
        elf = ELFFile(source)
        symbols = elf.get_section_by_name('.symtab')
        for symbol in symbols.iter_symbols():
            if symbol['st_info']['type'] != 'STT_FUNC' or not selected.match(symbol.name):
                continue
            address = symbol['st_value'] & ~1
            size = symbol['st_size']
            section = elf.get_section(symbol['st_shndx']) if isinstance(symbol['st_shndx'], int) else None
            expected = section.data()[address-section['sh_addr']:address-section['sh_addr']+size] if section else b''
            actual = payload[address-load:address-load+size] if load <= address and address+size <= load+len(payload) else b''
            report['functions'].append(dict(name=symbol.name, address=hex(symbol['st_value']), bytes=size,
                same_address_pac_bytes_match=bool(size and len(expected)==size and actual==expected),
                sdk_prefix=expected[:24].hex(), pac_prefix=actual[:24].hex()))
        for cu in elf.get_dwarf_info().iter_CUs():
            for die in cu.iter_DIEs():
                name = text(die)
                if die.tag == 'DW_TAG_subprogram' and selected.match(name):
                    declaration = prototype(die)
                    arguments = []
                    for child in declaration.iter_children():
                        if child.tag == 'DW_TAG_formal_parameter' and 'DW_AT_type' in child.attributes:
                            arguments.append(dict(name=text(child), type=describe(child.get_DIE_from_attribute('DW_AT_type'))))
                    complete = bool(arguments or 'DW_AT_type' in declaration.attributes or
                                    'DW_AT_prototyped' in declaration.attributes)
                    report['declarations'].append(dict(name=name, arguments=arguments,
                        prototype_available=complete, compilation_unit=text(cu.get_top_DIE()),
                        returns=describe(declaration.get_DIE_from_attribute('DW_AT_type'))
                        if 'DW_AT_type' in declaration.attributes else {'name':'void' if complete else 'unknown'}))
                elif die.tag in ('DW_TAG_typedef', 'DW_TAG_structure_type') and re.match(r'(?:udc|dwc|Dwc|usbSerial|usbEp|usb_ep|usbXfer|usb_xfer|usbString|drvDwc|DrvUsb|cops|composite_|Cops|udevDrv)', name):
                    report['types'].append(describe(die))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    state = json.loads((ROOT/'docs/project-state.json').read_text(encoding='utf-8'))
    report = inspect(ROOT/'inputs/repositories/rda8910-csdk-hotelec/core/iot_SDK_720U_map/CSDK_RDA8910.elf',
                     ROOT/state['installed_firmware']['pac'])
    output = args.output.resolve()
    if not output.is_relative_to(ROOT):
        parser.error('output must be inside project')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(output=str(output.relative_to(ROOT)), ap_load=report['ap_load_address'],
        functions=len(report['functions']), matching_functions=sum(f['same_address_pac_bytes_match'] for f in report['functions']),
        declarations=len(report['declarations']), types=len(report['types'])), indent=2))


if __name__ == '__main__':
    main()
