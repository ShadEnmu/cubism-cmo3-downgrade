"""Cubism 5.4 alpha -> 5.3 .cmo3 converter (core, no third-party deps).

CLI:  python cmo3conv.py <in.cmo3> [out.cmo3]
"""
import os, re, struct, sys, zlib

__version__ = "1.0.0"
import xml.etree.ElementTree as ET


class ConvertError(Exception):
    pass


# ---------------- CAFF container ----------------
def _xor_table(key):
    k = key & 0xff
    return bytes(i ^ k for i in range(256))


def parse_caff(path):
    d = open(path, 'rb').read()
    if d[:4] != b'CAFF':
        raise ConvertError('Это не файл .cmo3 (нет заголовка CAFF).')
    key = struct.unpack('>i', d[14:18])[0]
    tbl = _xor_table(key)
    p = 0x36

    def raw(n):
        nonlocal p
        b = d[p:p + n]; p += n; return b

    def u8(): return raw(1).translate(tbl)[0]
    def i32(): return struct.unpack('>i', raw(4))[0] ^ key
    def i64(): return struct.unpack('>q', raw(8))[0] ^ key

    def string():
        v = 0
        while True:
            b = u8(); v = (v << 7) | (b & 0x7f)
            if not b & 0x80: break
        return raw(v).translate(tbl).decode('utf-8')

    ents = []
    for _ in range(i32()):
        name = string(); tag = string()
        off = i64(); size = i32(); obf = u8(); comp = u8(); raw(8)
        ents.append(dict(name=name, tag=tag, off=off, size=size, obf=obf, comp=comp))
    return d, key, ents


def entry_bytes(d, key, e):
    b = d[e['off']:e['off'] + e['size']]
    if e['obf']: b = b.translate(_xor_table(key))
    if e['comp'] == 33:
        nl, el = struct.unpack('<HH', b[26:30])
        return zlib.decompressobj(-15).decompress(b[30 + nl + el:])
    return b


# ---------------- images ----------------
def packbits_rows(buf, linelens, width):
    out = bytearray(); p = 0
    for L in linelens:
        start = len(out); end = p + L
        while p < end:
            n = buf[p]; p += 1
            if n < 128:
                out += buf[p:p + n + 1]; p += n + 1
            elif n > 128:
                out += bytes((buf[p],)) * (257 - n); p += 1
        if len(out) - start != width:
            raise ConvertError('Повреждённые данные слоя PSD.')
    return bytes(out)


def png_rgba(w, h, r, g, b, a):
    px = bytearray(w * h * 4)
    px[0::4] = r; px[1::4] = g; px[2::4] = b; px[3::4] = a
    stride = w * 4
    raw = bytearray((stride + 1) * h)
    for y in range(h):
        o = y * (stride + 1)
        raw[o + 1:o + 1 + stride] = px[y * stride:(y + 1) * stride]

    def chunk(t, data):
        return struct.pack('>I', len(data)) + t + data + struct.pack('>I', zlib.crc32(t + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))


# imports 5.3 needs for the objects we add (absent from 5.4 files)
EXTRA_IMPORTS = [
    'com.live2d.cubism.doc.model.extension.textureInput.inputFilter.CLayerInputData',
    'com.live2d.cubism.doc.model.extension.textureInput.inputFilter.CLayerSelectorMap',
    'com.live2d.graphics.filter.concreteConnector.FilterOutputValueConnector',
]
BAN = {'LayerMergeSet', 'LayerMergeSetGroup', 'CLayerLMSWrapper', 'LMSFilterInputTable', 'LMSFilterInputIdentifier',
       'LayerMergeSetGuid', 'CModelStateSetSet', 'CPsdCompressedImage', 'CompressedChannel'}


