import json
from datetime import datetime,timedelta,timezone
import httpx
from app.database import SessionLocal
from app.models import Inbound,NotificationEvent
from app.services import cloudflare,notifications
from app.services.settings import set_setting


def test_cloudflare_scoped_dns_and_failed_scan_preserves_host(client,auth,monkeypatch):
    token='test-only-cloudflare-token-not-a-real-credential'
    configured=client.put('/api/integrations/cloudflare',headers=auth,json={'zone_id':'a'*32,'token':token})
    assert configured.status_code==200 and token not in configured.text
    writes=[]
    def provider(method,url,**kwargs):
        assert url.startswith('https://api.cloudflare.com/client/v4/')
        assert kwargs['headers']['Authorization']=='Bearer '+token
        if url.endswith('/zones/'+'a'*32):result={'name':'example.com'}
        elif method=='GET':result=[{'id':'b'*32,'name':'vpn.example.com','proxied':True,'content':'1.1.1.1'}]
        else:writes.append(kwargs['json']);result=kwargs['json']
        return httpx.Response(200,json={'success':True,'result':result})
    monkeypatch.setattr(cloudflare.httpx,'request',provider)
    assert client.post('/api/integrations/cloudflare/record',headers=auth,json={'domain':'outside.invalid','address':'1.1.1.1'}).status_code==502
    assert not writes
    changed=client.post('/api/integrations/cloudflare/record',headers=auth,json={'domain':'vpn.example.com','address':'1.1.1.1'})
    assert changed.status_code==200 and writes[-1]['proxied'] is True
    inbound=client.post('/api/inbounds',headers=auth,json={'tag':'cdn-contract','remark':'CDN','port':24312,'network':'ws','protocol':'vless','security':'tls','host':'vpn.example.com','sni':'vpn.example.com'}).json()
    monkeypatch.setattr(cloudflare,'measure',lambda address,domain:{'ip':address,'latency_ms':10 if address==cloudflare.EDGES[0] else 30})
    result=client.post(f"/api/integrations/cloudflare/scan/{inbound['id']}",headers=auth)
    assert result.status_code==200 and result.json()['measurement_origin']=='server'
    with SessionLocal() as db:
        row=db.get(Inbound,inbound['id']);before=row.extra_json
        assert json.loads(before)['share_host']==cloudflare.EDGES[0]
    monkeypatch.setattr(cloudflare,'measure',lambda *args:None)
    assert client.post(f"/api/integrations/cloudflare/scan/{inbound['id']}",headers=auth).status_code==422
    with SessionLocal() as db:assert db.get(Inbound,inbound['id']).extra_json==before
    assert client.get('/api/integrations/cloudflare').status_code==401


def test_notification_queue_retries_and_deduplicates_without_external_delivery(client,monkeypatch):
    calls=[]
    monkeypatch.setattr(notifications,'send_smtp_email',lambda *args:(calls.append('attempt') or False,'retry'))
    with SessionLocal() as db:
        set_setting(db,'smtp_enabled',True);db.commit()
        notifications.enqueue(db,'test-unique-notification','Test','Test notification')
        notifications.enqueue(db,'test-unique-notification','Test','Test notification')
        db.commit()
        row=db.query(NotificationEvent).filter_by(event_key='test-unique-notification:email').one()
        notifications.deliver_pending(db)
        assert row.attempts==1 and row.delivered_at is None
        notifications.deliver_pending(db)
        assert row.attempts==1
        row.next_attempt_at=datetime.now(timezone.utc)-timedelta(seconds=1);db.commit()
        monkeypatch.setattr(notifications,'send_smtp_email',lambda *args:(True,'sent'))
        notifications.deliver_pending(db)
        db.refresh(row);assert row.delivered_at is not None and row.attempts==2
        set_setting(db,'smtp_enabled',False);db.commit()


def test_update_requests_are_owner_only_and_do_not_claim_local_installation(client,auth,monkeypatch,tmp_path):
    from app.routers import updates
    monkeypatch.setattr(updates,'DATA',tmp_path)
    monkeypatch.setattr(updates,'WORKER',tmp_path/'missing-worker')
    assert client.post('/api/updates/request',json={'version':'latest'}).status_code==401
    assert client.post('/api/updates/request',headers=auth,json={'version':'latest'}).status_code==503
    assert client.post('/api/updates/request',headers=auth,json={'version':'main;echo injected'}).status_code==422
    assert not (tmp_path/'update-request.json').exists()
