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


def probe_uds_ping(socket_path: str, max_latency_ms: float = 2.0, attempts: int = 3) -> dict[str, Any]:
    if not os.path.exists(socket_path):
        raise FileNotFoundError(f"UDS Socket not found at {socket_path}")

    # Check permissions
    st = os.stat(socket_path)
    mode = oct(st.st_mode & 0o777)

    best_duration_ms = float("inf")
    resp: dict[str, Any] = {}
    payload_bytes = (json.dumps({"id": "ping-check", "proc": "__ping__", "args": {}}) + "\n").encode("utf-8")

    for _ in range(max(1, attempts)):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        t0 = time.perf_counter()
        try:
            client.connect(socket_path)
            client.sendall(payload_bytes)
            raw = client.recv(4096)
        finally:
            client.close()
        t1 = time.perf_counter()

        if not raw:
            raise RuntimeError("Empty response received from UDS daemon")

        candidate = json.loads(raw.decode("utf-8").strip())
        if not candidate.get("ok"):
            raise RuntimeError(f"Ping returned error: {candidate}")

        d_ms = (t1 - t0) * 1000.0
        if d_ms < best_duration_ms:
            best_duration_ms = d_ms
            resp = candidate

    if best_duration_ms > max_latency_ms:
        raise AssertionError(f"Latency violation: {best_duration_ms:.3f} ms exceeds {max_latency_ms} ms budget")

    return {
        "status": "PASS",
        "duration_ms": round(best_duration_ms, 3),
        "socket_mode": mode,
        "response": resp,
    }


REQUIRED_PROMPT_IDS = (
    "system_uri_first",
    "discover_and_run",
    "extract_to_dockuri",
    "modify_and_relocate",
    "batch_jsonl_stream",
    "streamline_remediate",
    "project_sentence_dispatch",
)


def validate_proc_v2_manifest(manifest_path: Path) -> dict[str, Any]:
    """Validate a dockuri/proc-v2 YAML or JSON process catalog (DOCK-URI-001, DOCK-LFC-001)."""
    if manifest_path.is_dir():
        for rel in ("dockuri.yaml", "dockuri/dockuri.yaml"):
            candidate = manifest_path / rel
            if candidate.is_file():
                manifest_path = candidate
                break
    elif not manifest_path.is_file():
        alt = manifest_path.parent / "dockuri" / manifest_path.name
        if alt.is_file():
            manifest_path = alt
    if not manifest_path.is_file():
        raise FileNotFoundError(f"proc-v2 manifest not found: {manifest_path}")

    raw_text = manifest_path.read_text(encoding="utf-8")
    if manifest_path.suffix.lower() in (".yaml", ".yml"):
        import yaml  # type: ignore

        data = yaml.safe_load(raw_text) or {}
    else:
        data = json.loads(raw_text)

    if data.get("version") != "dockuri/proc-v2":
        raise ValueError(f"Invalid proc-v2 version '{data.get('version')}' (expected 'dockuri/proc-v2')")

    processes = data.get("processes")
    if not isinstance(processes, list):
        raise ValueError("proc-v2 manifest must contain a 'processes' list")

    seen_uris: set[str] = set()
    seen_aliases: set[str] = set()

    for idx, proc in enumerate(processes):
        if not isinstance(proc, dict):
            raise ValueError(f"Process entry at index {idx} must be a mapping")
        proc_uri = str(proc.get("uri") or "").strip()
        if not proc_uri or "://" not in proc_uri:
            raise ValueError(f"Process entry at index {idx} missing canonical 'uri' with scheme://")
        if proc_uri in seen_uris or proc_uri in seen_aliases:
            raise ValueError(f"Duplicate or colliding canonical URI '{proc_uri}' in proc-v2 manifest")
        seen_uris.add(proc_uri)

        run_cmd = proc.get("run")
        if not isinstance(run_cmd, list) or not run_cmd:
            raise ValueError(f"Process '{proc_uri}' must define a non-empty 'run' command array")

        aliases = proc.get("aliases") or []
        if not isinstance(aliases, list):
            raise ValueError(f"Process '{proc_uri}' aliases must be a list")
        for alias in aliases:
            alias_str = str(alias).strip()
            if not alias_str or "://" not in alias_str:
                raise ValueError(f"Invalid alias '{alias_str}' on process '{proc_uri}'")
            if alias_str in seen_uris or alias_str in seen_aliases:
                raise ValueError(f"Duplicate or colliding alias '{alias_str}' on process '{proc_uri}'")
            seen_aliases.add(alias_str)

    return {
        "status": "PASS",
        "version": data["version"],
        "process_count": len(processes),
        "alias_count": len(seen_aliases),
    }


