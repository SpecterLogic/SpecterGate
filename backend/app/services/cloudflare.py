"""Scoped Cloudflare DNS integration and certificate-verified CDN measurements."""
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import socket
import ssl
import time

import httpx
from app.models import Inbound
from app.services.settings import get_setting, set_setting
from app.services.vault import get_secret
from app.services.inbound_options import options

BASE = 'https://api.cloudflare.com/client/v4'
EDGES = ['104.16.0.1','104.17.0.1','172.64.0.1','162.159.128.1']


def request(db, method, path, **kwargs):
    token=get_secret(db,'cloudflare_api_token')
    if not token:raise ValueError('Configure a scoped Cloudflare token first.')
    try:
        result=httpx.request(method,BASE+path,headers={'Authorization':'Bearer '+token},timeout=12,follow_redirects=False,**kwargs)
        payload=result.json()
        if not result.is_success or payload.get('success') is not True:
            raise ValueError('Cloudflare rejected the operation. Check the zone, DNS record and token permissions.')
        return payload['result']
    except (httpx.HTTPError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError('Cloudflare could not be reached or returned an invalid response.') from exc


def zone(db, domain):
    config=get_setting(db,'cloudflare_config',{}) or {}
    zid=config.get('zone_id','')
    import re
    if not re.fullmatch(r'[0-9a-fA-F]{32}',zid):raise ValueError('Configure a valid Cloudflare zone ID.')
    result=request(db,'GET','/zones/'+zid)
    if not isinstance(result,dict) or not isinstance(result.get('name'),str):raise ValueError('Invalid zone response')
    name=result['name'].lower().rstrip('.')
    domain=domain.lower().rstrip('.')
    if domain!=name and not domain.endswith('.'+name):
        raise ValueError('The requested domain is outside the configured zone.')
    return zid


def upsert(db, domain, address, proxied):
    zid=zone(db,domain)
    ip=ipaddress.ip_address(address)
    if not ip.is_global:raise ValueError('A public origin address is required.')
    kind='A' if ip.version==4 else 'AAAA'
    records=request(db,'GET',f'/zones/{zid}/dns_records',params={'name':domain,'type':kind})
    if len(records)>1:raise ValueError('Several matching records exist; choose and consolidate them in Cloudflare first.')
    data={'type':kind,'name':domain,'content':str(ip),'proxied':proxied,'ttl':1}
    path=f'/zones/{zid}/dns_records'
    if records:
        import re
        rid=records[0]['id']
        if not re.fullmatch(r'[0-9a-fA-F]{32}',rid):raise ValueError('Invalid DNS record response')
        result=request(db,'PUT',path+'/'+rid,json=data)
    else:
        result=request(db,'POST',path,json=data)
    if result.get('content')!=str(ip) or result.get('proxied') is not proxied:
        raise ValueError('Cloudflare did not confirm the requested DNS state.')
    return {'name':domain,'address':str(ip),'proxied':proxied}


def detect_origin():
    try:
        response=httpx.get('https://www.cloudflare.com/cdn-cgi/trace',timeout=8,follow_redirects=False)
        response.raise_for_status()
        values=dict(line.split('=',1) for line in response.text.splitlines() if '=' in line)
        ip=ipaddress.ip_address(values['ip'])
        if not ip.is_global:raise ValueError('No public address detected')
        return str(ip)
    except (httpx.HTTPError,ValueError,KeyError) as exc:
        raise ValueError('Could not detect this server public address.') from exc


def measure(address, domain):
    started=time.monotonic()
    try:
        context=ssl.create_default_context()
        with socket.create_connection((address,443),timeout=3) as raw,context.wrap_socket(raw,server_hostname=domain) as connection:
            connection.sendall(f'GET /cdn-cgi/trace HTTP/1.1\r\nHost: {domain}\r\nConnection: close\r\n\r\n'.encode('ascii'))
            data=b''
            while len(data)<32768:
                chunk=connection.recv(4096)
                if not chunk:break
                data+=chunk
            if not data.startswith((b'HTTP/1.1 200',b'HTTP/1.0 200')) or b'ip=' not in data:
                return None
        return {'ip':address,'latency_ms':round((time.monotonic()-started)*1000,1)}
    except (OSError,ValueError):
        return None


def scan(db,inbound):
    domain=inbound.host or inbound.sni
    if not domain or inbound.network not in {'ws','xhttp','httpupgrade','grpc'} or inbound.security!='tls' or inbound.engine!='xray':
        raise ValueError('Select an Xray TLS inbound with a CDN-compatible transport, SNI and Host domain.')
    zid=zone(db,domain)
    records=request(db,'GET',f'/zones/{zid}/dns_records',params={'name':domain})
    if not any(row.get('proxied') for row in records):
        raise ValueError('The domain must have a proxied DNS record in this zone.')
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=[row for row in pool.map(lambda ip:measure(ip,domain),EDGES) if row]
    if not results:raise ValueError('No candidate passed certificate and HTTP checks; the previous address was preserved.')
    results.sort(key=lambda row:row['latency_ms'])
    cfg=options(inbound)
    cfg.share_host=results[0]['ip'];cfg.share_port=443
    inbound.extra_json=cfg.model_dump_json()
    set_setting(db,'cdn_scan_'+str(inbound.id),{'at':time.time(),'best':results[0],'candidates':results})
    db.commit()
    return results


async def run(stop):
    import asyncio
    from app.database import SessionLocal
    def reconcile():
        with SessionLocal() as db:
            config=get_setting(db,'cloudflare_config',{}) or {}
            if not config.get('auto_cdn'):return
            for ident in config.get('inbound_ids',[]):
                previous=get_setting(db,'cdn_scan_'+str(ident),{}) or {}
                if time.time()-previous.get('at',0)<config.get('interval_hours',6)*3600:continue
                inbound=db.get(Inbound,ident)
                if inbound is None or not inbound.is_usable:continue
                try:scan(db,inbound)
                except ValueError:
                    db.rollback()  # Keep the last verified address; retry at the next scheduled interval.
                    set_setting(db,'cdn_scan_'+str(ident),{**previous,'at':time.time(),'failed':True})
                    db.commit()
    while not stop.is_set():
        try:await asyncio.to_thread(reconcile)
        except Exception:pass
        try:await asyncio.wait_for(stop.wait(),timeout=60)
        except TimeoutError:pass
