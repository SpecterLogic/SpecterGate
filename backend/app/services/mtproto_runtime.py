"""One dedicated MTG FakeTLS listener per selected user; all traffic uses Xray."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import quote

from app.config import settings
from app.models import Inbound, VPNUser
from app.services.inbound_options import options
from app.services.permissions import inbound_allowed

processes = {}
errors = {}


def relay_port(inbound):
    value = options(inbound).mtproto_relay_port or 20000 + inbound.id
    if value > 65535:
        raise ValueError('Select an explicit local MTProto relay port')
    return value


def validate_ports(db):
    rows = db.query(Inbound).filter(Inbound.is_active.is_(True)).all()
    local = [row for row in rows if not row.node_id or row.node and row.node.is_local]
    reserved = {settings.singbox_relay_port, int(settings.xray_api_address.rsplit(":", 1)[-1])}
    relays = set()
    for row in local:
        if row.engine != 'mtg':continue
        value = relay_port(row)
        if value in reserved or value in relays or any(other.port == value for other in local):
            raise ValueError('MTProto relay port conflicts with a local listener; select another private relay port.')
        relays.add(value)


def credentials(inbound, user):
    domain = options(inbound).mtproto_domain
    secret = hmac.new(user.password.encode(),f'mtg:{inbound.id}:{domain}'.encode(),hashlib.sha256).digest()[:16]
    relay_password = hmac.new(user.password.encode(),f'mtg-relay:{inbound.id}'.encode(),hashlib.sha256).hexdigest()
    return 'ee' + secret.hex() + domain.encode().hex(),relay_password


def selected_user(db, inbound):
    uid = options(inbound).mtproto_user_id
    user = db.get(VPNUser,uid) if uid else None
    return user if user and user.status=='active' and inbound_allowed(user,inbound.id) else None


def stop_one(key):
    record=processes.pop(key,None)
    if record and record[1].poll() is None:
        record[1].terminate()
        try:record[1].wait(timeout=5)
        except subprocess.TimeoutExpired:
            record[1].kill();record[1].wait(timeout=5)


def stop():
    for key in list(processes):stop_one(key)


def reconcile(db):
    from app.services.xray import xray_status
    wanted={}
    validate_ports(db)
    if settings.xray_enabled and xray_status()['running']:
        for inbound in db.query(Inbound).filter_by(engine='mtg',is_active=True).all():
            if not inbound.is_usable or inbound.node_id and (not inbound.node or not inbound.node.is_local):continue
            user=selected_user(db,inbound)
            if user is None:continue
            secret,password=credentials(inbound,user)
            bind=f'[{inbound.listen}]:{inbound.port}' if ':' in inbound.listen else f'{inbound.listen}:{inbound.port}'
            proxy=f'socks5://{quote(user.uuid,safe="")}:{password}@127.0.0.1:{relay_port(inbound)}'
            text=f'concurrency = 128\nsecret = {json.dumps(secret)}\nbind-to = {json.dumps(bind)}\nprefer-ip = "only-ipv4"\n[network]\nproxies = [{json.dumps(proxy)}]\ndns = ""\n'
            import ipaddress
            try:
                if ipaddress.ip_address(inbound.listen).is_loopback:
                    text = 'public-ipv4 = "127.0.0.1"\n' + text
            except ValueError:
                pass
            wanted[inbound.id]=text
    for key,(signature,process) in list(processes.items()):
        if signature!=wanted.get(key) or process.poll() is not None:stop_one(key)
    binary=shutil.which(settings.mtg_binary)
    for key,text in wanted.items():
        if key in processes:continue
        if not binary:
            errors[key]='MTG 2.2.8 is not installed.';continue
        folder=Path(settings.xray_config_path).resolve().parent.parent/'mtg'
        folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'{key}.toml'
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as output:output.write(text)
        try:
            log_fd = os.open(path.with_suffix('.log'), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(log_fd, 'ab') as log:
                process=subprocess.Popen([binary,'run',str(path)],stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:process.wait(timeout=.3)
            except subprocess.TimeoutExpired:
                processes[key]=(text,process);errors.pop(key,None);continue
            errors[key]='MTG exited during startup; inspect the local engine log.'
        except OSError:
            errors[key]='MTG could not start.'
