"""Small PAC reader/replacer for service firmware builds, without CP repacking."""
import struct

HEADER = struct.Struct('<48sI512s512s7I200s3I800sI2H')
ENTRY = struct.Struct('<I512s512s512s6I5I996s')


def crc16(data):
    table = []
    for value in range(256):
        for _ in range(8):
            value = (value >> 1) ^ (0xa001 if value & 1 else 0)
        table.append(value)
    crc = 0
    for value in data:
        crc = (crc >> 8) ^ table[(crc ^ value) & 255]
    return crc


def entries(data):
    header = HEADER.unpack_from(data)
    if header[1] != len(data) or header[4] > 1024 or header[5]+header[4]*ENTRY.size > len(data):
        raise ValueError('invalid PAC size/table')
    if crc16(data[:HEADER.size-4]) != header[-2] or crc16(data[HEADER.size:]) != header[-1]:
        raise ValueError('invalid PAC CRC')
    result = {}
    for index in range(header[4]):
        at = header[5]+index*ENTRY.size
        row = list(ENTRY.unpack_from(data, at))
        if not row[4]:
            continue
        name = row[2].decode('utf-16le').split('\0', 1)[0]
        if not name or name in result or row[7]+row[4] > len(data):
            raise ValueError('invalid PAC payload')
        result[name] = dict(table_offset=at, row=row, data=data[row[7]:row[7]+row[4]])
    return result


def replace(data, replacements):
    before = entries(data)
    if set(replacements)-before.keys():
        raise ValueError('replacement entry missing')
    result = bytearray(data)
    # Descending replacement offsets keep unprocessed original locations valid.
    for name in sorted(replacements, key=lambda n:before[n]['row'][7], reverse=True):
        current = entries(result)
        target = current[name]['row']
        offset, size = target[7], target[4]
        blob = replacements[name]
        delta = len(blob)-size
        result[offset:offset+size] = blob
        for other, record in current.items():
            row = record['row']
            if other == name:
                row[4] = len(blob)
            elif row[7] >= offset+size:
                row[7] += delta
            elif row[7] < offset+size and row[7]+row[4] > offset:
                raise ValueError('overlapping PAC payloads')
            ENTRY.pack_into(result, record['table_offset'], *row)
        struct.pack_into('<I', result, 48, len(result))
        struct.pack_into('<HH', result, HEADER.size-4,
                         crc16(result[:HEADER.size-4]), crc16(result[HEADER.size:]))
    after = entries(result)
    if set(after) != set(before) or any(after[n]['data'] != replacements.get(n, r['data']) for n,r in before.items()):
        raise ValueError('PAC replacement readback differs')
    return bytes(result)
