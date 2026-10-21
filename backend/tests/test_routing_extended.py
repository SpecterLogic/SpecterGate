import json
import os
import subprocess

from app.database import SessionLocal
from app.services.routing import apply_to_xray


def test_basic_routing_and_protocol_rules(client, auth, tmp_path):
    policy = {'default_outbound': 'ipv4', 'block_bittorrent': True, 'block_ips': ['198.51.100.0/24'], 'block_domains': ['domain:blocked.example'], 'direct_domains': ['domain:direct.example'], 'ipv4_domains': ['domain:ipv4.example'], 'rules': [{'outbound': 'blocked', 'network': 'udp', 'port': '25,1000-2000', 'protocols': ['quic']}]}
    response = client.put('/api/routing', headers=auth, json=policy)
    assert response.status_code == 200, response.text
    config = {'outbounds': [{'tag': 'direct', 'protocol': 'freedom'}, {'tag': 'blocked', 'protocol': 'blackhole'}], 'routing': {'rules': [{'type': 'field', 'ip': ['127.0.0.0/8'], 'outboundTag': 'blocked'}]}}
    with SessionLocal() as db:
        apply_to_xray(db, config)
    assert config['outbounds'][0]['tag'] == 'ipv4'
    assert config['routing']['rules'][0]['ip'] == ['127.0.0.0/8']
    assert config['routing']['rules'][1]['protocol'] == ['bittorrent']
    assert next(rule for rule in config['routing']['rules'] if rule.get('port') == '25,1000-2000')['port'] == '25,1000-2000'
    if os.getenv('XRAY_TEST_BINARY'):
        path = tmp_path / 'routing.json'
        path.write_text(json.dumps(config), encoding='utf-8')
        result = subprocess.run([os.environ['XRAY_TEST_BINARY'], 'run', '-test', '-c', str(path)], capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stdout + result.stderr
    assert client.put('/api/routing', headers=auth, json={'rules': [{'outbound': 'blocked', 'port': '70000'}]}).status_code == 422
    assert client.put('/api/routing', headers=auth, json={}).status_code == 200
