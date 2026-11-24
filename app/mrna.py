"""Private mRNA batch jobs; scientific code runs in an isolated local runtime."""
from __future__ import annotations
import csv
import io
import json
import os
import subprocess
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator, field_validator
from . import database as store
from .auth import user_id
from .mrna_fragments import prepare_assembly, project_fragments

ROOT = Path(__file__).resolve().parents[1]
router = APIRouter(prefix='/api/mrna', tags=['mRNA'])
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix='mrna')
_LOCK = threading.RLock()
_PROCESSES: dict[str, subprocess.Popen] = {}
_CANCELLED: set[str] = set()
_INITIALIZED: set[str] = set()


def runtime_config():
    path = Path(os.environ.get('JUNCTION_MRNA_CONFIG', ROOT/'.tools/mrna-config.json'))
    try: config = json.loads(path.read_text())
    except (OSError, ValueError): config = {}
    config['source'] = os.environ.get('JUNCTION_MRNARCHITECT_SOURCE', config.get('source', str(ROOT/'vendor/mRNArchitect')))
    config['python'] = os.environ.get('JUNCTION_MRNA_PYTHON', config.get('python', str(ROOT/'.tools/mrna-runtime/bin/python')))
    config['degscore'] = os.environ.get('JUNCTION_DEGSCORE_PATH', config.get('degscore', str(ROOT/'.tools/DegScore')))
    config['ribonn_command'] = os.environ.get('JUNCTION_RIBONN_COMMAND', config.get('ribonn_command', ''))
    config['csc'] = str(ROOT/'app/data/mrna/csc_wu2019.csv')
    return config


