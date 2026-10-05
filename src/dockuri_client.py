"""Dockuri Reference Client and Pipeline Runner (DOCK-STD-001).

Supports zero-cold-start procedure invocation over UDS and pipeline chaining
with cryptographic CompositeExecutionReceipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import time
from typing import Any


class DockuriClient:
    def __init__(self, socket_path: str, auto_spawn_cmd: list[str] | None = None):
        self.socket_path = socket_path
        self.auto_spawn_cmd = auto_spawn_cmd

    def ensure_socket(self) -> None:
        if os.path.exists(self.socket_path):
            return
        if not self.auto_spawn_cmd:
            raise FileNotFoundError(f"Socket not found at {self.socket_path} and no auto_spawn_cmd provided")

        # Auto spawn
        subprocess.Popen(self.auto_spawn_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Wait up to 500ms
        for _ in range(25):
            if os.path.exists(self.socket_path):
                time.sleep(0.02)
                return
            time.sleep(0.02)
        raise TimeoutError(f"Auto-spawned worker did not create socket {self.socket_path} in time")

    def call(self, proc: str, args: dict[str, Any], timeout_s: float = 1.0) -> dict[str, Any]:
        self.ensure_socket()
        req_id = f"req-{int(time.time()*1000):x}"
        msg = json.dumps({"id": req_id, "proc": proc, "args": args}) + "\n"

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout_s)
        t0 = time.perf_counter()
        try:
            client.connect(self.socket_path)
            client.sendall(msg.encode("utf-8"))
            raw = b""
            while b"\n" not in raw:
                chunk = client.recv(4096)
                if not chunk:
                    break
                raw += chunk
        finally:
            client.close()
        t1 = time.perf_counter()

        if not raw:
            raise RuntimeError(f"No response received from procedure '{proc}'")

        data = json.loads(raw.decode("utf-8").strip())
        data["_client_duration_ms"] = round((t1 - t0) * 1000.0, 3)
        return data


def run_pipeline(stages: list[dict[str, Any]], initial_input: Any) -> dict[str, Any]:
    """Execute a linear pipeline of Dockuri procedures and emit a CompositeExecutionReceipt."""
    results = []
    current_val = initial_input
    step_digests = []

    t_start = time.perf_counter()
    for i, stage in enumerate(stages):
        proc_name = stage["proc"]
        sock = stage["socket"]
        args_key = stage.get("input_key", "input")
        
        args = {args_key: current_val} if not isinstance(current_val, dict) else current_val
        client = DockuriClient(sock)
        resp = client.call(proc_name, args)
        
        if not resp.get("ok"):
            raise RuntimeError(f"Pipeline failed at stage {i+1} ({proc_name}): {resp.get('error')}")
        
        res = resp["result"]
        # If output specifies an extractor
        if "output_key" in stage and isinstance(res, dict):
            current_val = res.get(stage["output_key"])
        else:
            current_val = res
            
        stage_hash = hashlib.sha256(json.dumps({"stage": i+1, "proc": proc_name, "result": res}, sort_keys=True).encode()).hexdigest()
        step_digests.append(stage_hash)
        results.append({"stage": i+1, "proc": proc_name, "duration_ms": resp["_client_duration_ms"]})

    t_end = time.perf_counter()
    total_ms = round((t_end - t_start) * 1000.0, 3)

    receipt = {
        "schema": "wellmanifest.wellman/receipt/v1",
        "kind": "composite_pipeline",
        "stages_count": len(stages),
        "total_duration_ms": total_ms,
        "pipeline_digest": hashlib.sha256("".join(step_digests).encode()).hexdigest(),
        "step_digests": step_digests,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    return {
        "ok": True,
        "final_result": current_val,
        "stages": results,
        "receipt": receipt,
    }
