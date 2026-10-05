#!/usr/bin/env python3
"""Dockuri Conformance & Health Checker (DOCK-STD-001).

Validates dockuri.json against standard schema, probes UDS health via __ping__,
and asserts < 2.0 ms latency budget.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

SCHEMA_FILE = Path(__file__).parent.parent / "schemas" / "dockuri-manifest.schema.json"


def validate_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Basic structural check
    for req in ("app", "version", "transport", "procedures"):
        if req not in data:
            raise ValueError(f"Missing required field in manifest: '{req}'")

    if not SCHEMA_FILE.is_file():
        return data

    try:
        import jsonschema  # type: ignore

        with open(SCHEMA_FILE, "r", encoding="utf-8") as sf:
            schema = json.load(sf)
        jsonschema.validate(instance=data, schema=schema)
    except ImportError:
        pass

    return data


def probe_uds_ping(socket_path: str, max_latency_ms: float = 2.0) -> dict[str, Any]:
    if not os.path.exists(socket_path):
        raise FileNotFoundError(f"UDS Socket not found at {socket_path}")

    # Check permissions
    st = os.stat(socket_path)
    mode = oct(st.st_mode & 0o777)

    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    t0 = time.perf_counter()
    try:
        client.connect(socket_path)
        payload = json.dumps({"id": "ping-check", "proc": "__ping__", "args": {}}) + "\n"
        client.sendall(payload.encode("utf-8"))
        raw = client.recv(4096)
    finally:
        client.close()
    t1 = time.perf_counter()

    duration_ms = (t1 - t0) * 1000.0

    if not raw:
        raise RuntimeError("Empty response received from UDS daemon")

    resp = json.loads(raw.decode("utf-8").strip())
    if not resp.get("ok"):
        raise RuntimeError(f"Ping returned error: {resp}")

    if duration_ms > max_latency_ms:
        raise AssertionError(f"Latency violation: {duration_ms:.3f} ms exceeds {max_latency_ms} ms budget")

    return {
        "status": "PASS",
        "duration_ms": round(duration_ms, 3),
        "socket_mode": mode,
        "response": resp,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and test Dockuri manifests and workers.")
    parser.add_argument("--manifest", type=str, default="dockuri.json", help="Path to dockuri.json")
    parser.add_argument("--ping", action="store_true", help="Send live __ping__ probe to UDS socket")
    parser.add_argument("--socket", type=str, default=None, help="Explicit socket path override")
    args = parser.parse_args()

    m_path = Path(args.manifest)
    try:
        manifest = validate_manifest(m_path)
        print(f"✓ Manifest valid: app='{manifest['app']}', version='{manifest['version']}'")
        print(f"  Procedures: {len(manifest.get('procedures', {}))} registered")

        if args.ping:
            sock = args.socket or manifest.get("transport", {}).get("socket")
            if not sock:
                print("✗ No UDS socket path defined in transport", file=sys.stderr)
                return 1
            res = probe_uds_ping(sock)
            print(f"✓ UDS __ping__ PASS: {res['duration_ms']} ms round-trip (budget <= 2.0 ms)")
            print(f"  Runtime info: {res['response'].get('result', {})}")
        return 0
    except Exception as e:
        print(f"✗ Check failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
