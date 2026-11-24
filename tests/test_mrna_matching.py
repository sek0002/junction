"""Shared physical donors, joint constraints, strand mapping and job wiring."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from Bio.Seq import Seq
from fastapi.testclient import TestClient
from pydantic import ValidationError
from app import database as store
from app.main import app
from app.mrna import Batch,Parameters,Record,invoke,runtime_config
from app.mrna_fragments import prepare_assembly,project_fragments
from app.mrna_matching import donor_sites,donor_sequence,apply_donor,match_batch,fragment_library
from auth_client import bootstrap_pin
from test_mrna_fragments import fixture


def translate(dna):return str(Seq(dna).translate())

def batch_fixture():
    records=[]
    for name,reverse,species in [('A',False,'homo-sapiens'),('B',True,'mus-musculus')]:
        p=prepare_assembly(fixture(reverse_donor=reverse))
        params=Parameters(organism=species,gc_global_min=0,gc_global_max=1,gc_window_min=0,
            gc_window_max=1,avoid_repeat_length=None,avoid_poly_a=None,avoid_poly_t=None,
            avoid_poly_c=None,avoid_poly_g=None)
        records.append(Record(name=name,sequence=p['sequence'],assembly=p['assembly'],parameters=params))
    return Batch(mode='design',match_fragments=True,records=records,parameters=records[0].parameters).model_dump()


def solver(strict=False):
    immutable={i for a,b in prepare_assembly(fixture())['preserve_regions'] for i in range(a-1,b)}
    def solve(sequence,params,locks,seed):
        locked={i for a,b in locks for i in range(a-1,b)};dna=list(sequence)
        preferred='GCC' if params['organism']=='homo-sapiens' else 'GCG'
        for pos in range(0,len(sequence),3):
            if translate(sequence[pos:pos+3])=='A' and not locked.intersection(range(pos,pos+3)):
                dna[pos:pos+3]=preferred
        result=''.join(dna)
        if strict and any(translate(result[i:i+3])=='A' and i not in immutable and result[i:i+3]!=preferred for i in range(0,len(result),3)):
            raise ValueError('No shared codon satisfies this construct constraint.')
        return {'sequence':result,'report':{'status':'success','solution':{'constraints_summary':'Passed'}}}
    return solve


def metric(sequence,params):
    preferred='GCC' if params['organism']=='homo-sapiens' else 'GCG'
    codons=[sequence[i:i+3] for i in range(0,len(sequence),3) if translate(sequence[i:i+3])=='A']
    return .5+.5*sum(c==preferred for c in codons)/len(codons)


class MatchingTests(unittest.TestCase):
    def test_boundaries_are_required(self):
        for change in ({'mode':'compare'},{'records':batch_fixture()['records'][:1]},
                       {'records':[{'name':'Plain A','sequence':'ATGGCTTAA'},{'name':'Plain B','sequence':'ATGGCCTAA'}]}):
            with self.assertRaises(ValidationError):Batch(**(batch_fixture()|change))

    def test_reverse_donors_share_a_template_and_round_trip(self):
        batch=batch_fixture();a,b=[donor_sites(r,translate) for r in batch['records']]
        self.assertEqual([s['template'] for s in a],[s['template'] for s in b])
        self.assertNotEqual(a[1]['reverse_complement'],b[1]['reverse_complement'])
        for record,sites in zip(batch['records'],(a,b)):
            for site in sites:
                sequence=donor_sequence(site,record['sequence'])
                self.assertEqual(apply_donor(site,sequence,record['sequence']),record['sequence'])
        library=fragment_library(batch['records'],[r['sequence'] for r in batch['records']])
        self.assertEqual(len(library),2);self.assertTrue(all(e['shared'] for e in library))

    def test_joint_design_reuses_donors_and_retains_previous_matches(self):
        batch=batch_fixture();original=deepcopy(batch)
        result=match_batch(batch,solve=solver(),translate=translate,metric=metric)
        self.assertEqual(batch,original);self.assertEqual(result['errors'],[])
        report=result['report'];self.assertEqual(report['accepted_groups'],2)
        self.assertEqual(report['independent_unique_fragments'],4);self.assertEqual(report['matched_unique_fragments'],2)
        self.assertEqual(report['fragments_saved'],2)
        self.assertTrue(all(len({u['input_name'] for u in f['usages']})==2 for f in report['library']))
        for record,sequence in zip(batch['records'],result['sequences']):
            self.assertEqual(translate(sequence),translate(record['sequence']))
            for a,b in record['preserve_regions']:self.assertEqual(sequence[a-1:b],record['sequence'][a-1:b])
            for f in project_fragments(record['assembly'],sequence)['fragments']:self.assertTrue(f['non_cds_preserved'])
        repeat=match_batch(batch,solve=solver(),translate=translate,metric=metric)
        self.assertEqual(repeat['sequences'],result['sequences'])

    def test_different_preservation_masks_can_reuse_a_compatible_donor(self):
        batch=batch_fixture();batch['records'][0]['preserve_regions'].append([4,6])
        result=match_batch(batch,solve=solver(),translate=translate,metric=metric)
        self.assertEqual(result['sequences'][0][3:6],batch['records'][0]['sequence'][3:6])
        self.assertEqual(result['report']['matched_unique_fragments'],2)
        self.assertTrue(all(d['accepted'] for d in result['report']['decisions']))

    def test_incompatible_constraints_keep_independent_designs(self):
        result=match_batch(batch_fixture(),solve=solver(strict=True),translate=translate,metric=metric)
        self.assertEqual(result['report']['accepted_groups'],0)
        self.assertEqual(result['report']['fragments_saved'],0)
        self.assertEqual(result['report']['matched_unique_fragments'],4)
        self.assertTrue(all(not d['accepted'] and d['reason'] for d in result['report']['decisions']))
        self.assertEqual(result['errors'],[])

    def test_budget_does_not_claim_uncomputed_records(self):
        result=match_batch(batch_fixture(),solve=solver(),translate=translate,metric=metric,max_solves=1)
        self.assertTrue(result['report']['search_limit_reached']);self.assertEqual(result['report']['optimiser_calls'],1)
        self.assertIsNone(result['sequences'][1]);self.assertEqual(result['errors'][0]['name'],'B')
        self.assertTrue(all(u['input_name']=='A' for f in result['report']['library'] for u in f['usages']))

    @unittest.skipUnless(Path(runtime_config()['python']).is_file(),'Optional scientific runtime')
    def test_native_matching_and_rescoring(self):
        batch=batch_fixture();result=invoke({'action':'match','batch':batch},timeout=120)
        self.assertFalse(result['errors']);self.assertEqual(result['report']['shared_fragment_count'],2)
        for index,record in enumerate(batch['records']):
            output=invoke({'action':'run','batch':batch,'record':record,'index':index,
                'matched_sequence':result['sequences'][index],'matched_report':result['optimization_reports'][index]})
            self.assertFalse(output['errors']);before,after=output['rows']
            self.assertEqual(before['strategy'],'input');self.assertTrue(after['strategy'].startswith('Matched '))
            self.assertEqual(before['protein'],after['protein']);self.assertTrue(after['metrics']['protein_preserved'])
            self.assertEqual(after['cds'],result['sequences'][index]);self.assertTrue(after['fragment_output']['junctions_preserved'])


class MatchingJobTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.previous=os.environ.get('GOLDEN_GATE_DB')
        os.environ['GOLDEN_GATE_DB']=str(Path(self.folder.name)/'match.sqlite3');store.initialize()
        self.client=TestClient(app);self.client.post('/api/auth/login',json={'username':'admin','pin':bootstrap_pin()})
    def tearDown(self):
        self.client.close()
        if self.previous is None:os.environ.pop('GOLDEN_GATE_DB',None)
        else:os.environ['GOLDEN_GATE_DB']=self.previous
        self.folder.cleanup()
    def terminal(self,identifier):
        for _ in range(100):
            item=self.client.get('/api/mrna/jobs/'+identifier).json()
            if item['status'] not in ('queued','running'):return item
            time.sleep(.02)
        self.fail('Job did not finish')
    def test_matching_job_plans_once_and_scores_each_final_cds(self):
        batch=batch_fixture();plan=match_batch(batch,solve=solver(),translate=translate,metric=metric);calls=[]
        def fake(payload,*args,**kwargs):
            calls.append(payload)
            if payload['action']=='match':return plan
            return {'rows':[{'id':str(payload['index']),'strategy':'Matched CAI','cds':payload['matched_sequence']}],'errors':[]}
        with patch('app.mrna.capabilities',return_value={'ready':True}),patch('app.mrna.invoke',side_effect=fake):
            response=self.client.post('/api/mrna/jobs',json=batch);self.assertEqual(response.status_code,202,response.text)
            item=self.terminal(response.json()['id'])
        self.assertEqual(item['status'],'complete');self.assertEqual([c['action'] for c in calls],['match','run','run'])
        self.assertEqual(item['result']['fragment_matches']['fragments_saved'],2)
        self.assertEqual(item['completed'],2)
    def test_cancel_during_joint_search(self):
        entered=threading.Event();release=threading.Event()
        def wait(*args,**kwargs):entered.set();release.wait(3);raise RuntimeError('Stopped')
        with patch('app.mrna.capabilities',return_value={'ready':True}),patch('app.mrna.invoke',side_effect=wait):
            response=self.client.post('/api/mrna/jobs',json=batch_fixture());self.assertEqual(response.status_code,202)
            identifier=response.json()['id'];self.assertTrue(entered.wait(2))
            self.client.post('/api/mrna/jobs/'+identifier+'/cancel',json={});release.set()
            self.assertEqual(self.terminal(identifier)['status'],'cancelled')
