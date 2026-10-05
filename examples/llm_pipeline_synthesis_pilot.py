#!/usr/bin/env python3
"""LLM Pipeline Synthesis and Execution Pilot (dockuri/workflow-v1, DOCK-FLOW-001).

Demonstrates:
1. LLM Context Generation: Procedure registry projected into system prompt with RFC 6901 rules.
2. Pipeline Plan in canonical 'dockuri/workflow-v1' format with explicit $from references.
3. Topological Validation (Kahn's algorithm) ensuring acyclic execution.
4. Live Multi-Language Execution over UDS Daemons (Python + PHP).
5. Verification of CompositeExecutionReceipt (wellmanifest.wellman/receipt/v1).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

DOCKURI_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(DOCKURI_ROOT))

from src.dockuri_registry import DockuriRegistry
from src.dockuri_llm_pipeline import (
    build_llm_context,
    validate_pipeline_dag,
    execute_pipeline_dag,
)

PROJECTS = [
    Path("/home/tom/github/urirun-connectors/urirun-connector-fs"),
    Path("/home/tom/github/urirun-connectors/urirun-connector-base64"),
    Path("/home/tom/github/if-uri/curi"),
]

SOCKS = {
    "fs": "/tmp/pilot_workflow_fs.sock",
    "b64": "/tmp/pilot_workflow_b64.sock",
    "curi": "/tmp/pilot_workflow_curi.sock",
}


def start_daemons() -> list[subprocess.Popen]:
    for s in SOCKS.values():
        if os.path.exists(s):
            try:
                os.remove(s)
            except OSError:
                pass

    procs = []
    # 1. FS Daemon (Python)
    env_fs = os.environ.copy()
    env_fs["DOCKURI_SOCKET"] = SOCKS["fs"]
    env_fs["PYTHONPATH"] = str(PROJECTS[0])
    procs.append(
        subprocess.Popen(
            [sys.executable, "-m", "urirun_connector_fs.dockuri_worker"],
            cwd=str(PROJECTS[0]),
            env=env_fs,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    )

    # 2. Base64 Daemon (PHP)
    env_b64 = os.environ.copy()
    env_b64["DOCKURI_SOCKET"] = SOCKS["b64"]
    procs.append(
        subprocess.Popen(
            ["php", "cli.php", "daemon"],
            cwd=str(PROJECTS[1]),
            env=env_b64,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    )

    # 3. Curi Daemon (Python)
    env_curi = os.environ.copy()
    env_curi["DOCKURI_SOCKET"] = SOCKS["curi"]
    env_curi["PYTHONPATH"] = str(PROJECTS[2] / "src")
    procs.append(
        subprocess.Popen(
            [sys.executable, "-m", "curi.worker"],
            cwd=str(PROJECTS[2]),
            env=env_curi,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    )

    for _ in range(50):
        if all(os.path.exists(s) for s in SOCKS.values()):
            break
        time.sleep(0.02)
    else:
        raise TimeoutError("Failed to initialize all resident UDS daemons")

    return procs


def main() -> int:
    print("==========================================================================")
    print("🤖 DOCKURI/WORKFLOW-V1: LLM SYNTHESIS & TOPOLOGICAL DAG EXECUTION PILOT")
    print("==========================================================================")

    # 1. Discover registry
    reg = DockuriRegistry()
    for p in PROJECTS:
        reg.scan_path(p)

    # Inject ephemeral sockets into registry records for pilot isolation
    reg.procedures["fs.read_text"].transport["socket"] = SOCKS["fs"]
    reg.procedures["fs.sha256"].transport["socket"] = SOCKS["fs"]
    reg.procedures["base64.encode"].transport["socket"] = SOCKS["b64"]
    reg.procedures["base64.decode"].transport["socket"] = SOCKS["b64"]
    reg.procedures["curi.classify_uri"].transport["socket"] = SOCKS["curi"]

    print(f"📦 Step 1: Indexed {len(reg.procedures)} procedures in Dockuri Registry.")

    # 2. Generate System Prompt / Context for LLM
    llm_prompt = build_llm_context(reg)
    print(f"\n📑 Step 2: Generated LLM System Context ({len(llm_prompt)} bytes):")
    print("   [Head of context generated for LLM:]")
    for line in llm_prompt.splitlines()[:12]:
        print(f"   {line}")
    print("   ...")

    # 3. Synthetic Output produced by LLM conforming to dockuri/workflow-v1
    version_file = str(DOCKURI_ROOT / "VERSION")
    llm_generated_pipeline = {
        "$schema": "https://wellmanifest.org/schemas/dockuri-pipeline-v1.json",
        "name": "verify_and_digest_version_artifact",
        "max_parallel": 2,
        "flow": [
            {
                "id": "step1_read_file",
                "uri": "proc://urirun-connector-fs/fs/read_text/v1",
                "input": {
                    "path": version_file
                }
            },
            {
                "id": "step2_calc_checksum",
                "uri": "proc://urirun-connector-fs/fs/sha256/v1",
                "input": {
                    "path": version_file
                }
            },
            {
                "id": "step3_encode_b64",
                "uri": "proc://urirun-connector-base64/base64/encode/v1",
                "depends_on": ["step1_read_file"],
                "input": {
                    "text": { "$from": "step1_read_file", "path": "/content" }
                }
            },
            {
                "id": "step4_decode_b64",
                "uri": "proc://urirun-connector-base64/base64/decode/v1",
                "depends_on": ["step3_encode_b64"],
                "input": {
                    "text": { "$from": "step3_encode_b64", "path": "/result" }
                }
            },
            {
                "id": "step5_classify_uri",
                "uri": "proc://curi/curi/classify_uri/v1",
                "depends_on": ["step4_decode_b64"],
                "input": {
                    "uri": "fs://host/file/query/version"
                }
            }
        ]
    }

    print(f"\n🧠 Step 3: LLM Generated Pipeline Plan (dockuri/workflow-v1):")
    print(json.dumps(llm_generated_pipeline, indent=2))

    # 4. Preflight Validation (Kahn's DAG sort & cycle detection)
    order = validate_pipeline_dag(llm_generated_pipeline, reg)
    print(f"\n🔍 Step 4: Topological DAG Validation PASS!")
    print(f"   Execution order: {' -> '.join(order)}")

    # 5. Live Execution across UDS Daemons
    print(f"\n⚡ Step 5: Executing DAG over warm UDS daemons...")
    daemons = start_daemons()
    try:
        report = execute_pipeline_dag(llm_generated_pipeline, reg)
        print(f"\n✅ PIPELINE EXECUTION COMPLETED SUCCESSFULLY!")
        print(f"   Final Output: {report['final_output']}")

        print("\n📊 Per-Stage Execution Report:")
        for st in report["stages"]:
            print(f"   [{st['id']}] {st['proc']:<22} in {st['duration_ms']:.3f} ms -> {st['result']}")

        receipt = report["receipt"]
        print(f"\n🔐 CompositeExecutionReceipt (wellmanifest.wellman/receipt/v1):")
        print(json.dumps(receipt, indent=2))
        print("==========================================================================")
        assert receipt["total_duration_ms"] < 15.0, "Total execution exceeded 15 ms budget!"
        return 0
    finally:
        for d in daemons:
            d.terminate()
            d.wait(1.0)
        for s in SOCKS.values():
            if os.path.exists(s):
                try:
                    os.remove(s)
                except OSError:
                    pass


if __name__ == "__main__":
    sys.exit(main())
