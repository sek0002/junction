#!/usr/bin/env python3
"""Connect a separately licensed BASE installation to Junction's local mRNA runtime."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path,help='Path to your authorised mRNArchitect checkout')
    parser.add_argument('--python',default='3.13',help='Python 3.13 interpreter or uv version selector')
    parser.add_argument('--degscore',type=Path,help='Existing DegScore checkout; otherwise download the public model')
    args=parser.parse_args();source=args.source.expanduser().resolve()
    if not (source/'src/mrnarchitect/sequence.py').is_file():parser.error('The source must contain src/mrnarchitect/sequence.py.')
    if not shutil.which('uv'):parser.error('Install uv, then rerun this command.')
    runtime=ROOT/'.tools/mrna-runtime';runtime.parent.mkdir(exist_ok=True)
    subprocess.run(['uv','venv','--python',args.python,str(runtime),'--allow-existing'],check=True)
    python=runtime/('Scripts/python.exe' if __import__('os').name=='nt' else 'bin/python')
    subprocess.run(['uv','pip','install','--python',str(python),'-r',str(ROOT/'requirements-mrna.txt')],check=True)
    degscore=args.degscore.expanduser().resolve() if args.degscore else ROOT/'.tools/DegScore'
    if not degscore.exists():subprocess.run(['git','clone','--depth','1','https://github.com/eternagame/DegScore.git',str(degscore)],check=True)
    if not (degscore/'DegScore.py').is_file():parser.error('DegScore.py is missing from the model checkout.')
    def commit(path):
        result=subprocess.run(['git','-C',str(path),'rev-parse','HEAD'],capture_output=True,text=True)
        return result.stdout.strip() if result.returncode==0 else 'unknown'
    config_path=ROOT/'.tools/mrna-config.json'
    config=json.loads(config_path.read_text()) if config_path.exists() else {}
    config.update(source=str(source),python=str(python),degscore=str(degscore),source_commit=commit(source),degscore_commit=commit(degscore))
    config_path.write_text(json.dumps(config,indent=2)+'\n')
    print('Connected local mRNA runtime. Restart Junction to refresh model availability.')

if __name__=='__main__':main()
