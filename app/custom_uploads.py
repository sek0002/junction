"""Manual stock entries copy DNA into new independent stocks; never edit linked stocks."""
import hashlib
import json
import re
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from . import database as store
from .exports import parse_sequence_file
from .imports import dna

router=APIRouter(prefix='/api/uploads/custom')


class CustomRow(BaseModel):
    name:str=Field(default='',max_length=1000)
    concentration:float | None=Field(default=None,gt=0,lt=1e12,allow_inf_nan=False)
    location:str=Field(default='',max_length=1200)
    plate:str=Field(default='',max_length=1000)
    well:str=Field(default='',max_length=100)
    link:str=Field(default='',max_length=1200)
    sequence:str=Field(default='',max_length=200000)
    filename:str=Field(default='',max_length=1000)
    features:list[dict]=Field(default_factory=list,max_length=2000)


class CustomBatch(BaseModel):
    rows:list[CustomRow]=Field(min_length=1,max_length=1000)
    request_id:str=Field(default_factory=lambda:str(uuid4()),min_length=1,max_length=100)


def normalized_well(value):
    value=value.strip().upper()
    if not value:return ''
    if not re.fullmatch(r'[A-P](?:0?[1-9]|1[0-9]|2[0-4])',value):raise ValueError('Well must be A1–P24, or blank.')
    return value[0]+str(int(value[1:]))


@router.post('/parse')
async def parse(file:UploadFile=File(...)):
    content=await file.read(10*1024*1024+1)
    if not content or len(content)>10*1024*1024:raise HTTPException(422,'Choose a nonempty file up to 10 MB.')
    try:
        records=parse_sequence_file(content.decode('utf-8-sig'),file.filename or '')
        if not records or len(records)>1000:raise ValueError('Use 1–1,000 sequence records per file.')
        for record in records:
            record['sequence']=dna(record['sequence'])
            if len(record['sequence'])>100000:raise ValueError('Each fragment must be 100,000 nt or shorter.')
        return {'records':records}
    except (ValueError,UnicodeError,KeyError) as error:raise HTTPException(422,str(error)) from error


def resolve_link(db,value):
    if not value.strip():return None
    value=value.strip();match=re.fullmatch(r'(?:#?(\d+)|.*\(#(\d+)\))',value)
    if match:
        rows=db.execute('SELECT * FROM fragments WHERE id=? AND '+store.ACTIVE_FRAGMENTS,(int(match[1] or match[2]),)).fetchall()
    else:
        rows=[row for row in db.execute('SELECT * FROM fragments WHERE '+store.ACTIVE_FRAGMENTS) if row['name'].casefold()==value.casefold()]
    if len(rows)!=1:raise ValueError('Choose one active linked fragment; use its #ID if the name is ambiguous.')
    return store.fragment_dict(rows[0])


@router.post('')
def upload(payload:CustomBatch):
    if sum(len(row.sequence) for row in payload.rows)>2000000:raise HTTPException(422,'Use at most two million pasted bases per batch.')
    prepared=[];positions=set()
    digest=hashlib.sha256(json.dumps(payload.model_dump(),sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    try:
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            cached=db.execute('SELECT result FROM custom_import_results WHERE digest=?',(digest,)).fetchone()
            if cached:
                result=json.loads(cached['result']);result.update(count=0,unchanged=len(result['ids']));return result
            for index,row in enumerate(payload.rows,1):
                try:
                    plate,well=row.plate.strip(),normalized_well(row.well)
                    if plate and well:
                        if (plate,well) in positions:raise ValueError('The batch repeats this plate/well.')
                        positions.add((plate,well))
                    linked=resolve_link(db,row.link)
                    if row.sequence.strip() and linked:raise ValueError('Use a linked fragment or a new sequence, not both.')
                    records=parse_sequence_file(row.sequence) if row.sequence.strip() else []
                    if len(records)>1:raise ValueError('Use one sequence per row; upload multi-record files to split them into rows.')
                    sequence=dna(records[0]['sequence'] if records else linked['sequence'] if linked else '')
                    if len(sequence)>100000:raise ValueError('Each fragment must be 100,000 nt or shorter.')
                    name=row.name.strip() or (linked['name'] if linked else records[0]['name'] if records else '')
                    if not name:raise ValueError('Enter a name.')
                    construct=linked['construct_sequence'] if linked else ''
                    metadata={'stock_id':str(uuid4()),'source_filename':row.filename,'linked_fragment_id':linked['id'] if linked else None,
                              'linked_fragment_name':linked['name'] if linked else '',
                              'features':row.features or (linked.get('custom_metadata',{}).get('features',[]) if linked else records[0].get('features',[]))}
                    parent=db.execute('SELECT archived_at FROM plates WHERE plate_id=?',(plate,)).fetchone()
                    if parent and parent['archived_at']:raise ValueError('Restore the archived plate before adding wells.')
                    old=db.execute('SELECT * FROM fragments WHERE plate_id=? AND well=?',(plate,well)).fetchone() if plate and well else None
                    if old and (old['archived_at'] or any(old[key]!=value for key,value in [('name',name),('sequence',sequence),('construct_sequence',construct),('stock_ng_ul',row.concentration),('location',row.location.strip())])):
                        raise ValueError('This well is occupied. Use a new location or edit the existing stock in Fragments.')
                    prepared.append(dict(name=name,plate_id=plate,well=well,location=row.location.strip(),sequence=sequence,construct_sequence=construct,
                                         stock_ng_ul=row.concentration,custom_metadata=metadata,existing_id=old['id'] if old else None))
                except (ValueError,KeyError) as error:raise ValueError(f'Row {index}: {error}') from error
            previous=db.execute("SELECT id FROM imports WHERE kind='custom' AND digest=?",(digest,)).fetchone()
            source_id=previous['id'] if previous else db.execute('INSERT INTO imports(filename,digest,kind,row_count) VALUES(?,?,?,?)',
                ('Custom upload',digest,'custom',len(prepared))).lastrowid
            ids=[];count=0
            for row in prepared:
                if row['existing_id']:
                    ids.append(row['existing_id']);continue
                metadata=json.dumps(row['custom_metadata'],ensure_ascii=False)
                basis='Provided custom stock' if row['stock_ng_ul'] is not None else 'unknown'
                ids.append(db.execute('''INSERT INTO fragments(name,plate_id,well,location,sequence,construct_sequence,stock_ng_ul,
                    stock_saved,yield_locked,concentration_basis,default_stock_ng_ul,default_concentration_basis,custom_metadata,source_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(row['name'],row['plate_id'],row['well'],row['location'],row['sequence'],row['construct_sequence'],
                    row['stock_ng_ul'],int(row['stock_ng_ul'] is not None),0,basis,row['stock_ng_ul'],basis,metadata,source_id)).lastrowid)
                if row['plate_id'] and row['well']:db.execute('INSERT OR IGNORE INTO plates(plate_id) VALUES(?)',(row['plate_id'],))
                count+=1
            result={'count':count,'unchanged':len(ids)-count,'ids':ids,'names':[row['name'] for row in prepared]}
            db.execute('INSERT INTO custom_import_results(digest,result) VALUES(?,?)',(digest,json.dumps(result)))
        return result
    except ValueError as error:raise HTTPException(422,str(error)) from error
