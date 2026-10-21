from fastapi import APIRouter,Depends,HTTPException,Request
from pydantic import BaseModel,ConfigDict,Field,SecretStr
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import get_client_ip
from app.models import Admin,Inbound
from app.routers.integrations import owner_only
from app.services import cloudflare
from app.services.settings import get_setting,set_setting
from app.services.vault import put_secret,has_secret
from app.services.audit import write_audit

router=APIRouter(prefix='/integrations/cloudflare',tags=['cloudflare'])


class Config(BaseModel):
    model_config=ConfigDict(extra='forbid')
    zone_id:str=Field(pattern=r'^[0-9a-fA-F]{32}$')
    token:SecretStr|None=None
    auto_cdn:bool=False
    inbound_ids:list[int]=Field(default_factory=list,max_length=30)
    interval_hours:int=Field(default=6,ge=1,le=168)


class Record(BaseModel):
    domain:str=Field(min_length=3,max_length=253,pattern=r'^[A-Za-z0-9][A-Za-z0-9.-]+$')
    address:str=Field(max_length=45)
    proxied:bool=True


@router.get('')
def read(db:Session=Depends(get_db),_:Admin=Depends(owner_only)):
    return {**(get_setting(db,'cloudflare_config',{}) or {}),'token_configured':has_secret(db,'cloudflare_api_token')}


@router.put('')
def configure(payload:Config,request:Request,db:Session=Depends(get_db),admin:Admin=Depends(owner_only)):
    data=payload.model_dump(exclude={'token'})
    if payload.token:
        token=payload.token.get_secret_value().strip()
        if not 20<=len(token)<=512:raise HTTPException(422,'Invalid token length')
        put_secret(db,'cloudflare_api_token',token)
    set_setting(db,'cloudflare_config',data);db.commit()
    write_audit(db,admin,'configure_cloudflare','integration',None,'Cloudflare settings changed',get_client_ip(request))
    return read(db,admin)


@router.post('/record')
def upsert(payload:Record,request:Request,db:Session=Depends(get_db),admin:Admin=Depends(owner_only)):
    try:result=cloudflare.upsert(db,payload.domain,payload.address,payload.proxied)
    except ValueError as exc:raise HTTPException(502,str(exc)) from exc
    write_audit(db,admin,'cloudflare_dns','domain',payload.domain,'DNS record updated',get_client_ip(request))
    return result


@router.post('/detect-origin')
def detect(_:Admin=Depends(owner_only)):
    try:return {'address':cloudflare.detect_origin()}
    except ValueError as exc:raise HTTPException(502,str(exc)) from exc


@router.post('/scan/{inbound_id}')
def scan(inbound_id:int,request:Request,db:Session=Depends(get_db),admin:Admin=Depends(owner_only)):
    inbound=db.get(Inbound,inbound_id)
    if inbound is None:raise HTTPException(404,'Inbound not found')
    try:result=cloudflare.scan(db,inbound)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    write_audit(db,admin,'select_cdn_ip','inbound',inbound_id,'Verified CDN address selected',get_client_ip(request))
    return {'candidates':result,'measurement_origin':'server','note':'Latency at the server does not prove connectivity from client networks.'}
