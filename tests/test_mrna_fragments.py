"""Frame calls, immutable fusion labels and physical donor round trips."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError
from app import database as store
from app.main import app
from app.mrna import Record, Batch, Parameters, invoke, runtime_config, initialize
from app.mrna_fragments import prepare_assembly, project_fragments, detect_cds
from app.sequence_engine import assemble, digest_fragment, reverse_complement
from auth_client import bootstrap_pin

CDS='ATG'+'GCT'*15+'TAA'


def donor(left,target,right):
    return 'GCGTGGTCTCA'+left+target+right+'CGAGACCACGCA'


def fixture(reverse_cds=False,reverse_donor=False):
    dna='TTTG'+(reverse_complement(CDS) if reverse_cds else CDS)+'CGAA'
    cut=19
    parts=[{'id':1,'name':'Part A','sequence':donor(dna[:4],dna[4:cut],dna[cut:cut+4])},
        {'id':2,'name':'Part B','sequence':donor(dna[cut:cut+4],dna[cut+4:-4],dna[-4:])}]
    if reverse_donor:parts[1]['sequence']=reverse_complement(parts[1]['sequence'])
    return {'fragments':parts,'enzyme':'BsaI','frame':'auto'}


def synonym(prepared):
    cds=prepared['sequence'];locked={p for a,b in prepared['preserve_regions'] for p in range(a-1,b)}
    for i in range(0,len(cds),3):
        if cds[i:i+3]=='GCT' and not locked.intersection(range(i,i+3)):
            return cds[:i]+'GCC'+cds[i+3:]
    raise AssertionError('Fixture needs one mutable alanine codon.')


class FragmentMappingTests(unittest.TestCase):
    def test_fixed_build_boundaries_keep_reverse_orientation(self):
        source=fixture()['fragments'][:1]
        p=prepare_assembly({'fragments':source,'enzyme':'BsaI','frame':'auto',
            'left_overhang':reverse_complement('GCTG'),'right_overhang':reverse_complement('TTTG')})
        self.assertEqual(p['fragment_map'][0]['orientation'],-1)
        self.assertEqual(project_fragments(p['assembly'],p['sequence'])['fragments'][0]['sequence'],source[0]['sequence'])

    def test_auto_detection_and_explicit_six_frames(self):
        for reverse in (False,True):
            snap=fixture(reverse_cds=reverse);p=prepare_assembly(snap)
            self.assertEqual(p['sequence'],CDS)
            self.assertEqual((p['cds_start'],p['cds_end']),(5,55))
            self.assertEqual(p['frame'],-2 if reverse else 2)
            self.assertTrue(p['candidates'][0]['complete'])
        for frame in (1,2,3,-1,-2,-3):
            dna='C'*(abs(frame)-1)+CDS+'CC'
            if frame<0:dna=reverse_complement(dna)
            self.assertEqual(detect_cds(dna,frame)[0]['frame'],frame)
            self.assertTrue(detect_cds(dna,frame)[0]['complete'])

    def test_donor_round_trip_both_strands_and_reverse_physical_input(self):
        for reverse_cds in (False,True):
            for reverse_donor in (False,True):
                with self.subTest(reverse_cds=reverse_cds,reverse_donor=reverse_donor):
                    p=prepare_assembly(fixture(reverse_cds,reverse_donor));designed=synonym(p)
                    output=project_fragments(p['assembly'],designed)
                    self.assertTrue(output['junctions_preserved'])
                    self.assertEqual(sum(f['changed_nt'] for f in output['fragments']),1)
                    original=p['assembled_sequence'];dna=output['sequence'];a=p['cds_start']-1;b=p['cds_end']
                    self.assertEqual(dna[:a],original[:a]);self.assertEqual(dna[b:],original[b:])
                    self.assertEqual(assemble(output['fragments'],'BsaI',circular=False)['sequence'],dna)
                    for before,after in zip(p['assembly']['fragments'],output['fragments']):
                        self.assertTrue(after['non_cds_preserved'])
                        mutable={i for a,b in after['cds_regions'] for i in range(a-1,b)}
                        self.assertTrue(all(a==b for i,(a,b) in enumerate(zip(before['sequence'],after['sequence'])) if i not in mutable))
                        old=digest_fragment(before['sequence'],'BsaI');new=digest_fragment(after['sequence'],'BsaI')
                        self.assertEqual(old['left_overhang'],new['left_overhang']);self.assertEqual(old['right_overhang'],new['right_overhang'])
                        self.assertEqual(before['sequence'][:old['target_start']],after['sequence'][:new['target_start']])
                        self.assertEqual(before['sequence'][old['target_end']:],after['sequence'][new['target_end']:])

    def test_locked_codons_reject_changes_and_schema_rejects_detached_cds(self):
        p=prepare_assembly(fixture());r=Record(name='Assembly',sequence=p['sequence'],assembly=p['assembly'])
        self.assertEqual([list(v) for v in r.preserve_regions],p['preserve_regions'])
        start,end=p['preserve_regions'][0]
        i=start-1;bad=CDS[:i]+('C' if CDS[i]!='C' else 'A')+CDS[i+1:]
        with self.assertRaisesRegex(ValueError,'protected junction'):project_fragments(p['assembly'],bad)
        with self.assertRaisesRegex(ValidationError,'differs'):Record(name='Assembly',sequence=synonym(p),assembly=p['assembly'])
        with self.assertRaisesRegex(ValidationError,'nucleotide'):Record(name='Assembly',sequence='MAA',kind='protein',assembly=p['assembly'])

    def test_manual_bounds_partial_calls_and_invalid_assemblies(self):
        p=prepare_assembly(fixture())
        manual=prepare_assembly(fixture()|{'frame':2,'cds_start':8,'cds_end':55})
        self.assertEqual(manual['sequence'],CDS[3:]);self.assertTrue(any('Partial CDS' in w for w in manual['warnings']))
        for changes in ({'frame':1,'cds_start':5,'cds_end':55},{'cds_start':5},{'cds_start':5,'cds_end':54}):
            with self.assertRaises(ValueError):prepare_assembly(fixture()|changes)
        bad=fixture();bad['fragments'][1]['sequence']=donor('AAAA','GCTTAA','CGAA')
        with self.assertRaisesRegex(ValueError,'Assembly is invalid'):prepare_assembly(bad)

    @unittest.skipUnless(Path(runtime_config()['python']).is_file(),'Optional scientific runtime')
    def test_real_optimisation_preserves_protein_junctions_and_round_trips(self):
        p=prepare_assembly(fixture(reverse_donor=True))
        params=Parameters(gc_global_min=0,gc_global_max=1,gc_window_min=0,gc_window_max=1,
            avoid_repeat_length=None,avoid_poly_a=None,avoid_poly_t=None,avoid_poly_c=None,avoid_poly_g=None)
        batch=Batch(mode='design',parameters=params,records=[Record(name='Assembly',sequence=p['sequence'],assembly=p['assembly'])]).model_dump()
        result=invoke({'action':'run','batch':batch,'record':batch['records'][0],'index':0})
        self.assertFalse(result['errors'],result['errors']);self.assertEqual(len(result['rows']),2)
        before,after=result['rows'];self.assertNotEqual(before['cds'],after['cds'])
        self.assertEqual(before['protein'],after['protein']);self.assertTrue(after['metrics']['protein_preserved'])
        for a,b in p['preserve_regions']:self.assertEqual(before['cds'][a-1:b],after['cds'][a-1:b])
        self.assertTrue(after['fragment_output']['junctions_preserved'])
        self.assertTrue(assemble(after['fragment_output']['fragments'],'BsaI',circular=False)['valid'])
        batch['parameters']['enable_uridine_depletion']=True
        depleted=invoke({'action':'run','batch':batch,'record':batch['records'][0],'index':0})
        self.assertFalse(depleted['errors'],depleted['errors'])
        candidate=depleted['rows'][1]
        locked={i for a,b in p['preserve_regions'] for i in range(a-1,b)}
        for i in range(0,len(p['sequence']),3):
            if i in locked:self.assertEqual(candidate['cds'][i:i+3],p['sequence'][i:i+3])
            else:self.assertNotEqual(candidate['cds'][i+2],'T')
        self.assertEqual(candidate['protein'],before['protein'])
        self.assertTrue(candidate['fragment_output']['junctions_preserved'])
        self.assertEqual(assemble(candidate['fragment_output']['fragments'],'BsaI',circular=False)['sequence'],candidate['fragment_output']['sequence'])
        a,b=p['preserve_regions'][0]
        batch['parameters']['avoid_sequences']=[p['sequence'][a-1:b]]
        conflict=invoke({'action':'run','batch':batch,'record':batch['records'][0],'index':0})
        self.assertEqual(len(conflict['rows']),1)
        self.assertTrue(conflict['errors'])
        self.assertEqual(conflict['rows'][0]['cds'],p['sequence'])


class FragmentInputAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB')
        os.environ['GOLDEN_GATE_DB']=str(Path(self.tmp.name)/'db.sqlite3');store.initialize()
        self.client=TestClient(app);self.client.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
        self.ids=[]
        with store.connection() as db:
            for i,part in enumerate(fixture()['fragments']):
                self.ids.append(db.execute('INSERT INTO fragments(name,sequence,plate_id,well) VALUES(?,?,?,?)',(part['name'],part['sequence'],'MRNA',str(i))).lastrowid)

    def tearDown(self):
        self.client.close()
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.tmp.cleanup()

    def test_preview_auth_frame_validation_and_library_integrity(self):
        physical='AAAA'+fixture()['fragments'][0]['sequence']+'CCCC'
        with store.connection() as db:db.execute('UPDATE fragments SET construct_sequence=? WHERE id=?',(physical,self.ids[0]))
        request={'fragment_ids':self.ids,'enzyme':'BsaI','frame':'auto'}
        with TestClient(app) as anon:self.assertEqual(anon.post('/api/mrna/assemble',json=request).status_code,401)
        reply=self.client.post('/api/mrna/assemble',json=request);self.assertEqual(reply.status_code,200,reply.text)
        self.assertEqual(reply.json()['sequence'],CDS);self.assertEqual(reply.json()['frame'],2)
        self.assertEqual(reply.json()['assembly']['fragments'][0]['sequence'],physical)
        exported=project_fragments(reply.json()['assembly'],synonym(reply.json()))
        self.assertTrue(exported['fragments'][0]['sequence'].startswith('AAAA'))
        self.assertTrue(exported['fragments'][0]['sequence'].endswith('CCCC'))
        for patch in ({'fragment_ids':[self.ids[0]]*2},{'frame':4},{'fragment_ids':[9999999]},{'frame':1,'cds_start':5,'cds_end':55}):
            self.assertIn(self.client.post('/api/mrna/assemble',json=request|patch).status_code,(404,422))
        self.assertEqual(store.get_fragment(self.ids[0])['sequence'],fixture()['fragments'][0]['sequence'])

    def test_private_donor_exports_use_saved_snapshot(self):
        p=prepare_assembly(fixture());designed=synonym(p)
        row={'name':'=candidate','strategy':'CAI','assembly':p['assembly'],'cds':designed}
        initialize()
        with store.connection() as db:
            owner=db.execute("SELECT id FROM auth_users WHERE username='admin'").fetchone()[0]
            db.execute('INSERT INTO mrna_jobs(id,user_id,name,status,request,result,total) VALUES(?,?,?,?,?,?,?)',('export',owner,'Assembly','complete','{}',json.dumps({'rows':[row]}),1))
            db.execute('UPDATE fragments SET archived_at=CURRENT_TIMESTAMP')
        response=self.client.get('/api/mrna/jobs/export/export?format=fragments-csv');self.assertEqual(response.status_code,200,response.text)
        parts=list(csv.DictReader(io.StringIO(response.text)))
        self.assertEqual(len(parts),2);self.assertTrue(parts[0]['candidate'].startswith("'="))
        self.assertTrue(assemble(parts,'BsaI',circular=False)['valid'])
        self.assertEqual(self.client.get('/api/mrna/jobs/export/export?format=fragments-fasta').status_code,200)
        with TestClient(app) as anon:self.assertEqual(anon.get('/api/mrna/jobs/export/export?format=fragments-csv').status_code,401)

    def test_named_build_import_excludes_backbones_and_other_users(self):
        from test_sequence_engine import backbone
        with store.connection() as db:
            owner=db.execute("SELECT id FROM auth_users WHERE username='admin'").fetchone()[0]
            vector=db.execute('INSERT INTO plasmids(name,sequence,circular) VALUES(?,?,1)',('Vector',backbone('TTTG','CGAA'))).lastrowid
            requests=[{'name':'Named complete assembly','enzyme':'BsaI','fragment_ids':self.ids,'backbone_id':vector},
                {'name':'Starter backbone','enzyme':'BsaI','starter_fragment_id':self.ids[0],'fragment_ids':[self.ids[1]],'circular':False},
                {'name':'Empty donors','enzyme':'BsaI','fragment_ids':[],'starter_fragment_id':self.ids[0],'circular':False}]
            for request in requests:db.execute('INSERT INTO build_list(user_id,request) VALUES(?,?)',(owner,json.dumps(request)))
        response=self.client.get('/api/mrna/build-list');self.assertEqual(response.status_code,200,response.text)
        complete,starter,empty=response.json()['items']
        self.assertNotIn('error',complete,complete.get('error'));self.assertEqual(complete['name'],'Named complete assembly')
        self.assertEqual(complete['sequence'],CDS)
        self.assertEqual([f['id'] for f in complete['assembly']['fragments']],self.ids)
        self.assertEqual(complete['assembly']['left_overhang'],'TTTG');self.assertEqual(complete['assembly']['right_overhang'],'CGAA')
        self.assertNotIn('error',starter,starter.get('error'));self.assertEqual([f['id'] for f in starter['assembly']['fragments']],[self.ids[1]])
        self.assertIn('no donor',empty['error'])
        self.client.post('/api/auth/users',json={'username':'other','pin':'654321'})
        with TestClient(app) as other:
            other.post('/api/auth/login',json={'username':'other','pin':'654321'})
            self.assertEqual(other.get('/api/mrna/build-list').json()['items'],[])
        with TestClient(app) as anon:self.assertEqual(anon.get('/api/mrna/build-list').status_code,401)
        payload=complete['assembly']|{'cds_start':8,'cds_end':55,'frame':2}
        result=self.client.post('/api/mrna/assembly/preview',json=payload)
        self.assertEqual(result.status_code,200,result.text);self.assertEqual(result.json()['sequence'],CDS[3:])
        self.assertEqual(self.client.post('/api/mrna/assembly/preview',json=payload|{'frame':1}).status_code,422)

    def test_fragment_comparison_preserves_exogenous_dna_from_snapshot(self):
        for reverse in (False,True):
            p=prepare_assembly(fixture(reverse_cds=reverse,reverse_donor=True))
            sequence=synonym(p)
            response=self.client.post('/api/mrna/export/fragment-comparison',json={'assembly':p['assembly'],'sequence':sequence})
            self.assertEqual(response.status_code,200,response.text);data=response.json()
            self.assertEqual(data['before_sequence'],p['assembled_sequence']);self.assertTrue(data['non_cds_preserved'])
            for original,fragment in zip(p['assembly']['fragments'],data['fragments']):
                self.assertEqual(fragment['before_sequence'],original['sequence'])
                self.assertEqual(len(fragment['before_sequence']),len(fragment['after_sequence']))
                self.assertTrue(fragment['non_cds_preserved'])
                mutable={i for a,b in fragment['cds_regions'] for i in range(a-1,b)}
                self.assertTrue(all(a==b for i,(a,b) in enumerate(zip(fragment['before_sequence'],fragment['after_sequence'])) if i not in mutable))
            bad='GTG'+sequence[3:]
            self.assertEqual(self.client.post('/api/mrna/export/fragment-comparison',json={'assembly':p['assembly'],'sequence':bad}).status_code,422)
        with TestClient(app) as anon:self.assertEqual(anon.post('/api/mrna/export/fragment-comparison',json={'assembly':p['assembly'],'sequence':sequence}).status_code,401)


if __name__=='__main__':unittest.main()