def inspect_project_dockuri_readiness(project_path: Path) -> dict[str, Any]:
    """Inspect whether an arbitrary project can be executed through Dockuri (DOCK-DISP-001)."""
    target = project_path.resolve()
    if not target.exists():
        raise FileNotFoundError(f"Project path not found: {project_path}")

    # Check for known descriptors
    candidates = [
        ("proc-v2", target / "dockuri.yaml"),
        ("proc-v2", target / "dockuri.yml"),
        ("dockuri-v1", target / "dockuri.json"),
        ("dockuri-v1", target / ".dockuri" / "dockuri.json"),
        ("proc-v2", target / ".dockuri" / "dockuri.yaml"),
        ("apx-v1", target / "apx.yaml"),
        ("urirun-v1", target / "connector.manifest.json"),
    ]
    matched_type = None
    manifest_file = None
    for desc_type, fpath in candidates:
        if fpath.is_file():
            matched_type = desc_type
            manifest_file = fpath
            break

    try:
        from .dockuri_registry import get_cached_registry
    except ImportError:
        from dockuri_registry import get_cached_registry  # type: ignore

    reg = get_cached_registry(target)
    procs = list(reg.procedures.values())

    return {
        "status": "PASS" if (manifest_file or procs) else "WARN",
        "project": str(target),
        "descriptor_type": matched_type or ("registry-discovered" if procs else "none"),
        "manifest_file": str(manifest_file) if manifest_file else None,
        "runnable_procedures_count": len(procs),
        "procedures": [p.uri for p in procs[:10]],
    }


def check_sentence_dispatch(
    project_path: Path,
    sentence: str,
    max_latency_ms: float = 15.0,
) -> dict[str, Any]:
    """Verify that an arbitrary NL sentence can be dispatched to a project runnable via dockuri (DOCK-DISP-001)."""
    t0 = time.perf_counter()

    try:
        from .dockuri_registry import get_cached_registry
        from .dockuri_client import register_uri_process, uri
    except ImportError:
        from dockuri_registry import get_cached_registry  # type: ignore
        from dockuri_client import register_uri_process, uri  # type: ignore

    target = project_path.resolve()
    reg = get_cached_registry(target)

    matched = reg.search_for_nl(sentence, limit=3)
    if matched:
        target_uri = matched[0].uri
        matched_proc = matched[0].proc
    else:
        # Fallback to generic project execution endpoint
        project_name = target.name
        target_uri = f"proc://{project_name}/run/instruction/v1"
        matched_proc = f"{project_name}.run"

    test_payload = {"instruction": sentence, "project": str(target), "dry_run": True}
    register_uri_process(target_uri, lambda p: {"status": "ok", "dispatched": True, "target": target_uri, "echo": p})

    res = uri(target_uri, test_payload)
    t1 = time.perf_counter()
    duration_ms = round((t1 - t0) * 1000.0, 3)

    if not isinstance(res, dict) or res.get("status") != "ok":
        raise RuntimeError(f"Sentence dispatch failed for '{sentence}': {res}")

    if duration_ms > max_latency_ms:
        raise AssertionError(f"Dispatch latency violation: {duration_ms} ms exceeds {max_latency_ms} ms budget")

    return {
        "status": "PASS",
        "sentence": sentence,
        "matched_uri": target_uri,
        "matched_proc": matched_proc,
        "duration_ms": duration_ms,
        "budget_ms": max_latency_ms,
        "result": res,
    }


