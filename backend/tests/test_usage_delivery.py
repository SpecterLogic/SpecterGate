import importlib.util
from pathlib import Path
import uuid

import pytest


def test_node_usage_retry_is_idempotent(client, auth, sample_user):
    suffix = uuid.uuid4().hex[:7]
    node = client.post("/api/nodes", headers=auth, json={"name": "Receipt " + suffix, "address": "node.example.com", "port": 443}).json()
    headers = {"X-Node-Key": node["api_key"]}
    payload = {"batch_id": uuid.uuid4().hex, "entries": [{"uuid": sample_user["uuid"], "upload": 13, "download": 21}]}
    first = client.post("/api/agent/usage", headers=headers, json=payload)
    second = client.post("/api/agent/usage", headers=headers, json=payload)
    assert first.status_code == second.status_code == 200
    assert second.json()["duplicate"] is True
    user = client.get(f"/api/users/{sample_user['id']}", headers=auth).json()
    assert user["upload_bytes"] == 13
    assert user["download_bytes"] == 21


def test_agent_reuses_pending_batch_after_timeout(tmp_path):
    path = Path(__file__).resolve().parents[2] / "agent" / "spectergate_agent.py"
    spec = importlib.util.spec_from_file_location("tested_agent", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    agent = module.Agent.__new__(module.Agent)
    agent.state = {"users": {}}
    agent.state_path = tmp_path / "state.json"
    agent.query_stats = lambda: {"id": {"upload": 100, "download": 200}}
    sent = []

    def request(method, path, payload):
        sent.append(payload)
        if len(sent) == 1:
            raise TimeoutError("Response lost after the server committed")
        return {"ok": True}

    agent.request = request
    with pytest.raises(TimeoutError):
        agent.report_stats()
    agent.state = agent._load_state()
    agent.report_stats()
    assert len(sent) == 2
    assert sent[0]["batch_id"] == sent[1]["batch_id"]
    assert agent.state == {"users": {"id": {"upload": 100, "download": 200}}}
