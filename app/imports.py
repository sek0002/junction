import csv
import hashlib
import io
import json
import re
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from . import database as store


def dna(value):
    sequence = re.sub(r'\s+', '', str(value or '')).upper()
    if not sequence or set(sequence) - set('ACGT'):
        raise ValueError('DNA must contain only A, C, G and T, with optional whitespace.')
    return sequence


def numeric(value, label):
    if value is None or str(value).strip() in ('', '-', 'NA', 'N/A', 'None'):
        return None
    try:
        result = float(str(value).replace(',', ''))
    except ValueError:
        raise ValueError(f'{label} must be numeric.')
    if not 0 < result < 1e12:
        raise ValueError(f'{label} must be positive and finite.')
    return result


def header_key(value):
    return re.sub(r'[^a-z0-9]', '', str(value or '').lower().replace('µ','u').replace('μ','u'))


def table_records(matrix):
    """A CSV may concatenate plate tables with different column positions."""
    headers=None;records=[]
    for row in matrix:
        if not any(value is not None and str(value).strip() for value in row):continue
        keys={header_key(value) for value in row}
        is_header=bool(keys & {'name','fragmentname'}) and bool(keys & {'plateid','plate','platename'}) and bool(keys & {'welllocation','well'})
        if headers is None or is_header:
            headers=[str(value or '').strip() for value in row];continue
        records.append(dict(zip(headers,row)))
    return records


def strict_sheet_values(archive):
    """Read cached cell values from Strict OOXML without rewriting the source."""
    workbook=ET.fromstring(archive.read('xl/workbook.xml'))
    sheets=workbook.find('{*}sheets')
    if sheets is None or not len(sheets):raise ValueError('The workbook has no worksheets.')
    views=workbook.find('{*}bookViews')
    active=int(views[0].get('activeTab','0')) if views is not None and len(views) else 0
    sheet=list(sheets)[min(active,len(sheets)-1)]
    rid=next((value for key,value in sheet.attrib.items() if key.endswith('}id')),None)
    relationships=ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
    target=next((r.get('Target') for r in relationships if r.get('Id')==rid and r.get('Type','').endswith('/worksheet')),None)
    if not target:raise ValueError('The active worksheet is unavailable.')
    name=str(PurePosixPath(target.lstrip('/')) if target.startswith('/') else PurePosixPath('xl')/target)
    if '..' in PurePosixPath(name).parts:raise ValueError('Invalid worksheet path.')
    strings=[]
    if 'xl/sharedStrings.xml' in archive.namelist():
        for node in ET.fromstring(archive.read('xl/sharedStrings.xml')):
            strings.append(''.join(t.text or '' for t in node.findall('.//{*}t')))
    worksheet=ET.fromstring(archive.read(name));rows=[]
    for row in worksheet.findall('.//{*}sheetData/{*}row'):
        values=[]
        for cell in row.findall('{*}c'):
            ref=cell.get('r','');letters=re.match('[A-Z]+',ref)
            if not letters:raise ValueError('Worksheet cell reference is missing.')
            column=0
            for char in letters[0]:column=column*26+ord(char)-64
            if column>1000:raise ValueError('A plate table can contain at most 1,000 columns.')
            values.extend([None]*max(0,column-len(values)))
            value=cell.find('{*}v');kind=cell.get('t')
            text=value.text if value is not None else None
            if kind=='s':text=strings[int(text)] if text is not None else None
            elif kind=='inlineStr':text=''.join(t.text or '' for t in cell.findall('.//{*}t'))
            elif kind=='e':raise ValueError(f'Worksheet cell {ref} contains {text}.')
            values[column-1]=text
        rows.append(values)
    return rows


def read_sheet(content, filename):
    if filename.lower().endswith('.xlsx'):
        with ZipFile(io.BytesIO(content)) as archive:
            if sum(info.file_size for info in archive.infolist())>100*1024*1024:
                raise ValueError('The uncompressed workbook exceeds 100 MiB.')
            workbook=ET.fromstring(archive.read('xl/workbook.xml'))
            if workbook.tag.startswith('{http://purl.oclc.org/ooxml/'):
                return table_records(strict_sheet_values(archive))
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        try:
            if wb.active is None:raise ValueError('The workbook has no active worksheet.')
            return table_records(wb.active.values)
        finally:wb.close()
    text = content.decode('utf-8-sig')
    if not text.strip():raise ValueError('The plate file is empty.')
    delimiter = '\t' if '\t' in text.splitlines()[0] else ','
    return table_records(csv.reader(io.StringIO(text), delimiter=delimiter))


def parse_plate(content, filename):
    return parse_plate_rows(read_sheet(content, filename))


