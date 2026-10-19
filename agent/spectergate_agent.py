#!/usr/bin/env python3
"""SpecterGate node agent.

Pulls the node-specific Xray configuration from the panel, validates it, runs
Xray, and reports heartbeat plus per-user traffic. It intentionally depends only
on the Python standard library so it can run on a minimal server.

Environment:
  SPECTERGATE_PANEL_URL      e.g. https://panel.example.com
  SPECTERGATE_NODE_KEY       node API key from the Nodes page
  SPECTERGATE_XRAY_BINARY    default: xray
  SPECTERGATE_AGENT_CONFIG   default: /etc/spectergate/xray.json
  SPECTERGATE_AGENT_STATE    default: /var/lib/spectergate-agent/state.json
  SPECTERGATE_AGENT_LOG      default: /var/log/spectergate-agent.log
  SPECTERGATE_XRAY_API       default: 127.0.0.1:10085
  SPECTERGATE_XRAY_ASSET     optional geoip/geosite directory
  SPECTERGATE_AGENT_INTERVAL default: 60
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from uuid import uuid4
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{stamp}] {message}", flush=True)


class Agent:
    def __init__(self) -> None:
        self.panel_url = os.environ.get("SPECTERGATE_PANEL_URL", "").rstrip("/")
        self.node_key = os.environ.get("SPECTERGATE_NODE_KEY", "")
        if not self.panel_url or not self.node_key:
            raise SystemExit("SPECTERGATE_PANEL_URL and SPECTERGATE_NODE_KEY are required")
        self.xray = os.environ.get("SPECTERGATE_XRAY_BINARY", "xray")
        self.config_path = Path(os.environ.get("SPECTERGATE_AGENT_CONFIG", "/etc/spectergate/xray.json"))
        self.state_path = Path(os.environ.get("SPECTERGATE_AGENT_STATE", "/var/lib/spectergate-agent/state.json"))
        self.log_path = Path(os.environ.get("SPECTERGATE_AGENT_LOG", "/var/log/spectergate-agent.log"))
        self.api_address = os.environ.get("SPECTERGATE_XRAY_API", "127.0.0.1:10085")
        self.asset_dir = os.environ.get("SPECTERGATE_XRAY_ASSET", "")
        self.interval = max(20, int(os.environ.get("SPECTERGATE_AGENT_INTERVAL", "60")))
        self.process: subprocess.Popen | None = None
        self.config_hash = ""
        self.running = True
        self._cpu_prev: tuple[int, int] | None = None
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    # ---------------- HTTP ----------------
    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = f"{self.panel_url}{path}"
        body = None
        headers = {
            "X-Node-Key": self.node_key,
            "Accept": "application/json",
            "User-Agent": "spectergate-agent/0.1",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    # ---------------- host metrics ----------------
    def host_metrics(self) -> tuple[float, float]:
        cpu = 0.0
        memory = 0.0
        try:
            fields = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
            values = [int(value) for value in fields]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            total = sum(values)
            if self._cpu_prev:
                total_delta = total - self._cpu_prev[0]
                idle_delta = idle - self._cpu_prev[1]
                if total_delta > 0:
                    cpu = round(100 * (1 - idle_delta / total_delta), 1)
            self._cpu_prev = (total, idle)
        except (OSError, ValueError, IndexError):
            pass
        try:
            meminfo = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, value = line.split(":", 1)
                meminfo[key] = int(value.strip().split()[0])
            total = meminfo.get("MemTotal", 0)
            available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
            if total:
                memory = round(100 * (1 - available / total), 1)
        except (OSError, ValueError):
            pass
        return max(0.0, min(100.0, cpu)), max(0.0, min(100.0, memory))

    # ---------------- process ----------------
    def _xray_env(self) -> dict:
        env = os.environ.copy()
        if self.asset_dir:
            env["XRAY_LOCATION_ASSET"] = self.asset_dir
        return env

    def start_xray(self) -> None:
        if self.process and self.process.poll() is None:
            return
        self._flush_pending()
        with self.log_path.open("a", encoding="utf-8") as log_handle:
            self.process = subprocess.Popen(
                [self.xray, "run", "-c", str(self.config_path)],
                stdout=log_handle, stderr=subprocess.STDOUT,
                cwd=str(self.config_path.parent), env=self._xray_env(),
            )
        self.state = {"users": {}}
        self._save_state()
        time.sleep(1)
        if self.process.poll() is not None:
            raise RuntimeError("Xray exited immediately after start; check the agent log.")
        log(f"Xray started with pid {self.process.pid}")

    def stop_xray(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
            log("Xray stopped")
        self.process = None

    def validate(self, path: Path) -> None:
        result = subprocess.run(
            [self.xray, "run", "-test", "-c", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            env=self._xray_env(),
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip()[:1000])

    def apply_config(self, config: dict, expected_hash: str) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".spectergate-", suffix=".json", dir=self.config_path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(config, handle, ensure_ascii=False, indent=2)
            os.chmod(temp_path, 0o600)
            self.validate(temp_path)
            was_running = bool(self.process and self.process.poll() is None)
            if was_running:
                self.report_stats()
                self.stop_xray()
            os.replace(temp_path, self.config_path)
            self.config_hash = expected_hash
            log("Validated and installed a new Xray config")
            self.start_xray()
        finally:
            if temp_path.exists():
                temp_path.unlink()

    # ---------------- stats ----------------
    def _load_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"users": {}}

    def _save_state(self) -> None:
        temp_path = self.state_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_path, self.state_path)

    def query_stats(self) -> dict[str, dict[str, int]]:
        command = [
            self.xray,
            "api",
            "statsquery",
            f"--server={self.api_address}",
            "-pattern",
            "",
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, env=self._xray_env())
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip()[:500])
        payload = json.loads(result.stdout or "{}")
        totals: dict[str, dict[str, int]] = {}
        for item in payload.get("stat", []):
            name = str(item.get("name", ""))
            try:
                value = int(item.get("value", 0))
            except (TypeError, ValueError):
                continue
            parts = name.split(">>>")
            if len(parts) != 4 or parts[0] != "user":
                continue
            user = totals.setdefault(parts[1], {"upload": 0, "download": 0})
            if parts[3] == "uplink":
                user["upload"] += value
            elif parts[3] == "downlink":
                user["download"] += value
        return totals

    def _flush_pending(self) -> None:
        pending = self.state.get("pending")
        if pending:
            self.request("POST", "/api/agent/usage", {"batch_id": pending["batch_id"], "entries": pending["entries"]})
            self.state = {"users": pending["users"]}
            self._save_state()

    def report_stats(self) -> None:
        self._flush_pending()
        current = self.query_stats()
        previous = self.state.get("users", {})
        entries = []
        updated = {}
        for uuid, values in current.items():
            old = previous.get(uuid, {})
            upload = values["upload"] - int(old.get("upload", 0))
            download = values["download"] - int(old.get("download", 0))
            # Xray counters reset when the process restarts.
            if upload < 0:
                upload = values["upload"]
            if download < 0:
                download = values["download"]
            if upload > 0 or download > 0:
                entries.append({"uuid": uuid, "upload": upload, "download": download})
            updated[uuid] = values
        if entries:
            self.state["pending"] = {"batch_id": uuid4().hex, "entries": entries, "users": updated}
            self._save_state()
            self._flush_pending()
            log(f"Reported traffic for {len(entries)} users")
        self.state = {"users": updated}
        self._save_state()

    # ---------------- main loop ----------------
    def cycle(self) -> None:
        cpu, memory = self.host_metrics()
        self.request(
            "POST",
            "/api/agent/heartbeat",
            {"cpu_usage": cpu, "memory_usage": memory, "status": "online"},
        )
        remote = self.request("GET", "/api/agent/config")
        if remote.get("hash") != self.config_hash:
            self.apply_config(remote["config"], remote["hash"])
        elif not self.process or self.process.poll() is not None:
            self.start_xray()
        self.report_stats()

    def handle_signal(self, _signum, _frame) -> None:
        self.running = False

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)
        log(f"Agent started for {self.panel_url}")
        while self.running:
            try:
                self.cycle()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                log(f"Panel HTTP {exc.code}: {detail}")
            except (urllib.error.URLError, RuntimeError, OSError, json.JSONDecodeError) as exc:
                log(f"Cycle failed: {exc}")
            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)
        self.stop_xray()
        log("Agent stopped")


if __name__ == "__main__":
    if not shutil.which(os.environ.get("SPECTERGATE_XRAY_BINARY", "xray")):
        print("Xray binary not found. Set SPECTERGATE_XRAY_BINARY or install Xray.", file=sys.stderr)
        raise SystemExit(2)
    Agent().run()
