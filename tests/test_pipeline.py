import os
import subprocess
import sys
import time
import pytest
from pathlib import Path
from src.dockuri_client import run_pipeline

WORKER_SCRIPT = Path(__file__).parent.parent / "examples" / "workers" / "python" / "dockuri_worker.py"

@pytest.fixture(scope="module")
def worker_socket(tmp_path_factory):
    sock_dir = tmp_path_factory.mktemp("socks_pipe")
    sock_path = str(sock_dir / "pipe_worker.sock")
    env = os.environ.copy()
    env["DOCKURI_SOCKET"] = sock_path

    proc = subprocess.Popen([sys.executable, str(WORKER_SCRIPT)], env=env)
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


def test_chained_pipeline_with_composite_receipt(worker_socket):
    stages = [
        {"proc": "text.uppercase", "socket": worker_socket, "input_key": "text"},
        {"proc": "text.reverse", "socket": worker_socket, "input_key": "text"},
    ]

    res = run_pipeline(stages, "hello world")
    assert res["ok"] is True
    # "hello world" -> "HELLO WORLD" -> "DLROW OLLEH"
    assert res["final_result"] == "DLROW OLLEH"
    assert res["receipt"]["schema"] == "wellmanifest.wellman/receipt/v1"
    assert res["receipt"]["stages_count"] == 2
    assert len(res["receipt"]["step_digests"]) == 2
    assert res["receipt"]["total_duration_ms"] < 10.0
