"""Bounded 500-byte-page modem file replacement without reallocating pages."""
import struct
import zlib

MARKER=b'\xe5\x01\0\0'


def files(image):
    assert len(image)%512==0
    for index in range(len(image)//512):
        page=image[index*512:(index+1)*512]
        if page==b'\xff'*512 or (page[:4]==MARKER and page[4:504]==b'\xff'*500 and page[504:]==bytes(8)):
            continue
        assert page[:4]==MARKER
        flags,number,crc=struct.unpack_from('<HHI',page,504)
        assert flags==1 and number==index and crc==zlib.crc32(page[:508])
    result={};owned=set()
    for at in range(0,len(image),512):
        page=image[at:at+512]
        if page[:8]!=MARKER+b'FILE':continue
        name=page[8:72].split(b'\0')[0].decode('ascii')
        size=struct.unpack_from('<I',page,72)[0]
        assert name and name not in result
        if size<=408:
            ids=[];data=page[100:100+size]
        else:
            count=(size+499)//500
            assert count<=202
            ids=list(struct.unpack_from('<'+'H'*count,page,100))
            assert len(set(ids))==count
            for index in ids:
                assert index<len(image)//512 and index!=at//512 and index not in owned
                assert image[index*512:index*512+4]==MARKER
                owned.add(index)
            data=b''.join(image[index*512+4:index*512+504] for index in ids)[:size]
        assert len(data)==size
        result[name]=dict(data=data,pages=ids,node=at//512)
    assert result
    assert not owned.intersection(row['node'] for row in result.values())
    return result


def replace_file(image,name,payload):
    before=files(image);record=before[name];pages=record['pages']
    assert 408<len(payload)<=len(pages)*500,'replacement exceeds existing page allocation'
    count=(len(payload)+499)//500;updated=bytearray(image)
    def save(index,page):
        struct.pack_into('<HH',page,504,1,index)
        struct.pack_into('<I',page,508,zlib.crc32(page[:508]))
        updated[index*512:index*512+512]=page
    for i,index in enumerate(pages[:count]):
        page=bytearray(MARKER+payload[i*500:(i+1)*500].ljust(500,b'\xff')+bytes(8))
        save(index,page)
    index=record['node'];page=bytearray(image[index*512:index*512+512])
    struct.pack_into('<I',page,72,len(payload));page[100:504]=b'\xff'*404
    struct.pack_into('<'+'H'*count,page,100,*pages[:count]);save(index,page)
    after=files(updated)
    assert set(after)==set(before)
    assert all(after[key]['data']==(payload if key==name else row['data']) for key,row in before.items())
    permitted=set(pages[:count]+[index])
    assert all(image[at:at+512]==updated[at:at+512] or at//512 in permitted for at in range(0,len(image),512))
    return bytes(updated)
