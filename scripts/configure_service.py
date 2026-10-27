#!/usr/bin/env python3
"""Choose a free port once and write a persistent systemd environment file."""
import argparse
import os
from pathlib import Path
import socket


def choose_port(host):
    with socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET,socket.SOCK_STREAM) as listener:
        listener.bind((host,0))
        return listener.getsockname()[1]


def environment_text(host,port):
    if not host or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:-_' for c in host):
        raise ValueError('Host must be an IP address or hostname.')
    if not 0<=port<=65535:raise ValueError('Port must be between 0 and 65535.')
    return (f'GOLDEN_GATE_HOST={host}\nGOLDEN_GATE_PORT={port}\n'
        'GOLDEN_GATE_DB=/var/lib/junction/golden_gate.sqlite3\n'
        'GOLDEN_GATE_FORWARDED_ALLOW_IPS=127.0.0.1,::1\n')


def configure(path,host='127.0.0.1',port='auto'):
    path=Path(path)
    if path.exists():return False
    selected=choose_port(host) if port=='auto' else int(port)
    text=environment_text(host,selected)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(text)
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('/etc/junction/junction.env'))
    parser.add_argument('--host',default='127.0.0.1')
    parser.add_argument('--port',default='auto',help='auto chooses once; 0 chooses a new available port at every start')
    args=parser.parse_args()
    try:
        made=configure(args.output,args.host,args.port)
    except (ValueError,OSError) as error:parser.exit(1,str(error)+'\n')
    print(('Created ' if made else 'Kept existing ')+str(args.output))


if __name__=='__main__':main()