def initialize():
    key = str(store.db_path())
    with _LOCK:
        if key in _INITIALIZED: return
        with store.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS mrna_jobs (
                id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL,
                status TEXT NOT NULL, request TEXT NOT NULL, result TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL,
                error TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
            db.execute("UPDATE mrna_jobs SET status='interrupted',error='The server restarted. Run this batch again.' WHERE status IN ('queued','running')")
        _INITIALIZED.add(key)


class Parameters(BaseModel):
    organism: Literal['homo-sapiens', 'mus-musculus'] = 'homo-sapiens'
    objective: Literal['cai', 'tai'] = 'cai'
    gc_global_min: float = Field(.4, ge=0, le=1)
    gc_global_max: float = Field(.7, ge=0, le=1)
    gc_window_min: float = Field(.3, ge=0, le=1)
    gc_window_max: float = Field(.7, ge=0, le=1)
    gc_window_size: int = Field(40, ge=6, le=500)
    avoid_repeat_length: int | None = Field(10, ge=4, le=100)
    avoid_poly_a: int | None = Field(9, ge=3, le=100)
    avoid_poly_t: int | None = Field(9, ge=3, le=100)
    avoid_poly_c: int | None = Field(6, ge=3, le=100)
    avoid_poly_g: int | None = Field(6, ge=3, le=100)
    hairpin_stem_size: int | None = Field(None, ge=3, le=100)
    hairpin_window: int | None = Field(None, ge=10, le=500)
    enable_uridine_depletion: bool = False
    avoid_ribosome_slip: bool = False
    avoid_manufacture_restriction_sites: bool = False
    avoid_micro_rna_seed_sites: bool = False
    avoid_restriction_sites: list[str] = Field(default_factory=list, max_length=30)
    avoid_sequences: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def ordered(self):
        if self.gc_global_min > self.gc_global_max or self.gc_window_min > self.gc_window_max:
            raise ValueError('Minimum GC must not exceed maximum GC.')
        if bool(self.hairpin_stem_size) != bool(self.hairpin_window):
            raise ValueError('Set both hairpin stem size and window, or leave both empty.')
        for site in self.avoid_restriction_sites:
            if not site.isalnum() or len(site)>30: raise ValueError('Use restriction enzyme names such as BsaI.')
        for motif in self.avoid_sequences:
            if not motif or len(motif)>300 or set(motif.upper())-set('ACGTURYSWKMBDHVN'):
                raise ValueError('Avoid sequences must use IUPAC nucleotide notation.')
        if self.objective == 'tai' and self.organism != 'homo-sapiens':
            raise ValueError('This BASE version optimises tAI with human weights. Use CAI for mouse.')
        return self


class AssemblyFragment(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=1000)
    sequence: str = Field(min_length=1, max_length=40000)

    @field_validator('sequence')
    @classmethod
    def dna(cls, value):
        value=''.join(value.split()).upper()
        if set(value)-set('ACGT'):raise ValueError('Donor DNA must contain only A, C, G and T.')
        return value


class FragmentAssembly(BaseModel):
    fragments: list[AssemblyFragment] = Field(min_length=1, max_length=32)
    enzyme: Literal['BsaI','BsmBI','BsmBI + BsaI'] = 'BsaI'
    frame: Literal['auto',1,2,3,-1,-2,-3] = 'auto'
    cds_start: int | None = Field(None, ge=1)
    cds_end: int | None = Field(None, ge=1)
    left_overhang: str | None = Field(None,pattern='^[ACGT]{4}$')
    right_overhang: str | None = Field(None,pattern='^[ACGT]{4}$')
    fixed_regions: list[tuple[int,int]] = Field(default_factory=list,max_length=128)


@router.get('/build-list')
def importable_build_list():
    """Snapshot complete donor assemblies from the caller's active Build list."""
    owner=user_id()
    from .main import AssemblyRequest, build
    from .sequence_engine import reverse_complement
    with store.connection() as db:
        saved=db.execute('SELECT id,request FROM build_list WHERE user_id=? AND removed_at IS NULL ORDER BY id',(owner,)).fetchall()
    items=[];sources={fragment['id']:fragment for fragment in store.fragments()}
    for row in saved:
        raw=json.loads(row['request']);item={'id':row['id'],'name':raw.get('name','Assembly'),'enzyme':raw.get('enzyme','BsaI')}
        try:
            request=AssemblyRequest.model_validate(raw)
            result,_=build(request)
            if request.nested_assemblies and any(not n.get('applied') or n.get('errors') for n in result.get('nested_assemblies',[])):
                raise ValueError('Resolve the nested assembly errors in the Assembly Build list before importing.')
            edges=[edge for edge in result['fragments'] if not edge['is_backbone'] and edge['id']!=request.starter_fragment_id]
            if not edges:raise ValueError('This build has no donor fragments after excluding the backbone.')
            fragments=[]
            for edge in edges:
                source=sources.get(edge['id'])
                if not source:raise ValueError('A source donor is unavailable.')
                sequence=edge['input_sequence']
                if edge.get('orientation',1)<0:sequence=reverse_complement(sequence)
                physical=source.get('construct_sequence')
                if physical:
                    if physical.count(source['sequence'])!=1:raise ValueError('The physical donor has an ambiguous insert location.')
                    sequence=physical.replace(source['sequence'],sequence,1)
                fragments.append({'id':source['id'],'name':source['name'],'sequence':sequence})
            first=next(f for f in result['features'] if f.get('source')=='fragment' and f.get('fragment_id')==edges[0]['id'])
            shift=first['start']
            nested=[(f['start']-shift+1,f['end']-shift) for f in result['features'] if f.get('source')=='nested_fusion' and f['start']>=shift]
            snapshot=FragmentAssembly(fragments=fragments,enzyme=request.enzyme,
                left_overhang=edges[0]['left_overhang'],right_overhang=edges[-1]['right_overhang'],fixed_regions=nested).model_dump()
            prepared=prepare_assembly(snapshot)
            Record(name=item['name'],sequence=prepared['sequence'],assembly=prepared['assembly'])
            prepared.pop('_result')
            # Library metadata is kept separately from immutable donor DNA.
            prepared['cards']=[{'id':edge['id'],'name':edge['name'],'left':edge['left_overhang'],'right':edge['right_overhang'],
                'orientation':edge.get('orientation',1),'plate_id':sources[edge['id']].get('plate_id',''),
                'well':sources[edge['id']].get('well',''),'length':len(fragment['sequence'])}
                for edge,fragment in zip(edges,fragments)]
            if request.nested_assemblies:prepared['warnings'].append('Nested replacements are imported as assembled parent donors; their fusion labels are protected.')
            item.update(prepared)
        except (ValueError,KeyError,StopIteration,HTTPException) as error:
            item['error']=str(error.detail if isinstance(error,HTTPException) else error)
        items.append(item)
    return {'items':items}


@router.post('/assembly/preview')
def preview_saved_assembly(payload:FragmentAssembly):
    user_id()
    try:result=prepare_assembly(payload.model_dump())
    except ValueError as error:raise HTTPException(422,str(error)) from None
    result.pop('_result')
    return result


class AssembleInput(BaseModel):
    fragment_ids: list[int] = Field(min_length=1,max_length=32)
    enzyme: Literal['BsaI','BsmBI','BsmBI + BsaI'] = 'BsaI'
    frame: Literal['auto',1,2,3,-1,-2,-3] = 'auto'
    cds_start: int | None = Field(None,ge=1)
    cds_end: int | None = Field(None,ge=1)


@router.post('/assemble')
def assemble_input(payload:AssembleInput):
    user_id()
    if len(set(payload.fragment_ids))!=len(payload.fragment_ids):raise HTTPException(422,'Choose each donor fragment once.')
    fragments=[]
    for identifier in payload.fragment_ids:
        fragment=store.get_fragment(identifier)
        if not fragment:raise HTTPException(404,f'Fragment {identifier} is unavailable.')
        fragments.append({'id':fragment['id'],'name':fragment['name'],
            'sequence':fragment.get('construct_sequence') or fragment['sequence']})
    try:
        snapshot=FragmentAssembly(fragments=fragments,**payload.model_dump(exclude={'fragment_ids'})).model_dump()
        result=prepare_assembly(snapshot)
    except ValueError as error:raise HTTPException(422,str(error)) from None
    result.pop('_result')
    return result


class Record(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sequence: str = Field(min_length=1, max_length=24000)
    kind: Literal['nucleotide', 'protein'] = 'nucleotide'
    group: str = Field('Multiplex 1', max_length=100)
    parameters: Parameters | None = None
    five_prime_utr: str | None = Field(None, max_length=1500)
    three_prime_utr: str | None = Field(None, max_length=2000)
    preserve_regions: list[tuple[int, int]] = Field(default_factory=list, max_length=256)
    assembly: FragmentAssembly | None = None

    @field_validator('name')
    @classmethod
    def named(cls, value):
        if not value.strip(): raise ValueError('Sequence name is required.')
        return ' '.join(value.split())

    @model_validator(mode='after')
    def sequence_valid(self):
        self.sequence = ''.join(self.sequence.split()).upper()
        if self.kind == 'nucleotide':
            self.sequence = self.sequence.replace('U', 'T')
            if set(self.sequence)-set('ACGT'): raise ValueError('Nucleotide inputs must contain only A, C, G, T or U.')
            if len(self.sequence)%3: raise ValueError('Coding sequence length must be a multiple of three.')
        elif set(self.sequence)-set('ACDEFGHIKLMNPQRSTVWY*'):
            raise ValueError('Protein inputs must use the standard 20 amino acids and optional terminal *.')
        if not self.sequence: raise ValueError('Sequence is empty.')
        if self.assembly:
            if self.kind!='nucleotide':raise ValueError('Fragment assemblies require nucleotide input.')
            assembled=prepare_assembly(self.assembly.model_dump())
            if self.sequence!=assembled['sequence']:raise ValueError('The CDS differs from its fragment assembly. Rebuild the input or detach it before editing.')
            self.assembly=FragmentAssembly(**assembled['assembly'])
            self.preserve_regions=list(dict.fromkeys([*self.preserve_regions,*(tuple(r) for r in assembled['preserve_regions'])]))
        length = len(self.sequence)*(3 if self.kind=='protein' else 1)
        if length>8000: raise ValueError('Use coding sequences up to 8,000 nt per record.')
        for start, end in self.preserve_regions:
            if start<1 or end<start or end>length or (start-1)%3 or end%3:
                raise ValueError('Preserved regions use inclusive, 1-based codon-aligned coordinates within the CDS.')
        return self


class Batch(BaseModel):
    name: str = Field('mRNA design batch', min_length=1, max_length=120)
    mode: Literal['compare', 'design'] = 'compare'
    records: list[Record] = Field(min_length=1, max_length=32)
    parameters: Parameters = Field(default_factory=Parameters)
    candidates: int = Field(1, ge=1, le=3)
    five_prime_utr: str = Field('', max_length=1500)
    three_prime_utr: str = Field('', max_length=2000)
    poly_a: int = Field(0, ge=0, le=300)
    temperature: float = Field(37, ge=4, le=60)
    fold_scope: Literal['cds', 'transcript'] = 'cds'
    seed: int = Field(42, ge=0, le=2147483600)
    predict_translation: bool = False

    @model_validator(mode='after')
    def sizes(self):
        if len({r.name for r in self.records})!=len(self.records): raise ValueError('Use unique names for all input sequences.')
        total = 0
        for r in self.records:
            n = len(r.sequence)*(3 if r.kind=='protein' else 1)
            total += n
            for seq in [self.five_prime_utr, self.three_prime_utr, r.five_prime_utr, r.three_prime_utr]:
                if seq is not None and set(''.join(seq.split()).upper())-set('ACGTU'):
                    raise ValueError('UTRs must contain only A, C, G, T or U.')
            if self.predict_translation:
                five=''.join((r.five_prime_utr if r.five_prime_utr is not None else self.five_prime_utr).split())
                three=''.join((r.three_prime_utr if r.three_prime_utr is not None else self.three_prime_utr).split())
                if not five or not three: raise ValueError('RiboNN requires both 5-prime and 3-prime UTRs for every input.')
                if len(five)>1381: raise ValueError('RiboNN supports 5-prime UTRs up to 1,381 nt.')
                if r.kind=='protein' and not r.sequence.endswith('*') or r.kind=='nucleotide' and not r.sequence.endswith(('TAA','TAG','TGA')):
                    raise ValueError('RiboNN requires every coding sequence to end with a stop codon.')
            if n+len(r.five_prime_utr if r.five_prime_utr is not None else self.five_prime_utr)+len(r.three_prime_utr if r.three_prime_utr is not None else self.three_prime_utr)+self.poly_a>10000:
                raise ValueError('Assembled transcripts must be at most 10,000 nt.')
        if total>120000: raise ValueError('Use at most 120,000 coding nucleotides per batch.')
        return self


def stop_process(proc,force=False):
    try:
        if os.name=='nt': proc.kill() if force else proc.terminate()
        else: os.killpg(proc.pid,signal.SIGKILL if force else signal.SIGTERM)
    except ProcessLookupError: pass


def invoke(payload, job_id=None, timeout=600):
    config = runtime_config()
    if not Path(config['python']).is_file() or not (Path(config['source'])/'src/mrnarchitect').is_dir():
        raise RuntimeError('Connect a local mRNArchitect installation using scripts/setup_mrna.py, then retry.')
    with __import__('tempfile').TemporaryDirectory(prefix='junction-mrna-') as temp:
        proc = subprocess.Popen([config['python'], str(ROOT/'app/mrna_worker.py')], cwd=temp,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=(os.name!='nt'))
        with _LOCK:
            if job_id in _CANCELLED: stop_process(proc)
            if job_id: _PROCESSES[job_id] = proc
        try:
            stdout, stderr = proc.communicate(json.dumps({'config':config, **payload}), timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_process(proc,force=True); proc.communicate()
            raise RuntimeError('This sequence exceeded the 10-minute calculation limit. Reduce constraints or batch size.') from None
        finally:
            with _LOCK:
                if job_id: _PROCESSES.pop(job_id, None)
        if proc.returncode: raise RuntimeError('The scientific runtime failed. Check the local mRNA runtime installation.')
        try: data = json.loads(stdout)
        except ValueError: raise RuntimeError('The scientific runtime returned invalid results.') from None
        if data.get('error'): raise RuntimeError(data['error'])
        return data


@lru_cache(maxsize=4)
def capabilities_cached(python, source, degscore, command):
    try: return invoke({'action':'capabilities'}, timeout=45)
    except RuntimeError as error: return {'ready':False, 'message':str(error), 'models':{}}


@router.get('/capabilities')
def capabilities():
    c=runtime_config()
    return capabilities_cached(c['python'],c['source'],c['degscore'],c['ribonn_command'])


class StabilityRequest(BaseModel):
    sequence:str=Field(min_length=1,max_length=10000)
    structure:str=Field(min_length=1,max_length=10000,pattern=r'^[().]+$')

    @model_validator(mode='after')
    def valid_fold(self):
        self.sequence=''.join(self.sequence.split()).upper().replace('U','T')
        if not self.sequence or set(self.sequence)-set('ACGT'):raise ValueError('Use only A, C, G, T or U.')
        if len(self.sequence)!=len(self.structure):raise ValueError('Sequence and dot-bracket structure lengths must match.')
        depth=0
        for char in self.structure:
            depth+=(char=='(')-(char==')')
            if depth<0:raise ValueError('Dot-bracket structure is unbalanced.')
        if depth:raise ValueError('Dot-bracket structure is unbalanced.')
        return self


@router.post('/stability')
def stability(payload:StabilityRequest):
    user_id()
    try:return invoke({'action':'stability',**payload.model_dump()},timeout=60)
    except RuntimeError as error:raise HTTPException(503,str(error)) from None


@router.post('/design-metrics')
def design_metrics(payload:Record):
    user_id()
    if payload.kind!='nucleotide':raise HTTPException(422,'Supply the scored nucleotide CDS.')
    try:return invoke({'action':'quality','sequence':payload.sequence,'parameters':(payload.parameters or Parameters()).model_dump()},timeout=60)
    except RuntimeError as error:raise HTTPException(503,str(error)) from None


def serialize(row, full=True):
    item={k:row[k] for k in ['id','name','status','completed','total','error','created_at','updated_at']}
    if full:
        item['request']=json.loads(row['request']); item['result']=json.loads(row['result'])
    return item


def owned(identifier, owner):
    initialize()
    with store.connection() as db:
        row=db.execute('SELECT * FROM mrna_jobs WHERE id=? AND user_id=?',(identifier,owner)).fetchone()
    if row is None: raise HTTPException(404,'mRNA batch not found.')
    return row


def update(identifier, **values):
    with store.connection() as db:
        db.execute('UPDATE mrna_jobs SET '+','.join(k+'=?' for k in values)+',updated_at=CURRENT_TIMESTAMP WHERE id=?',(*values.values(),identifier))


def execute(identifier, payload):
    result={'rows':[], 'errors':[], 'parameters':payload}
    try:
        update(identifier,status='running')
        for index, record in enumerate(payload['records']):
            with _LOCK:
                if identifier in _CANCELLED: break
            try:
                output=invoke({'action':'run', 'batch':payload, 'record':record, 'index':index}, identifier)
                result['rows'].extend(output['rows']); result['errors'].extend(output.get('errors',[]))
            except RuntimeError as error:
                with _LOCK:
                    if identifier in _CANCELLED: break
                result['errors'].append({'name':record['name'],'error':str(error)})
            update(identifier,result=json.dumps(result,allow_nan=False),completed=index+1)
        with _LOCK: cancelled=identifier in _CANCELLED
        status='cancelled' if cancelled else 'partial' if result['rows'] and result['errors'] else 'failed' if not result['rows'] else 'complete'
        update(identifier,status=status,result=json.dumps(result,allow_nan=False),error=None if result['rows'] or cancelled else 'No sequences completed. See sequence errors.')
    except Exception:
        update(identifier,status='failed',error='The mRNA batch could not finish. Retry the batch.')
    finally:
        with _LOCK: _CANCELLED.discard(identifier)


@router.post('/jobs',status_code=202)
def start(payload:Batch):
    owner=user_id(); initialize()
    c=capabilities()
    if not c.get('ready'): raise HTTPException(503,c.get('message','mRNA runtime is unavailable.'))
    if payload.predict_translation and not c.get('models',{}).get('ribonn'):
        raise HTTPException(422,'RiboNN is not connected. Configure its trained local runtime before requesting translation predictions.')
    identifier=str(uuid4()); data=payload.model_dump()
    with _LOCK:
        with store.connection() as db:
            running=db.execute("SELECT COUNT(*) FROM mrna_jobs WHERE user_id=? AND status IN ('queued','running')",(owner,)).fetchone()[0]
            if running>=2: raise HTTPException(409,'Wait for or cancel an active mRNA batch before starting another.')
            db.execute('INSERT INTO mrna_jobs(id,user_id,name,status,request,result,total) VALUES(?,?,?,?,?,?,?)',
                (identifier,owner,payload.name,'queued',json.dumps(data),'{}',len(data['records'])))
        _POOL.submit(execute,identifier,data)
    return {'id':identifier,'status':'queued'}


@router.get('/jobs')
def history():
    owner=user_id(); initialize()
    with store.connection() as db:
        rows=db.execute('SELECT * FROM mrna_jobs WHERE user_id=? ORDER BY created_at DESC,rowid DESC LIMIT 100',(owner,)).fetchall()
    return {'items':[serialize(r,False) for r in rows]}


@router.get('/jobs/{identifier}')
def get_job(identifier:str):
    return serialize(owned(identifier,user_id()))


@router.post('/jobs/{identifier}/cancel')
def cancel(identifier:str):
    row=owned(identifier,user_id())
    with _LOCK:
        if row['status'] in ('running','queued'):
            _CANCELLED.add(identifier)
            if proc:=_PROCESSES.get(identifier): stop_process(proc)
    return {'cancel_requested':True}


@router.get('/jobs/{identifier}/export')
def export(identifier:str, format:Literal['json','csv','fasta','dbn','fragments-fasta','fragments-csv']='csv'):
    row=owned(identifier,user_id()); data=json.loads(row['result']); rows=data.get('rows',[])
    if format.startswith('fragments-'):
        fragments=[]
        for item in rows:
            if item['strategy']=='input' or not item.get('assembly'):continue
            try:output=project_fragments(item['assembly'],item['cds'])
            except ValueError as error:raise HTTPException(422,str(error)) from None
            fragments.extend({'candidate':item['name'],**part} for part in output['fragments'])
        if not fragments:raise HTTPException(422,'Optimise a fragment assembly before exporting new donor fragments.')
        if format=='fragments-csv':
            stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=['candidate','name','sequence','orientation','left_overhang','right_overhang','changed_nt'],extrasaction='ignore');writer.writeheader()
            for part in fragments:
                for key in ('candidate','name'):
                    if part[key].startswith(('=','+','-','@','\t','\r')):part[key]="'"+part[key]
                writer.writerow(part)
            content=stream.getvalue();mime='text/csv'
        else:
            content='\n'.join('>'+ ' '.join((p['candidate']+' | '+p['name']).split())+'\n'+'\n'.join(p['sequence'][i:i+80] for i in range(0,len(p['sequence']),80)) for p in fragments)+'\n';mime='text/plain'
    elif format=='json': content=json.dumps(serialize(row),indent=2,allow_nan=False); mime='application/json'
    elif format=='csv':
        stream=io.StringIO(); fields=['name','input_name','group','strategy','length','gc','cai','tai','mfe','mfe_density','paired_ratio','degscore','predicted_half_life','csc','translation','homopolymer_nt','homopolymer_ratio','manufacturability','hamming_ratio','protein_preserved','fold_scope','temperature','model_versions','parameters','seed','sha256','cds','transcript']
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader()
        for item in rows:
            record={**item,**item['metrics']}; record['model_versions']=json.dumps(item['model_versions'],sort_keys=True); record['parameters']=json.dumps(item['parameters'],sort_keys=True)
            # CSV imports must not interpret sequence labels as formulas.
            for key in ('name','input_name','group','strategy'):
                if str(record.get(key,'')).startswith(('=','+','-','@','\t','\r')): record[key]="'"+str(record[key])
            writer.writerow(record)
        content=stream.getvalue();mime='text/csv'
    else:
        chunks=[]
        for item in rows:
            name=' '.join(item['name'].split())
            if format=='fasta':chunks.append('>'+name+'\n'+'\n'.join(item['transcript'][i:i+80].replace('T','U') for i in range(0,len(item['transcript']),80)))
            else: chunks.append('>'+name+' | '+item['fold_scope']+' | '+str(item['metrics']['mfe'])+' kcal/mol\n'+item['fold_sequence'].replace('T','U')+'\n'+item['structure'])
        content='\n'.join(chunks)+'\n';mime='text/plain'
    extension={'fragments-fasta':'fragments.fasta','fragments-csv':'fragments.csv'}.get(format,format)
    return Response(content,media_type=mime,headers={'Content-Disposition':f'attachment; filename="junction-mrna-{identifier[:8]}.{extension}"'})
