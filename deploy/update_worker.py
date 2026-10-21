#!/usr/bin/env python3
"""Root-owned updater. Accepts only signed stable tags from the fixed repository."""
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.request

APP = Path('/opt/spectergate')
DATA = APP/'backend/data'
TRUST = Path('/etc/spectergate/releases.pub')
TAG = re.compile(r'^v[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$')
STATUS = DATA/'update-status.json'


def read_json(path):
    try:
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):return {}
            value=json.loads(stream.read(4097))
            return value if isinstance(value,dict) else {}
    except (OSError,ValueError,RecursionError):return {}


def state(stage,nonce='',version=None):
    fd,name=tempfile.mkstemp(prefix='.update-status-',dir=DATA)
    try:
        with os.fdopen(fd,'w') as output:
            json.dump({'stage':stage,'nonce':nonce,'version':version,'checked_at':time.time()},output)
        os.chmod(name,0o644)
        os.replace(name,STATUS)
    finally:Path(name).unlink(missing_ok=True)


def verify_tag(repository,tag,environment,log):
    if not TAG.fullmatch(tag):raise ValueError('Only stable semantic version tags are allowed')
    subprocess.run(['git','-C',str(repository),'verify-tag',tag],env=environment,stdout=log,stderr=log,check=True,timeout=30)


def readable_tree(folder,private_web=False):
    # The worker has umask 077; published code/assets must remain readable by
    # the unprivileged application and web server after rsync preserves modes.
    for directory,folders,files in os.walk(folder,followlinks=False):
        folders[:]=[name for name in folders if name!='.git']
        target=Path(directory)
        os.chmod(target,0o750 if private_web else 0o755)
        if private_web:shutil.chown(target,group='www-data')
        for name in files:
            path=target/name
            if path.is_symlink():continue
            executable=bool(path.stat().st_mode&0o111)
            os.chmod(path,(0o750 if executable else 0o640) if private_web else (0o755 if executable else 0o644))
            if private_web:shutil.chown(path,group='www-data')