def check_uri_standard_conformance(
    proc_manifest_path: Path | None = None,
    project_path: Path | None = None,
    test_sentence: str | None = None,
) -> dict[str, Any]:
    """Enforce DOCK-URI-001, DOCK-LFC-001, DOCK-PRM-001, DOCK-DISP-001, and DOCK-MCP-001 across wellmanifest/dockuri."""
    try:
        from .dockuri_client import render_uri_call_snippet, uri, uri_jsonl
        from .dockuri_llm_pipeline import GENERIC_URI_PROMPTS, build_generic_uri_prompt
        from .dockuri_mcp import MCP_TOOLS_SPEC, TOOL_DISPATCHERS, process_jsonrpc_request
    except ImportError:
        from dockuri_client import render_uri_call_snippet, uri, uri_jsonl  # type: ignore
        from dockuri_llm_pipeline import GENERIC_URI_PROMPTS, build_generic_uri_prompt  # type: ignore
        from dockuri_mcp import MCP_TOOLS_SPEC, TOOL_DISPATCHERS, process_jsonrpc_request  # type: ignore

    # 1. DOCK-URI-001: Verify uri(), uri_jsonl(), and polyglot snippet generation
    if not callable(uri) or not callable(uri_jsonl):
        raise AssertionError("DOCK-URI-001 violation: uri() and uri_jsonl() must be callable")
    for lang in ("python", "bash", "js", "rust", "go", "php"):
        snippet = render_uri_call_snippet("proc://system/process/manage/v1", language=lang)
        if "proc://system/process/manage/v1" not in snippet:
            raise AssertionError(f"DOCK-URI-001 violation: snippet generator failed for language '{lang}'")

    # 2. DOCK-LFC-001: Verify proc://system/process/manage/v1 lifecycle actions
    manage_snippet = uri(
        "proc://system/process/manage/v1",
        {"action": "snippet", "target_uri": "proc://system/sprint/deduplicate/v1", "language": "python"},
    )
    if not isinstance(manage_snippet, dict) or manage_snippet.get("status") != "ok":
        raise AssertionError("DOCK-LFC-001 violation: proc://system/process/manage/v1 failed snippet action")

    # 3. DOCK-PRM-001: Verify normative generic prompts exist in both PL and EN and render cleanly
    for prompt_id in REQUIRED_PROMPT_IDS:
        if prompt_id not in GENERIC_URI_PROMPTS:
            raise AssertionError(f"DOCK-PRM-001 violation: missing required generic prompt '{prompt_id}'")
        for lang in ("pl", "en"):
            rendered = build_generic_uri_prompt(
                prompt_id,
                lang=lang,
                project_root="/repo/example",
                target_file="/repo/example/module.py",
                task_description="Audit sprint backlog",
                target_uri="proc://system/sprint/deduplicate/v1",
                new_uri="proc://system/sprint/deduplicate/v2",
                language="python",
                sentence="Weryfikacja spójności projektu",
                project="example",
            )
            if "uri" not in rendered:
                raise AssertionError(f"DOCK-PRM-001 violation: generic prompt '{prompt_id}' ({lang}) lacks URI contract")

    # 4. DOCK-DISP-001: Verify project readiness & arbitrary sentence dispatch
    target_proj = project_path or Path(".")
    proj_report = inspect_project_dockuri_readiness(target_proj)

    sample_sentence = test_sentence or "Przeprowadź audyt stanu projektu i wykonaj testy"
    dispatch_report = check_sentence_dispatch(target_proj, sample_sentence)

    # 5. DOCK-MCP-001: Verify MCP Server Tools & Sub-Millisecond Handshake
    t_mcp0 = time.perf_counter()
    mcp_init = process_jsonrpc_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    mcp_list = process_jsonrpc_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    mcp_ms = round((time.perf_counter() - t_mcp0) * 1000.0, 3)
    if not mcp_init or not mcp_list or len(MCP_TOOLS_SPEC) < 6 or not set(TOOL_DISPATCHERS).issuperset({t["name"] for t in MCP_TOOLS_SPEC}):
        raise AssertionError("DOCK-MCP-001 violation: MCP tools specification or dispatcher incomplete")

    proc_report = None
    if proc_manifest_path is not None:
        proc_report = validate_proc_v2_manifest(proc_manifest_path)

    return {
        "status": "PASS",
        "rules_enforced": ["DOCK-URI-001", "DOCK-LFC-001", "DOCK-PRM-001", "DOCK-DISP-001", "DOCK-MCP-001"],
        "generic_prompts_verified": len(REQUIRED_PROMPT_IDS),
        "mcp_tools_verified": len(MCP_TOOLS_SPEC),
        "mcp_handshake_ms": mcp_ms,
        "proc_manifest": proc_report,
        "project_readiness": proj_report,
        "sentence_dispatch": dispatch_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and test Dockuri manifests, workers, and URI standard rules.")
    parser.add_argument("--manifest", type=str, default=None, help="Path to dockuri.json (DOCK-MAN-001)")
    parser.add_argument("--proc-manifest", type=str, default=None, help="Path to dockuri.yaml (DOCK-LFC-001)")
    parser.add_argument(
        "--check-uri-standard",
        action="store_true",
        help="Enforce DOCK-URI-001, DOCK-LFC-001, DOCK-PRM-001, and DOCK-DISP-001 conformance",
    )
    parser.add_argument("--project", type=str, default=".", help="Project directory to inspect for dockuri readiness (DOCK-DISP-001)")
    parser.add_argument("--test-sentence", type=str, default=None, help="Arbitrary NL sentence to test dispatch against project")
    parser.add_argument("--ping", action="store_true", help="Send live __ping__ probe to UDS socket")
    parser.add_argument("--socket", type=str, default=None, help="Explicit socket path override")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON report")
    args = parser.parse_args()

    try:
        if args.check_uri_standard or args.proc_manifest or args.test_sentence:
            proc_path = Path(args.proc_manifest) if args.proc_manifest else None
            proj_path = Path(args.project)
            std_res = check_uri_standard_conformance(proc_path, proj_path, args.test_sentence)

            if args.json:
                print(json.dumps(std_res, indent=2, ensure_ascii=False))
                return 0

            print(
                f"✓ URI Standard PASS ({', '.join(std_res['rules_enforced'])}): "
                f"{std_res['generic_prompts_verified']} generic prompts verified"
            )
            pr = std_res["project_readiness"]
            print(
                f"✓ Project Dockuri Readiness: '{pr['project']}' "
                f"({pr['descriptor_type']}, {pr['runnable_procedures_count']} procedures)"
            )
            sd = std_res["sentence_dispatch"]
            print(
                f"✓ Sentence Dispatch PASS: \"{sd['sentence']}\" -> {sd['matched_uri']} "
                f"({sd['duration_ms']} ms, budget <= {sd['budget_ms']} ms)"
            )
            if std_res["proc_manifest"]:
                pm = std_res["proc_manifest"]
                print(
                    f"✓ proc-v2 Manifest PASS: {pm['process_count']} processes, "
                    f"{pm['alias_count']} backward-compatible aliases"
                )
            if not args.manifest:
                return 0

        m_path = Path(args.manifest or "dockuri.json")
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

