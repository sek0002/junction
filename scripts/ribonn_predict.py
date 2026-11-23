#!/usr/bin/env python3
"""Run the official RiboNN ensemble locally with JSON stdin/stdout.

Configuration comes from JUNCTION_MRNA_CONFIG (default .tools/mrna-config.json),
or RIBONN_ROOT. Run this script with the isolated RiboNN Python environment.
No input files or predictions are written to the model checkout.
"""
import contextlib
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]

def main():
    config_path=Path(os.environ.get('JUNCTION_MRNA_CONFIG',ROOT/'.tools/mrna-config.json'))
    config=json.loads(config_path.read_text()) if config_path.exists() else {}
    root=Path(os.environ.get('RIBONN_ROOT',config.get('ribonn_root',ROOT/'.tools/RiboNN'))).expanduser().resolve()
    data=json.load(sys.stdin);species={'homo-sapiens':'human','mus-musculus':'mouse'}[data['organism']]
    runs=root/'models'/species/'runs.csv'
    if not runs.is_file():raise RuntimeError('Install RiboNN trained models before enabling translation predictions.')
    if not data['utr5_sequence'] or not data['utr3_sequence']:raise ValueError('RiboNN needs both UTRs.')
    if not data['cds_sequence'].endswith(('TAA','TAG','TGA')):raise ValueError('RiboNN needs a terminal stop codon.')
    if len(data['utr5_sequence'])>1381 or len(data['cds_sequence'])+len(data['utr3_sequence'])>11937:raise ValueError('Transcript exceeds the trained RiboNN input dimensions.')
    with contextlib.redirect_stdout(sys.stderr):
        import torch
        import pandas as pd
        sys.path.insert(0,str(root))
        from src.predict import predict_using_nested_cross_validation_models
        torch.set_num_threads(2)
        # Published checkpoints can contain CUDA tensors. Load them on CPU here.
        original_load=torch.load
        def cpu_load(*args,**kwargs):
            kwargs['map_location']='cpu'
            return original_load(*args,**kwargs)
        torch.load=cpu_load
        with tempfile.TemporaryDirectory(prefix='junction-ribonn-') as directory:
            work=Path(directory);(work/'models').symlink_to(root/'models',target_is_directory=True)
            infile=work/'prediction_input.txt'
            with infile.open('w') as stream:
                writer=csv.DictWriter(stream,fieldnames=['tx_id','utr5_sequence','cds_sequence','utr3_sequence'],delimiter='\t')
                writer.writeheader();writer.writerow({'tx_id':'junction',**{k:data[k] for k in ['utr5_sequence','cds_sequence','utr3_sequence']}})
            previous=Path.cwd()
            try:
                os.chdir(work)
                predictions=predict_using_nested_cross_validation_models(str(infile),species,pd.read_csv(runs),5,batch_size=1,num_workers=0)
            finally:os.chdir(previous)
            columns=[c for c in predictions if c.startswith('predicted_')]
            scores=predictions[columns].mean(axis=0)
            score=float(scores.mean())
            if not math.isfinite(score):raise ValueError('RiboNN returned a non-finite prediction.')
            result={'translation':score,'model':f'RiboNN 1.0 / {species} / runs '+hashlib.sha256(runs.read_bytes()).hexdigest()[:12],
                    'tissue_predictions':{k:float(v) for k,v in scores.items()}}
    print(json.dumps(result,allow_nan=False))

if __name__=='__main__':main()
