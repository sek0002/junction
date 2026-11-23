#!/usr/bin/env python3
"""Install the optional local RiboNN CPU predictor and published pretrained models."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
RECORD='https://zenodo.org/api/records/17258709'

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.parse_args()
    if not shutil.which('uv'):parser.error('Install uv before running this script.')
    model=ROOT/'.tools/RiboNN';runtime=ROOT/'.tools/ribonn-runtime';model.parent.mkdir(exist_ok=True)
    if not model.exists():subprocess.run(['git','clone','--depth','1','https://github.com/Sanofi-Public/RiboNN.git',str(model)],check=True)
    subprocess.run(['uv','venv','--python','3.10',str(runtime),'--allow-existing'],check=True)
    python=runtime/('Scripts/python.exe' if __import__('os').name=='nt' else 'bin/python')
    subprocess.run(['uv','pip','install','--python',str(python),'-r',str(ROOT/'requirements-ribonn.txt')],check=True)
    if not (model/'models/human/runs.csv').is_file() or not (model/'models/mouse/runs.csv').is_file():
        with urllib.request.urlopen(RECORD,timeout=30) as response:record=json.load(response)
        file=next(f for f in record['files'] if f['key']=='weights.zip')
        archive=model/'weights.zip';print('Downloading published RiboNN weights (about 198 MB).',flush=True)
        urllib.request.urlretrieve(file['links']['self'],archive)
        checksum=file['checksum'];algorithm,expected=checksum.split(':',1)
        digest=hashlib.new(algorithm)
        with archive.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        if digest.hexdigest()!=expected:raise RuntimeError('RiboNN archive checksum mismatch.')
        dest=(model/'models').resolve()
        with zipfile.ZipFile(archive) as z:
            if any(not (dest/name).resolve().is_relative_to(dest) for name in z.namelist()):raise RuntimeError('Unexpected model archive paths.')
            z.extractall(dest)
    config_path=ROOT/'.tools/mrna-config.json';config=json.loads(config_path.read_text()) if config_path.exists() else {}
    config.update(ribonn_root=str(model),ribonn_python=str(python),ribonn_command=shlex.join([str(python),str(ROOT/'scripts/ribonn_predict.py')]))
    config_path.write_text(json.dumps(config,indent=2)+'\n')
    print('RiboNN connected. Restart Junction; translation predictions require both UTRs and a terminal stop codon.')

if __name__=='__main__':main()
