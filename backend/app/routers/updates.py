import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from fastapi import APIRouter,Depends,HTTPException,Request
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from sqlalchemy.orm import Session
from app.config import BASE_DIR,settings
from app.database import get_db
from app.deps import get_client_ip
from app.models import Admin
from app.routers.integrations import owner_only
from app.services.vault import get_secret
from app.services.audit import write_audit

router=APIRouter(prefix='/updates',tags=['updates'])
DATA=BASE_DIR/'data'
WORKER=Path('/usr/local/lib/spectergate/update_worker.py')


def read(name):
    try:
        value=json.loads((DATA/name).read_text(encoding='utf-8'))
        return value if isinstance(value,dict) else {}
    except (OSError,ValueError):return {}


def write(value):
    DATA.mkdir(parents=True,exist_ok=True)
    fd,candidate=tempfile.mkstemp(prefix='.update-request-',dir=DATA)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as output:json.dump(value,output)
        os.replace(candidate,DATA/'update-request.json')
    finally:Path(candidate).unlink(missing_ok=True)


class Config(BaseModel):
    automatic:bool=False


class UpdateRequest(BaseModel):
    version:str=Field(default='latest',pattern=r'^(latest|v[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4})$')


@router.get('')
def status(_:Admin=Depends(owner_only)):
    return {'installed':WORKER.is_file(),'current_version':settings.version,'automatic':read('update-request.json').get('auto',False),'status':read('update-status.json')}


def ready(db):
    if not WORKER.is_file():raise HTTPException(503,'Install the signed update worker on Linux first.')
    if not get_secret(db,'backup_password'):raise HTTPException(422,'Set a backup password before enabling updates.')


@router.put('')
def configure(payload:Config,request:Request,db:Session=Depends(get_db),admin:Admin=Depends(owner_only)):
    if payload.automatic:ready(db)
    value=read('update-request.json');value['auto']=payload.automatic;write(value)
    write_audit(db,admin,'configure_updates','system',None,'Automatic signed updates changed',get_client_ip(request))
    return status(admin)


@router.post('/request')
def request_update(payload:UpdateRequest,request:Request,db:Session=Depends(get_db),admin:Admin=Depends(owner_only)):
    ready(db)
    value=read('update-request.json');value.update(version=payload.version,nonce=secrets.token_hex(16));write(value)
    write_audit(db,admin,'request_update','system',payload.version,'Signed release update requested',get_client_ip(request))
    return {'ok':True,'message':'The root worker will verify the release and create an encrypted backup before installation.'}


@router.get('/backups')
def backups(_:Admin=Depends(owner_only)):
    folder=DATA/'update-backups'
    return [{'name':file.name,'bytes':file.stat().st_size} for file in sorted(folder.glob('spectergate-*.sgbackup'),reverse=True) if file.is_file() and not file.is_symlink()]


@router.get('/backups/{filename}')
def download_backup(filename:str,_:Admin=Depends(owner_only)):
    if not re.fullmatch(r'spectergate-[0-9]{8}T[0-9]{6}Z\.sgbackup',filename):raise HTTPException(404,'Backup not found')
    path=DATA/'update-backups'/filename
    if path.is_symlink() or not path.is_file():raise HTTPException(404,'Backup not found')
    return FileResponse(path,filename=filename,media_type='application/octet-stream')
