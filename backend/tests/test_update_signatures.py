import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest


@pytest.mark.skipif(sys.platform!='linux' or not shutil.which('gpg'),reason='Linux and GPG required')
def test_updater_accepts_only_trusted_signed_tags_and_regular_requests(tmp_path):
    path=Path(__file__).resolve().parents[2]/'deploy/update_worker.py'
    spec=importlib.util.spec_from_file_location('update_worker',path)
    worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
    repo=tmp_path/'repo';repo.mkdir()
    signer=tmp_path/'signer';verifier=tmp_path/'verifier'
    signer.mkdir(mode=0o700);verifier.mkdir(mode=0o700)
    environment={**os.environ,'GNUPGHOME':str(signer),'GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_NOSYSTEM':'1'}
    def run(args,env=environment):return subprocess.run(args,env=env,check=True,capture_output=True)
    run(['gpg','--batch','--passphrase','','--quick-generate-key','Disposable Release Test','ed25519','sign','1d'])
    public=run(['gpg','--armor','--export']).stdout
    verification={**environment,'GNUPGHOME':str(verifier)}
    subprocess.run(['gpg','--batch','--import'],input=public,env=verification,check=True,capture_output=True)
    run(['git','-C',str(repo),'init','-q'])
    identity=['git','-C',str(repo),'-c','user.name=Release Test','-c','user.email=test@example.invalid']
    run([*identity,'commit','--allow-empty','-m','test'])
    run([*identity,'-c','user.signingkey=Disposable Release Test','tag','-s','v0.0.1','-m','signed test'])
    run([*identity,'tag','v0.0.2'])
    with (tmp_path/'verify.log').open('wb') as log:
        worker.verify_tag(repo,'v0.0.1',verification,log)
        with pytest.raises(subprocess.CalledProcessError):worker.verify_tag(repo,'v0.0.2',verification,log)
        with pytest.raises(ValueError):worker.verify_tag(repo,'main;echo injected',verification,log)
    normal=tmp_path/'request.json';normal.write_text(json.dumps({'auto':False,'version':'latest'}))
    assert worker.read_json(normal)['version']=='latest'
    link=tmp_path/'link.json';link.symlink_to(normal)
    assert worker.read_json(link)=={}
    fifo=tmp_path/'fifo.json';os.mkfifo(fifo)
    assert worker.read_json(fifo)=={}
