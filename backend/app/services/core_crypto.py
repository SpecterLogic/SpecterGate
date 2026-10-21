"""Key generation through the installed, pinned core; no shell or secret logs."""
import re
import subprocess
from app.services.xray import _binary_path


def generate(kind, server_name='example.com'):
    commands = {'vlessenc':['vlessenc'], 'mldsa65':['mldsa65'], 'ech':['tls','ech','--serverName',server_name]}
    if kind not in commands:
        raise ValueError('Unknown key type')
    binary = _binary_path()
    if not binary:
        raise RuntimeError('Install Xray before generating keys.')
    result = subprocess.run([binary,*commands[kind]],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:
        raise RuntimeError('The installed core could not generate these keys.')
    if kind == 'vlessenc':
        private = re.findall(r'"decryption"\s*:\s*"([^"]+)"',result.stdout)
        public = re.findall(r'"encryption"\s*:\s*"([^"]+)"',result.stdout)
        if not private or len(private)!=len(public):
            raise RuntimeError('Unexpected encryption key output')
        return {'vless_decryption':private[-1],'vless_encryption':public[-1]}
    if kind == 'mldsa65':
        values=dict(line.split(':',1) for line in result.stdout.splitlines() if ':' in line)
        if not values.get('Seed') or not values.get('Verify'):
            raise RuntimeError('Unexpected signature key output')
        return {'mldsa65Seed':values['Seed'].strip(),'mldsa65Verify':values['Verify'].strip()}
    lines=[line.strip() for line in result.stdout.splitlines() if line.strip()]
    values={lines[i].rstrip(':'):lines[i+1] for i in range(len(lines)-1) if lines[i].endswith(':')}
    if not values.get('ECH config list') or not values.get('ECH server keys'):
        raise RuntimeError('Unexpected ECH key output')
    return {'echServerKeys':values['ECH server keys'],'echConfigList':values['ECH config list']}