def parse_plate_rows(raw):
    if len(raw)>5000:
        raise ValueError('A plate import can contain at most 5,000 rows.')
    parsed = []
    positions = set()
    for number, row in enumerate(raw, 2):
        if not any(v is not None and str(v).strip() for v in row.values()):
            continue
        clean = {header_key(k): v for k,v in row.items()}
        def pick(*keys, default=''):
            return next((clean[k] for k in keys if k in clean and clean[k] is not None), default)
        try:
            name = str(pick('name', 'fragmentname')).strip()
            if not name:
                raise ValueError('Name is required.')
            plate = str(pick('plateid', 'plate', 'platename')).strip()
            well = str(pick('welllocation', 'well')).strip().upper()
            if not plate or not re.fullmatch(r'[A-P](?:0?[1-9]|1[0-9]|2[0-4])', well):
                raise ValueError('Plate ID and a well such as A1–P24 are required.')
            well = well[0] + str(int(well[1:]))
            if (plate, well) in positions:
                raise ValueError('Duplicate plate/well in this file.')
            positions.add((plate, well))
            seq = dna(pick('insertsequence', 'sequence', 'targetsequence'))
            construct = str(pick('constructsequenceinsertadapters', 'constructsequence')).strip()
            construct = dna(construct) if construct else ''
            length = pick('insertlength')
            if length and int(float(length)) != len(seq):
                raise ValueError('Insert length does not match the supplied sequence.')
            clength = pick('constructlengthinsertadapters', 'constructlength')
            if clength and construct and int(float(clength)) != len(construct):
                raise ValueError('Construct length does not match its sequence.')
            if construct and seq not in construct:
                raise ValueError('Construct sequence does not contain the insert sequence.')
            stock = numeric(pick('stockngul', 'concentrationngul', default=None),'Stock concentration')
            parsed.append(dict(name=name, plate_id=plate, well=well, sequence=seq, construct_sequence=construct,
                yield_ng=numeric(pick('yieldng','massng',default=None),'Yield'), stock_ng_ul=stock,
                resuspension_ul=numeric(pick('resuspensionul',default=None),'Resuspension volume'),
                concentration_basis='provided' if stock else 'unknown', notes=str(pick('notes','customlabel'))))
        except (ValueError,TypeError) as exc:
            raise ValueError(f'Row {number}: {exc}') from exc
    if not parsed:
        raise ValueError('No fragments found. Use the supplied example CSV headers.')
    return parsed


def import_plate(content, filename, preview=False, rules=None, precalculated=False):
    audit=[]
    if precalculated:
        from .precalculated import precalculated_rows
        rows,audit=precalculated_rows(content,filename)
    else:rows = parse_plate(content, filename)
    previous = store.import_exists(content, 'plate')
    if preview:
        return {'filename':filename,'count':len(rows),'plates':sorted({r['plate_id'] for r in rows}),
                'already_imported':bool(previous),'rows':[{k:v for k,v in r.items() if k not in ('sequence','construct_sequence')} | {'length':len(r['sequence']), 'physical_length':len(r['construct_sequence'] or r['sequence'])} for r in rows], 'calculation_audit':audit}
    if previous:
        return {'count':0,'unchanged':previous['row_count'],'already_imported':True,'filename':filename}
    # Reject conflicting locations atomically, rather than silently replacing stocks.
    with store.connection() as db:
        changed = 0
        updated = 0
        for r in rows:
            old = db.execute('SELECT name,sequence,construct_sequence FROM fragments WHERE plate_id=? AND well=?',(r['plate_id'],r['well'])).fetchone()
            if old and (old['name'] != r['name'] or old['sequence'] != r['sequence'] or old['construct_sequence'] != r['construct_sequence']):
                raise ValueError(f"Plate {r['plate_id']} well {r['well']} is already occupied by different DNA. Use a new plate ID.")
        for plate_id in {row['plate_id'] for row in rows}:
            existing_plate=db.execute('SELECT archived_at FROM plates WHERE plate_id=?',(plate_id,)).fetchone()
            if existing_plate and existing_plate['archived_at'] and not precalculated:
                raise ValueError(f'Plate {plate_id} is archived. Restore it before importing more wells.')
            db.execute('INSERT OR IGNORE INTO plates(plate_id) VALUES(?)',(plate_id,))
        source_id = db.execute('INSERT INTO imports(filename,digest,kind,row_count) VALUES(?,?,?,?)',
            (filename,hashlib.sha256(content).hexdigest(),'plate',len(rows))).lastrowid
        for r in rows:
            r=r | {'default_yield_ng':r['yield_ng'],'stock_saved':int(r['stock_ng_ul'] is not None or r['resuspension_ul'] is not None)}
            if rules is not None:
                r['stock_rules']=json.dumps(rules)
                if not r['stock_saved']:
                    r['concentration_basis']='Custom rule plan (unmeasured)'
            keys = list(r)+['source_id']
            result = db.execute(f'INSERT OR IGNORE INTO fragments({",".join(keys)}) VALUES({",".join("?" for _ in keys)})', [r[k] for k in r]+[source_id])
            changed += result.rowcount
            if not result.rowcount and precalculated:
                fields=['yield_ng','default_yield_ng','stock_ng_ul','resuspension_ul','concentration_basis','default_stock_ng_ul','default_resuspension_ul','default_concentration_basis','stock_saved']
                db.execute('UPDATE fragments SET '+','.join(key+'=?' for key in fields)+',stock_rules=NULL,source_id=? WHERE plate_id=? AND well=?',
                    [r[key] for key in fields]+[source_id,r['plate_id'],r['well']])
                updated+=1
    return {'count':changed,'updated':updated,'unchanged':len(rows)-changed-updated,'filename':filename,'calculation_audit':audit}
