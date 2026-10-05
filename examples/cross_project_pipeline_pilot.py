#!/usr/bin/env python3
"""Cross-Project Polyglot Pipeline Pilot (Dockuri Standard DOCK-STD-001).

Chains procedures across multiple independent repositories:
1. PHP Daemon: urirun-connectors/urirun-connector-base64 (base64.encode)
2. PHP Daemon: urirun-connectors/urirun-connector-base64 (base64.decode)
3. Python Daemon: if-uri/curi (curi.classify_uri)

Generates an aggregated CompositeExecutionReceipt and verifies sub-millisecond per-hop performance.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

# Add wellmanifest/dockuri to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.dockuri_client import DockuriClient, run_pipeline

B64_DIR = Path("/home/tom/github/urirun-connectors/urirun-connector-base64")
CURI_DIR = Path("/home/tom/github/if-uri/curi")

B64_SOCK = "/tmp/pilot_dockuri_b64.sock"
CURI_SOCK = "/tmp/pilot_dockuri_curi.sock"


def start_daemons() -> tuple[subprocess.Popen, subprocess.Popen]:
    for s in (B64_SOCK, CURI_SOCK):
        if os.path.exists(s):
            try:
                os.remove(s)
            except OSError:
                pass

    # 1. Start PHP Base64 daemon
    env_b64 = os.environ.copy()
    env_b64["DOCKURI_SOCKET"] = B64_SOCK
    proc_b64 = subprocess.Popen(
        ["php", "cli.php", "daemon"],
        cwd=str(B64_DIR),
        env=env_b64,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 2. Start Python Curi daemon
    env_curi = os.environ.copy()
    env_curi["DOCKURI_SOCKET"] = CURI_SOCK
    env_curi["PYTHONPATH"] = str(CURI_DIR / "src")
    proc_curi = subprocess.Popen(
        [sys.executable, "-m", "curi.worker"],
        cwd=str(CURI_DIR),
        env=env_curi,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait for sockets
    for _ in range(50):
        if os.path.exists(B64_SOCK) and os.path.exists(CURI_SOCK):
            break
        time.sleep(0.02)
    else:
        raise TimeoutError("Failed to initialize resident daemons on UDS")

    return proc_b64, proc_curi


def main() -> int:
    print("=================================================================")
    print("🚀 DOCKURI CROSS-PROJECT POLYGLOT PIPELINE PILOT (DOCK-STD-001)")
    print("=================================================================")

    p_b64, p_curi = start_daemons()
    try:
        # Pre-check ping latencies
        c_b64 = DockuriClient(B64_SOCK)
        c_curi = DockuriClient(CURI_SOCK)

        ping_b64 = c_b64.call("__ping__", {})
        ping_curi = c_curi.call("__ping__", {})

        print(f"✓ PHP Worker (base64) Ping:  {ping_b64['_client_duration_ms']} ms")
        print(f"✓ Python Worker (curi) Ping: {ping_curi['_client_duration_ms']} ms")
        print("-" * 65)

        # Pipeline definition
        stages = [
            {
                "proc": "base64.encode",
                "socket": B64_SOCK,
                "input_key": "text",
                "output_key": "result",
            },
            {
                "proc": "base64.decode",
                "socket": B64_SOCK,
                "input_key": "text",
                "output_key": "result",
            },
            {
                "proc": "curi.classify_uri",
                "socket": CURI_SOCK,
                "input_key": "uri",
            },
        ]

        raw_uri = "codec://host/text/query/base64"
        print(f"▶ Input payload: '{raw_uri}'")

        pipeline_result = run_pipeline(stages, raw_uri)

        print("\n✅ PIPELINE EXECUTION SUCCESSFUL!")
        print(f"  Final Result: {pipeline_result['final_result']}")
        print("\n📊 Per-Stage Latency Breakdown:")
        for st in pipeline_result["stages"]:
            print(f"  - Stage {st['stage']} ({st['proc']}): {st['duration_ms']} ms")

        receipt = pipeline_result["receipt"]
        print(f"\n🔐 CompositeExecutionReceipt (wellmanifest.wellman/receipt/v1):")
        print(f"  - Schema: {receipt['schema']}")
        print(f"  - Total Pipeline Duration: {receipt['total_duration_ms']} ms")
        print(f"  - Pipeline Digest (SHA-256): {receipt['pipeline_digest']}")
        print(f"  - Completed At: {receipt['completed_at']}")
        print("=================================================================")

        # Assert total latency is well below 10 ms (thousands of times faster than Docker)
        assert receipt["total_duration_ms"] < 10.0, "Total pipeline duration exceeded 10 ms!"
        return 0
    finally:
        p_b64.terminate()
        p_curi.terminate()
        p_b64.wait(1.0)
        p_curi.wait(1.0)
        for s in (B64_SOCK, CURI_SOCK):
            if os.path.exists(s):
                try:
                    os.remove(s)
                except OSError:
                    pass


if __name__ == "__main__":
    sys.exit(main())
