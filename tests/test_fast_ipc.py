import os
import subprocess
import sys
import time
import pytest
from pathlib import Path
from src.dockuri_check import probe_uds_ping
from src.dockuri_client import DockuriClient

WORKER_SCRIPT = Path(__file__).parent.parent / "examples" / "workers" / "python" / "dockuri_worker.py"

@pytest.fixture(scope="module")
def python_worker(tmp_path_factory):
    sock_dir = tmp_path_factory.mktemp("socks")
    sock_path = str(sock_dir / "worker.sock")
    env = os.environ.copy()
    env["DOCKURI_SOCKET"] = sock_path

    proc = subprocess.Popen([sys.executable, str(WORKER_SCRIPT)], env=env)

    # Wait for socket to appear
    for _ in range(50):
        if os.path.exists(sock_path):
            break
        time.sleep(0.02)
    else:
        proc.kill()
        raise TimeoutError("Worker failed to create socket")

    yield sock_path

    proc.terminate()
    proc.wait(timeout=2.0)
    if os.path.exists(sock_path):
        os.remove(sock_path)


def test_ping_latency_budget(python_worker):
    # DOCK-PNG-001: Round-trip ping must be <= 2.0 ms
    res = probe_uds_ping(python_worker, max_latency_ms=2.0)
    assert res["status"] == "PASS"
    assert res["duration_ms"] <= 2.0
    print(f"\nMeasured Ping Latency: {res['duration_ms']} ms")


def test_procedure_call(python_worker):
    client = DockuriClient(python_worker)
    
    # 1. math.add
    resp1 = client.call("math.add", {"a": 15, "b": 27})
    assert resp1["ok"] is True
    assert resp1["result"] == 42
    assert resp1["_client_duration_ms"] < 2.0

    # 2. text.uppercase
    resp2 = client.call("text.uppercase", {"text": "hello dockuri"})
    assert resp2["ok"] is True
    assert resp2["result"] == "HELLO DOCKURI"
    assert resp2["_client_duration_ms"] < 2.0
