#!/usr/bin/env python3
"""Start Junction without development reload, using service environment settings."""
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]


def server_options(environ=None):
    env=os.environ if environ is None else environ
    try:port=int(env.get('GOLDEN_GATE_PORT','8765'))
    except ValueError:raise ValueError('GOLDEN_GATE_PORT must be an integer from 0 to 65535.') from None
    if not 0<=port<=65535:raise ValueError('GOLDEN_GATE_PORT must be an integer from 0 to 65535.')
    return {'host':env.get('GOLDEN_GATE_HOST','127.0.0.1'),'port':port,'workers':1,
        'proxy_headers':True,'forwarded_allow_ips':env.get('GOLDEN_GATE_FORWARDED_ALLOW_IPS','127.0.0.1,::1')}


def main():
    sys.path.insert(0,str(ROOT))
    import uvicorn
    uvicorn.run('app.main:app',**server_options())


if __name__=='__main__':main()
