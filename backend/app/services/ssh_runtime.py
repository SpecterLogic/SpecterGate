"""Rootless SSH TCP tunnelling. No shell, OS account, remote listener or file access."""
import asyncio
import hmac
import ipaddress
import logging
import struct
import uuid

import asyncssh
from fastapi import HTTPException
from app.config import settings
from app.database import SessionLocal
from app.models import Inbound, Node, VPNUser
from app.services.permissions import inbound_allowed
from app.services import vault, login_guard

logger = logging.getLogger(__name__)
listeners = {}
errors = {}
connections = set()


def host_key():
    with SessionLocal() as db:
        value = vault.get_secret(db, 'ssh_host_key')
        if value is None:
            value = asyncssh.generate_private_key('ssh-ed25519').export_private_key().decode()
            vault.put_secret(db, 'ssh_host_key', value)
            db.commit()
        return asyncssh.import_private_key(value)


def authorized(inbound_id, username, password):
    with SessionLocal() as db:
        inbound = db.get(Inbound,inbound_id)
        user = db.query(VPNUser).filter_by(username=username).first()
        if not inbound or inbound.engine != "ssh" or not inbound.is_usable or not user or user.status!='active' or not inbound_allowed(user,inbound_id):
            return None
        if not hmac.compare_digest(password.encode(),user.password.encode()):
            return None
        return user.uuid


def desired():
    with SessionLocal() as db:
        return {ib.id:(ib.listen,ib.port) for ib in db.query(Inbound).filter_by(engine='ssh',is_active=True).all() if ib.is_usable and (not ib.node_id or ib.node and ib.node.is_local)}


class Server(asyncssh.SSHServer):
    def __init__(self,inbound_id):
        self.inbound_id=inbound_id
        self.connection=None
        self.username=self.password=self.identity=None
        self.tasks=set()

    def connection_made(self,connection):
        self.connection=connection
        self.address=connection.get_extra_info('peername')[0]
        if len(connections)>=1024:
            connection.close()
        else:
            connections.add(self)

    def connection_lost(self,exc):
        connections.discard(self)
        for task in list(self.tasks):task.cancel()

    def begin_auth(self,username):
        return True

    def password_auth_supported(self):
        return True

    async def validate_password(self,username,password):
        key='ssh:'+self.address
        try:
            login_guard.check_login(key)
        except HTTPException:
            return False
        identity=await asyncio.to_thread(authorized,self.inbound_id,username,password)
        if not identity:
            login_guard.failed_login(key)
            return False
        login_guard.successful_login(key)
        self.username,self.password,self.identity=username,password,identity
        return True

    def session_requested(self):
        return False

    def server_requested(self,*args):
        return False

    def unix_connection_requested(self,*args):
        return False

    def connection_requested(self,host,port,orig_host,orig_port):
        identity=self.identity
        if not identity or len(self.tasks)>=32 or not 1<=port<=65535:
            raise asyncssh.ChannelOpenError(asyncssh.OPEN_ADMINISTRATIVELY_PROHIBITED,'Access denied')

        async def handle(reader,writer):
            task=asyncio.current_task();self.tasks.add(task)
            remote_writer=None
            transfers=[]
            try:
                current=await asyncio.to_thread(authorized,self.inbound_id,self.username,self.password)
                if current!=identity:return
                try:
                    address=ipaddress.ip_address(host)
                    destination=(b'\x01' if address.version==4 else b'\x03')+address.packed
                except ValueError:
                    encoded=host.encode('idna')
                    if not 1<=len(encoded)<=253:raise ValueError('Invalid destination')
                    destination=b'\x02'+bytes([len(encoded)])+encoded
                async with asyncio.timeout(10):
                    remote_reader,remote_writer=await asyncio.open_connection('127.0.0.1',settings.singbox_relay_port)
                    remote_writer.write(b'\x00'+uuid.UUID(identity).bytes+b'\x00\x01'+struct.pack('>H',port)+destination)
                    await remote_writer.drain()
                    # VLESS may wait for payload before emitting the response header.
                async def upstream():
                    while chunk:=await reader.read(65536):
                        remote_writer.write(chunk);await remote_writer.drain()
                async def downstream():
                    version,addon=await remote_reader.readexactly(2)
                    if version!=0:raise ValueError('Invalid relay response')
                    await remote_reader.readexactly(addon)
                    while chunk:=await remote_reader.read(65536):
                        writer.write(chunk);await writer.drain()
                async def guard():
                    while True:
                        await asyncio.sleep(1)
                        if await asyncio.to_thread(authorized,self.inbound_id,self.username,self.password)!=identity:
                            self.connection.close();return
                transfers=[asyncio.create_task(upstream()),asyncio.create_task(downstream()),asyncio.create_task(guard())]
                await asyncio.wait(transfers,return_when=asyncio.FIRST_COMPLETED)
            except (OSError,ValueError,asyncio.IncompleteReadError,TimeoutError):
                pass
            finally:
                for transfer in transfers:transfer.cancel()
                await asyncio.gather(*transfers,return_exceptions=True)
                if remote_writer:
                    remote_writer.close()
                    try:await remote_writer.wait_closed()
                    except OSError:pass
                writer.close()
                self.tasks.discard(task)
        return handle


async def run(stop):
    try:
        while not stop.is_set():
            wanted=await asyncio.to_thread(desired) if settings.xray_enabled else {}
            for key,(endpoint,listener) in list(listeners.items()):
                if wanted.get(key)!=endpoint:
                    listener.close();await listener.wait_closed();listeners.pop(key,None)
                    for client in list(connections):
                        if client.inbound_id==key:client.connection.close()
            for key,endpoint in wanted.items():
                if key in listeners:continue
                try:
                    private=await asyncio.to_thread(host_key)
                    listener=await asyncssh.create_server(lambda key=key:Server(key),*endpoint,server_host_keys=[private],encoding=None,login_timeout=15,max_auth_attempts=3)
                    listeners[key]=(endpoint,listener);errors.pop(key,None)
                except (OSError,ValueError):
                    errors[key]='SSH listener could not be started; check its bind address and port.'
            try:await asyncio.wait_for(stop.wait(),timeout=3)
            except TimeoutError:pass
    finally:
        for _,listener in listeners.values():listener.close()
        await asyncio.gather(*(listener.wait_closed() for _,listener in listeners.values()))
        for client in list(connections):client.connection.close()
        await asyncio.gather(*(client.connection.wait_closed() for client in list(connections)),return_exceptions=True)
        listeners.clear()