def update():
    request=read_json(DATA/'update-request.json')
    previous=read_json(STATUS)
    manual=bool(request.get('nonce')) and request.get('nonce')!=previous.get('nonce')
    if not manual and (request.get('auto') is not True or time.time()-previous.get('checked_at',0)<86400):return
    nonce=str(request.get('nonce',''))[:64]
    selected=request.get('version','latest')
    if selected!='latest' and (not isinstance(selected,str) or not TAG.fullmatch(selected)):
        state('invalid-request',nonce);return
    if not TRUST.is_file():
        state('missing-release-key',nonce);return
    root=Path('/var/lib/spectergate-updater')
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    os.chmod(root,0o700)
    old_venv=root/'previous-venv'
    rollback=root/'rollback'
    stopped=False
    with tempfile.TemporaryDirectory(prefix='candidate-',dir=root) as directory, (root/'update.log').open('ab') as log:
        os.chmod(root/'update.log',0o600)
        work=Path(directory)
        source=work/'source';source.mkdir()
        environment={**os.environ,'GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0','GNUPGHOME':str(work/'gnupg')}
        Path(environment['GNUPGHOME']).mkdir(mode=0o700)
        def run(args,cwd=None,timeout=600):
            subprocess.run([str(arg) for arg in args],cwd=cwd,env=environment,stdout=log,stderr=log,check=True,timeout=timeout)
        def sync(origin,destination,extra=()):
            run(['rsync','-a','--delete',*extra,str(origin)+'/',str(destination)+'/'])
        exclusions=['--exclude=.git','--exclude=backend/.env','--exclude=backend/data','--exclude=backend/.venv','--exclude=frontend/node_modules','--exclude=frontend/dist','--exclude=frontend/dist-private']
        try:
            state('checking-signature',nonce)
            run(['gpg','--batch','--import',TRUST],timeout=30)
            run(['git','-C',source,'init','-q'])
            run(['git','-C',source,'remote','add','origin','https://github.com/SpecterLogic/SpecterGate.git'])
            run(['git','-C',source,'fetch','--depth=1','--tags','origin'],timeout=180)
            if selected=='latest':
                tags=subprocess.check_output(['git','-C',str(source),'tag','--sort=-version:refname'],env=environment,text=True).splitlines()
                selected=next((tag for tag in tags if TAG.fullmatch(tag)),None)
                if selected is None:
                    state('no-stable-release',nonce);return
            verify_tag(source,selected,environment,log)
            current=(APP/'VERSION').read_text().strip()
            if not manual and tuple(map(int,selected[1:].split('.'))) < tuple(map(int,current.split('.'))):
                state('up-to-date',nonce,'v'+current);return
            if selected=='v'+current:
                state('up-to-date',nonce,selected);return
            run(['git','-C',source,'checkout','--detach',selected])
            readable_tree(source)
            if (source/'VERSION').read_text().strip()!=selected[1:]:raise ValueError('Release version mismatch')
            state('building',nonce,selected)
            run(['python3','-m','venv',work/'venv'])
            run([work/'venv/bin/pip','install','-r',source/'backend/requirements.txt'],timeout=1200)
            run(['npm','ci'],cwd=source/'frontend',timeout=1200)
            run(['npm','run','build'],cwd=source/'frontend',timeout=600)
            access=read_json(Path('/etc/spectergate/panel-access.json'))
            private_key=access.get('path')
            if private_key:
                if not re.fullmatch(r'[A-Za-z0-9_-]{12,128}',private_key):raise ValueError('Invalid management path')
                run(['npm','run','build','--','--base','/'+private_key+'/','--outDir','dist-private'],cwd=source/'frontend')
            run(['bash',source/'backend/core/build.sh',work/'xray'],timeout=1800)
            run(['python3',source/'backend/core/install_engine.py','singbox',work/'sing-box'],timeout=180)
            run(['python3',source/'backend/core/install_engine.py','mtg',work/'mtg'],timeout=180)
            readable_tree(work/'venv')
            readable_tree(source/'frontend/dist')
            if private_key:readable_tree(source/'frontend/dist-private',private_web=True)
            state('backing-up',nonce,selected)
            # Database/env parsing and backup creation run with service privileges.
            run(['runuser','-u','spectergate','--',APP/'backend/.venv/bin/python','-m','app.update_backup'],cwd=APP/'backend',timeout=180)
            sync(APP,rollback,exclusions)
            previous_binaries=root/'previous-binaries'
            previous_binaries.mkdir(exist_ok=True)
            for binary in ('xray','sing-box','mtg'):
                current_binary=Path('/usr/local/bin')/binary
                if current_binary.is_file():shutil.copy2(current_binary,previous_binaries/binary)
            sync('/var/www/spectergate',root/'previous-web')
            if private_key:sync('/var/www/spectergate-admin/'+private_key,root/'previous-admin')
            state('installing',nonce,selected)
            run(['systemctl','stop','spectergate']);stopped=True
            if old_venv.exists():shutil.rmtree(old_venv)
            shutil.move(str(APP/'backend/.venv'),str(old_venv))
            sync(source,APP,exclusions)
            shutil.move(str(work/'venv'),str(APP/'backend/.venv'))
            # Rewrite only generated Python entrypoint shebangs. No downloads
            # or package installation occur while the service is stopped.
            for entry in (APP/'backend/.venv/bin').iterdir():
                if entry.is_symlink() or not entry.is_file():continue
                content=entry.read_bytes()
                if content.startswith(b'#!') or entry.name.startswith('activate'):
                    entry.write_bytes(content.replace(str(work/'venv').encode(),str(APP/'backend/.venv').encode()))
            for name in ('xray','sing-box','mtg'):
                os.chmod(work/name,0o755)
                shutil.copy2(work/name,Path('/usr/local/bin')/('.sg-'+name))
                os.replace(Path('/usr/local/bin')/('.sg-'+name),Path('/usr/local/bin')/name)
            sync(source/'frontend/dist','/var/www/spectergate')
            if private_key:sync(source/'frontend/dist-private','/var/www/spectergate-admin/'+private_key)
            run(['systemctl','start','spectergate'])
            for _ in range(30):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=2) as response:
                        if response.status==200:break
                except OSError:time.sleep(1)
            else:raise RuntimeError('Updated service did not become healthy')
            shutil.copy2(source/'deploy/releases.pub',TRUST)
            shutil.copy2(source/'deploy/update_worker.py','/usr/local/lib/spectergate/update_worker.py')
            state('complete',nonce,selected)
        except Exception:
            if stopped and rollback.is_dir():
                try:
                    run(['systemctl','stop','spectergate'])
                    sync(rollback,APP,exclusions)
                    if old_venv.exists():
                        shutil.rmtree(APP/'backend/.venv',ignore_errors=True)
                        shutil.move(str(old_venv),str(APP/'backend/.venv'))
                    for binary in ('xray','sing-box','mtg'):
                        saved=root/'previous-binaries'/binary
                        if saved.is_file():
                            target=Path('/usr/local/bin')/('.sg-rollback-'+binary)
                            shutil.copy2(saved,target)
                            os.replace(target,Path('/usr/local/bin')/binary)
                    sync(root/'previous-web','/var/www/spectergate')
                    if private_key:sync(root/'previous-admin','/var/www/spectergate-admin/'+private_key)
                    run(['systemctl','start','spectergate'])
                except Exception:pass
            state('failed-preserved-or-rolled-back',nonce,selected)


if __name__=='__main__':
    if os.geteuid()!=0:raise SystemExit('Root service required')
    lock_dir=Path('/run/spectergate-updater')
    lock_dir.mkdir(mode=0o700,exist_ok=True)
    with (lock_dir/'update.lock').open('w') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit(0)
        update()
