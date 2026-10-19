"""Tests for DOCK-MCP-001 Model Context Protocol Server in wellmanifest/dockuri."""

from __future__ import annotations

import json
from pathlib import Path
from src.dockuri_mcp import (
    MCP_TOOLS_SPEC,
    TOOL_DISPATCHERS,
    process_jsonrpc_request,
)


def test_mcp_tools_spec_completeness():
    tool_names = {t["name"] for t in MCP_TOOLS_SPEC}
    expected = {
        "dockuri_execute_sentence",
        "dockuri_call_uri",
        "dockuri_search_procedures",
        "dockuri_list_projects",
        "dockuri_manage_process",
        "dockuri_check_conformance",
    }
    assert expected.issubset(tool_names)
    for t in MCP_TOOLS_SPEC:
        assert "name" in t
        assert "description" in t
        assert "inputSchema" in t
        assert t["name"] in TOOL_DISPATCHERS


def test_mcp_initialize_and_ping():
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {},
    }
    res = process_jsonrpc_request(init_req)
    assert res["id"] == 1
    assert res["result"]["protocolVersion"] == "2024-11-05"
    assert res["result"]["serverInfo"]["name"] == "dockuri-mcp"

    ping_req = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    ping_res = process_jsonrpc_request(ping_req)
    assert ping_res["id"] == 2
    assert ping_res["result"] == {}


def test_mcp_tools_list():
    req = {"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
    res = process_jsonrpc_request(req)
    assert res["id"] == 3
    tools = res["result"]["tools"]
    assert len(tools) >= 6


def test_mcp_call_manage_process_snippet():
    req = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "dockuri_manage_process",
            "arguments": {
                "action": "snippet",
                "target_uri": "proc://test/op/v1",
                "language": "python",
            },
        },
    }
    res = process_jsonrpc_request(req)
    assert res["id"] == 4
    assert res["result"]["isError"] is False
    text = res["result"]["content"][0]["text"]
    data = json.loads(text)
    assert data["status"] == "ok"
    assert "uri('proc://test/op/v1'" in data["snippet"]


def test_mcp_call_execute_sentence(tmp_path: Path):
    proj_dir = tmp_path / "mock_project"
    proj_dir.mkdir()
    (proj_dir / "dockuri.yaml").write_text(
        "version: dockuri/proc-v2\n"
        "processes:\n"
        "  proc://mock/sprint/v1:\n"
        "    run: ['echo', 'sprint ok']\n"
        "    description: 'Deduplicate sprint backlog'\n",
        encoding="utf-8",
    )
    req = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "dockuri_execute_sentence",
            "arguments": {
                "sentence": "zdeduplikuj sprint",
                "project": str(proj_dir),
                "dry_run": True,
            },
        },
    }
    res = process_jsonrpc_request(req)
    assert res["id"] == 5
    assert res["result"]["isError"] is False
    data = json.loads(res["result"]["content"][0]["text"])
    assert data["status"] == "ok"
    assert data["matched_uri"] == "proc://mock/sprint/v1"
    assert data["duration_ms"] <= 100.0


def test_mcp_provider_config_and_prompt_registry():
    for prov in ("all", "google", "antigravity", "gemini", "codex", "claude", "ide", "shell"):
        req = {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "dockuri_provider_config",
                "arguments": {"provider": prov},
            },
        }
        res = process_jsonrpc_request(req)
        assert res["result"]["isError"] is False
        data = json.loads(res["result"]["content"][0]["text"])
        assert data["status"] == "ok"

    reg_req = {
        "jsonrpc": "2.0",
        "id": 11,
        "method": "tools/call",
        "params": {
            "name": "dockuri_prompt_registry",
            "arguments": {"query": "deduplicate sprint tickets", "top_k": 4},
        },
    }
    reg_res = process_jsonrpc_request(reg_req)
    assert reg_res["result"]["isError"] is False
    reg_data = json.loads(reg_res["result"]["content"][0]["text"])
    assert reg_data["status"] == "ok"
    assert reg_data["duration_ms"] <= 100.0