def convert(src, dst, log=print):
    d, key, ents = parse_caff(src)
    E = {e['name']: e for e in ents}
    if 'main.xml' not in E:
        raise ConvertError('В файле нет main.xml.')
    xml = entry_bytes(d, key, E['main.xml']).decode('utf-8')
    prolog = xml[:xml.index('<root')]
    root = ET.fromstring(xml)
    ver = int(root.get('fileFormatVersion', '0'))
    if ver < 504000000:
        raise ConvertError(f'Файл уже в формате 5.3 или старше ({ver}), конвертировать не нужно.')
    shared = root.find('shared'); main = root.find('main')
    byid = {c.get('xs.id'): c for c in shared}
    state = {'idx': max(int(e.get('xs.idx')) for e in shared) + 1, 'n': 0}
    new_files = {}

    def E_(tag, attrs=None, text=None, children=()):
        el = ET.Element(tag, attrs or {}); el.text = text; el.tail = '\n'
        if children:
            el.text = '\n' if text is None else text
            for c in children: el.append(c)
        return el

    def new_obj(tag, attrs=None, children=()):
        el = E_(tag, attrs, children=children)
        state['n'] += 1
        el.set('xs.id', f'#new{state["n"]}'); el.set('xs.idx', str(state['idx'])); state['idx'] += 1
        if el.text is None and tag != 'FilterValueId' and tag != 'FilterInstanceId' and tag != 'StaticFilterDefGuid':
            el.text = '\n'
        shared.append(el); byid[el.get('xs.id')] = el
        return el

    def ref_(tag, n, obj):
        a = {'xs.n': n} if n else {}
        a['xs.ref'] = obj.get('xs.id')
        return E_(tag, a)

    def no_mask(ent):
        for m in ent.findall("*[@xs.n='layerMask']"):
            if m.tag != 'null':
                raise ConvertError('В модели используются маски слоёв (функция 5.4), 5.3 их не поддерживает.')
            ent.remove(m)

    # 1. PSD layers -> PNG
    layers = [l for l in shared.iter('CLayer') if l.find('CPsdCompressedImage') is not None]
    for i, lay in enumerate(layers):
        if i % 25 == 0: log(f'Слои PSD: {i}/{len(layers)}')
        c = lay.find('CPsdCompressedImage')
        w = int(c.find("i[@xs.n='width']").text); h = int(c.find("i[@xs.n='height']").text)
        chans = {}
        for ch in c.find('array'):
            raw = entry_bytes(d, key, E[ch.find('file').get('path')])
            if ch.get('comp') == '1':
                px = packbits_rows(raw, list(map(int, ch.find('int-array').text.split())), w)
            elif ch.get('comp') == '0':
                px = raw[:w * h]
            else:
                raise ConvertError('Неизвестное сжатие слоя: ' + ch.get('comp'))
            chans[ch.get('channelID')] = px
        z = bytes(w * h)
        png = png_rgba(w, h, chans.get('0', z), chans.get('1', z), chans.get('2', z), chans.get('-1', b'\xff' * (w * h)))
        fname = f'imageFileBuf_cv{i}.png'; new_files[fname] = png
        res = new_obj('CImageResource', {'width': str(w), 'height': str(h), 'type': 'INT_ARGB',
                                         'imageFileBuf_size': str(len(png)), 'previewFileBuf_size': '0'},
                      [E_('file', {'xs.n': 'imageFileBuf', 'path': fname})])
        lay.remove(c)
        kids = list(lay)
        for k in kids: lay.remove(k)
        sup = [k for k in kids if k.get('xs.n') == 'super']
        bounds = [k for k in kids if k.get('xs.n') == 'boundsOnImageDoc']
        ident = [k for k in kids if k.get('xs.n') == 'layerIdentifier']
        rest = [k for k in kids if k not in sup + bounds + ident]
        for k in sup + [ref_('CImageResource', 'imageResource', res)] + bounds + ident + rest:
            lay.append(k)
    log(f'Слои PSD: {len(layers)}/{len(layers)}')

    # 2. shared 5.3 filter objects
    def fvid(idstr):
        for c in shared:
            if c.tag == 'FilterValueId' and c.get('idstr') == idstr: return c
        return new_obj('FilterValueId', {'idstr': idstr})

    ID = {s: fvid(s) for s in ['mi_input_layerInputData', 'ilf_inputLayerData', 'mi_currentImageGuid',
                               'ilf_currentImageGuid', 'ilf_outputLayerData', 'ilf_inputLayer',
                               'mi_output_image', 'mi_output_transform']}
    G_SEL = new_obj('StaticFilterDefGuid', {'uuid': '5e9fe1ea-0ec3-4d68-a5fa-018fc7abe301', 'note': '(no debug info)'})
    G_LAY = new_obj('StaticFilterDefGuid', {'uuid': '4083cd1f-40ba-4eda-8400-379019d55ed8', 'note': '(no debug info)'})

    def fval(name, idref=None, idstr=None):
        idel = ref_('FilterValueId', 'id', idref) if idref is not None else E_('FilterValueId', {'xs.n': 'id', 'idstr': idstr})
        return new_obj('FilterValue', None, [E_('s', {'xs.n': 'name'}, name), idel, E_('null', {'xs.n': 'defaultValueInitializer'})])

    FV_select = fval('Select Layer', ID['ilf_outputLayerData'])
    FV_imp = fval('Import Layer', ID['mi_input_layerInputData'])
    FV_impsel = fval('Import Layer selection', ID['ilf_inputLayerData'])
    FV_cur = fval('Current GUID', ID['mi_currentImageGuid'])
    FV_cursel = fval('GUID of Selected Source Image', ID['ilf_currentImageGuid'])
    FV_out = fval('Output image', ID['mi_output_image'])
    FV_outres = fval('Output Image (Resource Format)', idstr='ilf_outputImageRes')
    FV_tr = fval('LayerToCanvas変換', ID['mi_output_transform'])
    FV_trout = fval('LayerToCanvas変換', idstr='ilf_outputTransform')

    def entry(*kids): return E_('entry', children=kids)

    def envconn(k, envdef, inst, valdef):
        return entry(ref_('FilterValueId', 'key', k),
                     E_('EnvConnection', {'xs.n': 'value'}, children=[ref_('FilterValue', '_envValueDef', envdef),
                        ref_('FilterInstance', 'filter', inst), ref_('FilterValue', 'filterValueDef', valdef)]))

    def envvalconn(k, envid):
        return entry(ref_('FilterValueId', 'key', k),
                     E_('EnvValueConnector', {'xs.n': 'value'}, children=[E_('AValueConnector', {'xs.n': 'super'}),
                        ref_('FilterValueId', 'envValueId', envid)]))

    # 3. rewire model images
    mis = [m for m in shared.iter('CModelImage') if m.find('.//LMSFilterInputTable') is not None]
    for mi in mis:
        name = (mi.find("s[@xs.n='name']").text or '?')
        tents = list(mi.find('.//LMSFilterInputTable/hash_map'))
        if len(tents) != 1:
            raise ConvertError(f'Текстура «{name}» использует несколько наборов объединения слоёв — не поддерживается.')
        lms = byid[tents[0].find('LayerMergeSet').get('xs.ref')]
        wraps = list(lms.find("array_list[@xs.n='layers']"))
        if len(wraps) != 1:
            raise ConvertError(f'Текстура «{name}» объединяет {len(wraps)} слоя(ёв) — в 5.3 такого нет. '
                               'Разделите объединение в 5.4 или пересоздайте текстуру после конвертации.')
        w0 = wraps[0]
        if (w0.find("b[@xs.n='isVisible']").text != 'true' or w0.find("f[@xs.n='opacity']").text != '1.0'
                or w0.find("b[@xs.n='isApplyLayerMask']").text != 'false'):
            raise ConvertError(f'Текстура «{name}» использует скрытие/прозрачность/маску в наборе объединения — не поддерживается.')
        upd = mi.find('.//EnvValueSet/l').text
        raw_guid = byid[mi.find("carray_list[@xs.n='linkedRawImageGuids']/CLayeredImageGuid").get('xs.ref')]
        layer = byid[w0.find('CLayer').get('xs.ref')]

        fs = new_obj('ModelImageFilterSet')
        fid0 = new_obj('FilterInstanceId', {'idstr': 'filter0'})
        fid1 = new_obj('FilterInstanceId', {'idstr': 'filter1'})
        sel = new_obj('FilterInstance', {'filterName': 'CLayerSelector'})
        lay = new_obj('FilterInstance', {'filterName': 'CLayerFilter'})
        outc = new_obj('FilterOutputValueConnector', None, [E_('AValueConnector', {'xs.n': 'super'}),
                       ref_('FilterInstance', 'instance', sel), ref_('FilterValueId', 'id', ID['ilf_outputLayerData']),
                       ref_('FilterValue', 'valueDef', FV_select)])
        for k in [ref_('StaticFilterDefGuid', 'filterDefGuid', G_SEL), E_('null', {'xs.n': 'filterDef'}),
                  ref_('FilterInstanceId', 'filterId', fid0),
                  E_('hash_map', {'xs.n': 'inputConnectors', 'count': '2'}, children=[
                      envvalconn(ID['ilf_inputLayerData'], ID['mi_input_layerInputData']),
                      envvalconn(ID['ilf_currentImageGuid'], ID['mi_currentImageGuid'])]),
                  E_('hash_map', {'xs.n': 'outputConnectors', 'count': '1'}, children=[
                      entry(ref_('FilterValueId', 'key', ID['ilf_outputLayerData']),
                            ref_('FilterOutputValueConnector', 'value', outc))]),
                  ref_('ModelImageFilterSet', 'ownerFilterSet', fs)]:
            sel.append(k)
        for k in [ref_('StaticFilterDefGuid', 'filterDefGuid', G_LAY), E_('null', {'xs.n': 'filterDef'}),
                  ref_('FilterInstanceId', 'filterId', fid1),
                  E_('hash_map', {'xs.n': 'inputConnectors', 'count': '1'}, children=[
                      entry(ref_('FilterValueId', 'key', ID['ilf_inputLayer']),
                            ref_('FilterOutputValueConnector', 'value', outc))]),
                  E_('hash_map', {'xs.n': 'outputConnectors', 'count': '0', 'keyType': 'string'}),
                  ref_('ModelImageFilterSet', 'ownerFilterSet', fs)]:
            lay.append(k)
        fs.append(E_('FilterSet', {'xs.n': 'super'}, children=[
            E_('linked_map', {'xs.n': 'filterMap', 'count': '2'}, children=[
                entry(ref_('FilterInstanceId', 'key', fid0), ref_('FilterInstance', 'value', sel)),
                entry(ref_('FilterInstanceId', 'key', fid1), ref_('FilterInstance', 'value', lay))]),
            E_('linked_map', {'xs.n': '_externalInputs', 'count': '2'}, children=[
                envconn(ID['mi_input_layerInputData'], FV_imp, sel, FV_impsel),
                envconn(ID['mi_currentImageGuid'], FV_cur, sel, FV_cursel)]),
            E_('linked_map', {'xs.n': '_externalOutputs', 'count': '2'}, children=[
                envconn(ID['mi_output_image'], FV_out, lay, FV_outres),
                envconn(ID['mi_output_transform'], FV_tr, lay, FV_trout)])]))

        mi.find("ModelImageFilterSet[@xs.n='inputFilter']").set('xs.ref', fs.get('xs.id'))
        inp = E_('CLayerInputData', children=[ref_('CLayer', 'layer', layer),
                 E_('CAffine', {'xs.n': 'affine', 'm00': '1.0', 'm01': '0.0', 'm02': '0.0', 'm10': '0.0', 'm11': '1.0', 'm12': '0.0'}),
                 E_('null', {'xs.n': 'clippingOnTexturePx'})])
        hm = mi.find('ModelImageFilterEnv/FilterEnv/hash_map')
        for k in list(hm): hm.remove(k)
        hm.set('count', '2'); hm.text = '\n'
        hm.append(entry(ref_('FilterValueId', 'key', ID['mi_currentImageGuid']),
            E_('EnvValueSet', {'xs.n': 'value'}, children=[ref_('FilterValueId', 'id', ID['mi_currentImageGuid']),
                ref_('CLayeredImageGuid', 'value', raw_guid), E_('l', {'xs.n': 'updateTimeMs'}, upd)])))
        hm.append(entry(ref_('FilterValueId', 'key', ID['mi_input_layerInputData']),
            E_('EnvValueSet', {'xs.n': 'value'}, children=[ref_('FilterValueId', 'id', ID['mi_input_layerInputData']),
                E_('CLayerSelectorMap', {'xs.n': 'value'}, children=[
                    E_('linked_map', {'xs.n': '_imageToLayerInput', 'count': '1'}, children=[
                        entry(ref_('CLayeredImageGuid', 'key', raw_guid),
                              E_('array_list', {'xs.n': 'value', 'count': '1'}, children=[inp]))])]),
                E_('l', {'xs.n': 'updateTimeMs'}, upd)])))
    log(f'Текстуры переподключены: {len(mis)}')

    # 4. drop 5.4-only fields
    for el in root.iter('CTextureManager'):
        for c in el.findall("*[@xs.n='_layerMergeSetGroups']"): el.remove(c)
    for el in root.iter('CModelSource'):
        for c in el.findall("*[@xs.n='modelStateSetSet']"):
            if c.find("carray_list").get('count') != '0':
                log('Внимание: Model State Set (функция 5.4) будет удалён.')
            el.remove(c)
    for ent in root.iter('ACLayerEntry'):
        no_mask(ent)

    # 5. drop unreachable objects
    reach = set(); stack = [main]
    while stack:
        el = stack.pop()
        for x in el.iter():
            r = x.get('xs.ref')
            if r and r not in reach:
                reach.add(r); stack.append(byid[r])
    for c in list(shared):
        if c.get('xs.id') not in reach: shared.remove(c)
    left = {x.tag for x in root.iter()} & BAN
    if left or any(x.get('filterName') == 'CLayerMergeSetFilter' for x in root.iter()):
        raise ConvertError('Остались неподдерживаемые объекты 5.4: ' + ', '.join(sorted(left)))

    # 6. renumber ids
    remap = {c.get('xs.id'): f'#{i}' for i, c in enumerate(shared)}
    for x in root.iter():
        if x.get('xs.id'): x.set('xs.id', remap[x.get('xs.id')])
        if x.get('xs.ref'): x.set('xs.ref', remap[x.get('xs.ref')])
    root.set('fileFormatVersion', '503010000')

    # 7. prolog
    tags = {x.tag for x in root.iter()}
    imports = sorted(set(re.findall(r'<\?import ([^?]+)\?>', prolog)) | set(EXTRA_IMPORTS))
    imports = [i for i in imports if re.split(r'[.$]', i)[-1] in tags]
    vers = []
    for k, v in re.findall(r'<\?version ([^:]+):(\d+)\?>', prolog):
        if k in ('CLayer', 'ModelStateSet'): continue
        if k == 'CModelSource': v = '15'
        vers.append(f'<?version {k}:{v}?>')
    body = ET.tostring(root, encoding='unicode', short_empty_elements=True)
    out_xml = (prolog.split('\n')[0] + '\n' + '\n'.join(vers) + '\n'
               + '\n'.join(f'<?import {i}?>' for i in imports) + '\n' + body + '\n')

    # 8. repack
    log('Сборка файла...')
    used = set(re.findall(r'path="([^"]+)"', body))
    tbl = _xor_table(key)

    def wstr(s):
        b = s.encode('utf-8'); n = len(b); v = bytearray([n & 0x7f]); n >>= 7
        while n: v.insert(0, 0x80 | (n & 0x7f)); n >>= 7
        return (bytes(v) + b).translate(tbl)

    om = E['main.xml']
    mraw = d[om['off']:om['off'] + om['size']].translate(tbl)
    lh = bytearray(mraw[:30]); nl, el = struct.unpack('<HH', lh[26:30]); lname = mraw[30:30 + nl + el]
    xb = out_xml.encode('utf-8'); co = zlib.compressobj(9, zlib.DEFLATED, -15); comp = co.compress(xb) + co.flush()
    struct.pack_into('<III', lh, 14, 0, 0, 0)
    zipblob = bytes(lh) + lname + comp + struct.pack('<IIII', 0x08074b50, zlib.crc32(xb) & 0xffffffff, len(comp), len(xb))

    items = [(e['name'], e['tag'], e['obf'], e['comp'], d[e['off']:e['off'] + e['size']])
             for e in ents if e['name'] != 'main.xml' and e['name'] in used]
    items += [(n, '', 1, 16, b.translate(tbl)) for n, b in new_files.items()]
    items.append(('main.xml', 'main_xml', 1, 33, zipblob.translate(tbl)))
    missing = used - {i[0] for i in items}
    if missing:
        raise ConvertError('Не найдены файлы внутри архива: ' + ', '.join(sorted(missing)[:5]))

    pos = 0x36 + 4 + sum(len(wstr(n)) + len(wstr(t)) + 22 for n, t, *_ in items)
    table = bytearray(struct.pack('>i', len(items) ^ key))
    for n, t, ob, cp, payload in items:
        table += wstr(n) + wstr(t) + struct.pack('>q', pos ^ key) + struct.pack('>i', len(payload) ^ key)
        table += bytes([ob, cp]).translate(tbl) + b'\x00' * 8
        pos += len(payload)
    tmp = dst + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(d[:0x36]); f.write(table)
        for *_, payload in items: f.write(payload)
        f.write(d[-2:])
    os.replace(tmp, dst)
    log(f'Готово: {dst}')
    return dst


def default_output(src):
    base, _ = os.path.splitext(src)
    return base + '_5.3.cmo3'


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    s = sys.argv[1]
    convert(s, sys.argv[2] if len(sys.argv) > 2 else default_output(s))
