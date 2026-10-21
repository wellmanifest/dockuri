#!/usr/bin/env python3
"""Dockuri Model Context Protocol (MCP) Server (DOCK-MCP-001).

Exposes Dockuri's fast URI execution engine to LLMs (Google Gemini / Antigravity,
Claude, OpenAI Codex) via JSON-RPC 2.0 over stdio.

Tools:
- dockuri_execute_sentence: Dispatch and execute any NL sentence on any dockuri project.
- dockuri_call_uri: Direct fast URI process invocation (uri / uri_jsonl).
- dockuri_search_procedures: Semantic & lexical search across the workspace.
- dockuri_list_projects: Inspect all runnable projects in the workspace.
- dockuri_manage_process: Lifecycle management (generate, modify, relocate, snippet).
- dockuri_check_conformance: Enforce DOCK-STD-001 & latency budget (< 15ms).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from .dockuri_check import (
        check_sentence_dispatch,
        check_uri_standard_conformance,
        inspect_project_dockuri_readiness,
    )
    from .dockuri_client import render_uri_call_snippet, uri, uri_jsonl
    from .dockuri_registry import DockuriRegistry, get_cached_registry
except ImportError:
    from src.dockuri_check import (  # type: ignore
        check_sentence_dispatch,
        check_uri_standard_conformance,
        inspect_project_dockuri_readiness,
    )
    from src.dockuri_client import render_uri_call_snippet, uri, uri_jsonl  # type: ignore
    from src.dockuri_registry import DockuriRegistry, get_cached_registry  # type: ignore


MCP_TOOLS_SPEC: List[Dict[str, Any]] = [
    {
        "name": "dockuri_execute_sentence",
        "description": (
            "Execute any natural language sentence or instruction against any project "
            "runnable via Dockuri using the ultra-fast URI process engine (DOCK-DISP-001, DOCK-ACC-001)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sentence": {
                    "type": "string",
                    "description": "Task or instruction in plain Polish or English (e.g. 'zdeduplikuj zadania w sprincie', 'uruchom audyt')",
                },
                "project": {
                    "type": "string",
                    "description": "Absolute path to the target project (defaults to current working directory)",
                },
                "payload": {
                    "type": "object",
                    "description": "Optional parameters or arguments dictionary for execution",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true, simulates dispatch without mutating state",
                    "default": False,
                },
            },
            "required": ["sentence"],
        },
    },
    {
        "name": "dockuri_call_uri",
        "description": "Call any registered Dockuri URI process directly with payload or streaming JSONL (DOCK-URI-001).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uri": {
                    "type": "string",
                    "description": "Full canonical URI (e.g. 'proc://system/sprint/deduplicate/v1', 'willman://operation/dockuri/v1')",
                },
                "payload": {
                    "type": "object",
                    "description": "JSON arguments or payload dictionary",
                },
                "raw_jsonl": {
                    "type": "string",
                    "description": "Optional raw multiline JSONL string for streaming execution",
                },
            },
            "required": ["uri"],
        },
    },
    {
        "name": "dockuri_search_procedures",
        "description": "Search registered Dockuri procedures across the workspace by natural language query or keywords (DOCK-REG-001).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query or keywords in Polish/English",
                },
                "project": {
                    "type": "string",
                    "description": "Specific project directory to scan (defaults to current directory or ~/github)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of candidate procedures to return",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "dockuri_list_projects",
        "description": "List all projects in the workspace runnable via Dockuri along with their descriptors and procedure counts (DOCK-DISP-001).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "root_dir": {
                    "type": "string",
                    "description": "Directory to scan for projects (defaults to current directory or ~/github)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum projects to return",
                    "default": 20,
                },
            },
        },
    },
    {
        "name": "dockuri_manage_process",
        "description": "Declaratively generate, modify, relocate, list, or generate code snippets for a URI process in dockuri.yaml (DOCK-LFC-001).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["generate", "modify", "mutate", "relocate", "move", "extract", "catalog", "list", "snippet", "prompt_registry"],
                    "description": "Lifecycle action to perform",
                },
                "target_uri": {
                    "type": "string",
                    "description": "Canonical URI of the process",
                },
                "new_uri": {
                    "type": "string",
                    "description": "New target URI when action is 'relocate'",
                },
                "language": {
                    "type": "string",
                    "enum": ["python", "bash", "js", "ts", "rust", "go", "php"],
                    "description": "Target language for action='snippet'",
                    "default": "python",
                },
                "run": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command line array for 'generate' or 'modify'",
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description of the procedure",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "dockuri_check_conformance",
        "description": "Run the Dockuri standard conformance and latency audit on a project (DOCK-STD-001, DOCK-DISP-001).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "Project directory to audit",
                },
                "test_sentence": {
                    "type": "string",
                    "description": "Sample sentence to test dispatch latency budget",
                },
            },
        },
    },
    {
        "name": "dockuri_prompt_registry",
        "description": "Generate a prompt-tailored URI command shortlist, TOON bounded registry, and constrained JSON Schema for LLM tool calls.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language task or prompt query"},
                "top_k": {"type": "integer", "default": 8, "description": "Number of top matching URI processes"},
                "project": {"type": "string", "description": "Optional project root directory"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "dockuri_provider_config",
        "description": "Return ready-to-use MCP client configurations and CLI commands for Google Antigravity/Gemini, OpenAI Codex, Anthropic Claude, IDE, and Shell CLI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": ["all", "google", "antigravity", "gemini", "codex", "claude", "ide", "shell"],
                    "default": "all",
                },
                "command": {"type": "string", "default": "dockuri-mcp"},
            },
        },
    },
]


def handle_execute_sentence(args: Dict[str, Any]) -> Dict[str, Any]:
    sentence = args["sentence"]
    project_str = args.get("project") or os.getcwd()
    project_path = Path(project_str).resolve()
    dry_run = bool(args.get("dry_run", False))
    extra_payload = args.get("payload") or {}

    t0 = time.perf_counter()
    readiness = inspect_project_dockuri_readiness(project_path)

    # Search for matching procedure using cached registry (single scan)
    reg = get_cached_registry(project_path)
    matched = reg.search_for_nl(sentence, limit=3)

    if matched:
        target_uri = matched[0].uri
        matched_proc = matched[0].proc
    else:
        fallback = reg.procedures.get(f"{project_path.name}.run")
        if fallback is None:
            return {
                "status": "error",
                "sentence": sentence,
                "matched_uri": None,
                "matched_proc": None,
                "duration_ms": round((time.perf_counter() - t0) * 1000.0, 3),
                "readiness": readiness,
                "error": {"code": "NO_MATCHING_PROCEDURE", "message": "no procedure matches the sentence and the project registers no generic instruction endpoint"},
            }
        target_uri, matched_proc = fallback.uri, fallback.proc

    dispatch_payload = {
        "instruction": sentence,
        "project": str(project_path),
        "dry_run": dry_run,
        **extra_payload,
    }

    result = uri(target_uri, dispatch_payload)
    t1 = time.perf_counter()
    duration_ms = round((t1 - t0) * 1000.0, 3)

    failed = not isinstance(result, dict) or result.get("status") == "error" or result.get("ok") is False
    return {
        "status": "error" if failed else "ok",
        "sentence": sentence,
        "matched_uri": target_uri,
        "matched_proc": matched_proc,
        "duration_ms": duration_ms,
        "readiness": readiness,
        "execution_result": result,
    }


_PROJECT_SCOPED_MUTATING_URIS = ("proc://system/sprint/deduplicate/v1", "proc://system/worktree/promote/v1")
_TARGETED_ACTIONS = ("generate", "modify", "relocate", "extract")


def handle_call_uri(args: Dict[str, Any]) -> Any:
    if not args.get("uri") and args.get("sentence"):
        return handle_execute_sentence(args)
    target_uri = args["uri"]
    payload = dict(args.get("payload") or args.get("params") or args.get("args") or {})
    if args.get("project") and "project" not in payload:
        payload["project"] = args["project"]
    if args.get("dry_run") is not None and "dry_run" not in payload:
        payload["dry_run"] = bool(args["dry_run"])
    if (
        target_uri in _PROJECT_SCOPED_MUTATING_URIS
        and not any(k in payload for k in ("project", "projects", "workspace_root"))
    ):
        if not (payload.get("dry_run") or str(payload.get("action") or "").lower() == "audit"):
            return {"status": "error", "uri": target_uri, "error": {"code": "PROJECT_REQUIRED", "message": "mutating call needs an explicit project, projects or workspace_root"}}
        payload["project"] = os.getcwd()
    raw_jsonl = args.get("raw_jsonl") or args.get("jsonl_lines")
    t0 = time.perf_counter()
    if raw_jsonl is not None:
        lines = raw_jsonl.splitlines() if isinstance(raw_jsonl, str) else list(raw_jsonl)
        res = {"status": "ok", "uri": target_uri, "results": uri_jsonl(target_uri, lines, socket_path=args.get("socket_path"))}
    else:
        res = uri(target_uri, payload, socket_path=args.get("socket_path"))
    t1 = time.perf_counter()
    duration_ms = round((t1 - t0) * 1000.0, 3)
    if isinstance(res, dict):
        res["_mcp_duration_ms"] = duration_ms
    return res


def handle_search_procedures(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args["query"]
    limit = int(args.get("limit", 5))
    project_str = args.get("project")
    scan_dir = Path(project_str).resolve() if project_str else Path(os.getcwd())

    t0 = time.perf_counter()
    reg = get_cached_registry(scan_dir)
    results = reg.search_for_nl(query, limit=limit)
    t1 = time.perf_counter()

    return {
        "query": query,
        "total_indexed": len(reg.procedures),
        "duration_ms": round((t1 - t0) * 1000.0, 3),
        "candidates": [r.to_dict() for r in results],
    }


def handle_list_projects(args: Dict[str, Any]) -> Dict[str, Any]:
    root_str = args.get("root_dir") or args.get("workspace_root") or args.get("project")
    root_dir = Path(root_str).resolve() if root_str else Path(os.getcwd())
    limit = int(args.get("limit", 20))

    t0 = time.perf_counter()
    projects: List[Dict[str, Any]] = []

    if root_dir.exists():
        for entry in sorted(root_dir.iterdir()):
            if entry.is_dir() and not entry.name.startswith(".") and not entry.name.endswith("-archive"):
                try:
                    rd = inspect_project_dockuri_readiness(entry)
                    if rd["status"] == "PASS":
                        projects.append(rd)
                        if len(projects) >= limit:
                            break
                except Exception:
                    pass

    t1 = time.perf_counter()
    return {
        "root_scanned": str(root_dir),
        "runnable_projects_count": len(projects),
        "duration_ms": round((t1 - t0) * 1000.0, 3),
        "projects": projects,
    }


def handle_manage_process(args: Dict[str, Any]) -> Dict[str, Any]:
    raw_action = str(args.get("action") or "catalog").strip().lower()
    action = {"list": "catalog", "mutate": "modify", "move": "relocate"}.get(raw_action, raw_action)
    if action in _TARGETED_ACTIONS and not (args.get("target_uri") or args.get("uri")):
        return {"status": "error", "action": action, "error": {"code": "TARGET_URI_REQUIRED", "message": f"action '{action}' needs an explicit target_uri"}}
    target_uri = str(args.get("target_uri") or args.get("uri") or "proc://system/sprint/deduplicate/v1")
    language = str(args.get("language") or args.get("snippet_lang") or args.get("lang") or "python")

    if action == "snippet":
        snip = render_uri_call_snippet(target_uri, default_params={"dry_run": True}, language=language)
        return {"status": "ok", "action": "snippet", "target_uri": target_uri, "language": language, "snippet": snip}

    manage_payload: Dict[str, Any] = {
        "action": action,
        "target_uri": target_uri,
        "new_uri": args.get("new_uri"),
        "run": args.get("run") or args.get("command"),
        "description": args.get("description"),
        "language": language,
    }
    if args.get("query") or args.get("prompt"):
        manage_payload["query"] = args.get("query") or args.get("prompt")
    if args.get("project"):
        manage_payload["manifest"] = str(Path(str(args["project"])).resolve() / "dockuri.yaml")
    return uri("proc://system/process/manage/v1", manage_payload)


def handle_check_conformance(args: Dict[str, Any]) -> Dict[str, Any]:
    project_str = args.get("project") or os.getcwd()
    project_path = Path(project_str).resolve()
    test_sentence = args.get("test_sentence")
    return check_uri_standard_conformance(
        project_path=project_path,
        test_sentence=test_sentence,
    )


def handle_prompt_registry(args: Dict[str, Any]) -> Dict[str, Any]:
    t0 = time.perf_counter()
    query = args["query"]
    top_k = int(args.get("top_k", 8))
    req: Dict[str, Any] = {"action": "llm_context", "query": query, "top_k": top_k}
    if args.get("project"):
        mf = Path(args["project"]).resolve() / "dockuri.yaml"
        if mf.is_file():
            req["manifest"] = str(mf)
    res = uri("proc://system/process/prompt-registry/v1", req)
    if isinstance(res, dict):
        res["duration_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        return res
    return {"status": "ok", "results": res, "duration_ms": round((time.perf_counter() - t0) * 1000.0, 3)}


def handle_provider_config(args: Dict[str, Any]) -> Dict[str, Any]:
    provider = str(args.get("provider") or "all").lower()
    command = str(args.get("command") or "dockuri-mcp")
    mcp_entry = {"command": command, "args": ["--stdio"]}
    providers = {
        "google": {
            "provider": "google",
            "clients": ["Google Antigravity IDE/CLI", "Gemini CLI"],
            "config_paths": ["~/.gemini/settings.json", "~/.gemini/antigravity-cli/mcp/dockuri/config.json"],
            "cli_install": f"gemini mcp add dockuri -- {command} --stdio",
            "mcpServers": {"dockuri": mcp_entry},
        },
        "codex": {
            "provider": "codex",
            "clients": ["OpenAI Codex CLI", "Codex IDE"],
            "config_paths": ["~/.codex/config.toml"],
            "cli_install": f"codex mcp add dockuri -- {command} --stdio",
            "toml_config": f'[mcp_servers.dockuri]\ncommand = "{command}"\nargs = ["--stdio"]\n',
            "mcpServers": {"dockuri": mcp_entry},
        },
        "claude": {
            "provider": "claude",
            "clients": ["Anthropic Claude Code CLI", "Claude Desktop"],
            "config_paths": ["~/.claude.json", "~/.config/Claude/claude_desktop_config.json"],
            "cli_install": f"claude mcp add dockuri -- {command} --stdio",
            "mcpServers": {"dockuri": mcp_entry},
        },
        "ide": {
            "provider": "ide",
            "clients": ["Cursor", "VS Code", "Windsurf", "Zed"],
            "config_paths": [".cursor/mcp.json", ".vscode/mcp.json"],
            "mcpServers": {"dockuri": mcp_entry},
        },
        "shell": {
            "provider": "shell",
            "clients": ["Bash/Zsh CLI", "CI/CD Pipelines"],
            "commands": {
                "single_call": 'uri "proc://system/sprint/deduplicate/v1" \'{"dry_run":true}\'',
                "prompt_registry": 'uri --prompt "deduplicate sprint tickets" 5',
            },
        },
    }
    alias_map = {"antigravity": "google", "gemini": "google"}
    key = alias_map.get(provider, provider)
    if key == "all":
        return {"status": "ok", "provider": "all", "providers": providers}
    if key not in providers:
        raise ValueError(f"Unsupported provider: {provider}")
    return {"status": "ok", **providers[key]}


TOOL_DISPATCHERS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "dockuri_execute_sentence": handle_execute_sentence,
    "dockuri_call_uri": handle_call_uri,
    "dockuri_search_procedures": handle_search_procedures,
    "dockuri_list_projects": handle_list_projects,
    "dockuri_manage_process": handle_manage_process,
    "dockuri_check_conformance": handle_check_conformance,
    "dockuri_prompt_registry": handle_prompt_registry,
    "dockuri_provider_config": handle_provider_config,
    # Dot-named aliases matching dockuri/dockuri MCP Server
    "dockuri.uri": handle_call_uri,
    "dockuri.search": handle_search_procedures,
    "dockuri.prompt_registry": handle_prompt_registry,
    "dockuri.process_manage": handle_manage_process,
    "dockuri.provider_config": handle_provider_config,
}


def process_jsonrpc_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process a single Model Context Protocol JSON-RPC 2.0 message."""
    method = req.get("method")
    msg_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "dockuri-mcp",
                    "version": "0.1.0",
                    "description": "Dockuri Zero-Cold-Start Fast URI Process MCP Server",
                },
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": MCP_TOOLS_SPEC},
        }

    if method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name")
        tool_args = params.get("arguments", {})

        if tool_name not in TOOL_DISPATCHERS:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32601,
                    "message": f"Method not found: unknown tool '{tool_name}'",
                },
            }

        try:
            handler = TOOL_DISPATCHERS[tool_name]
            result_data = handler(tool_args)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result_data, indent=2, ensure_ascii=False),
                        }
                    ],
                    "isError": False,
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"status": "error", "error": str(e)}, ensure_ascii=False),
                        }
                    ],
                    "isError": True,
                },
            }

    if msg_id is not None:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {
                "code": -32601,
                "message": f"Unsupported JSON-RPC method: '{method}'",
            },
        }
    return None


def run_stdio_server() -> None:
    """Run MCP JSON-RPC 2.0 stdio server loop."""
    sys.stderr.write("[dockuri-mcp] Server started (stdio JSON-RPC 2.0)\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line_str = line.strip()
        if not line_str:
            continue
        try:
            req = json.loads(line_str)
            res = process_jsonrpc_request(req)
            if res is not None:
                sys.stdout.write(json.dumps(res, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as err:
            err_res = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": f"Parse error: {err}"},
            }
            sys.stdout.write(json.dumps(err_res, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except Exception as fatal:
            sys.stderr.write(f"[dockuri-mcp] Error: {fatal}\n")
            sys.stderr.flush()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Dockuri Model Context Protocol (MCP) Server.")
    parser.add_argument("--stdio", action="store_true", default=True, help="Run in stdio mode (default)")
    parser.add_argument("--list-tools", action="store_true", help="Print available tools in MCP format and exit")
    parser.add_argument("--call", type=str, default=None, help="Directly invoke a tool: --call <tool_name>")
    parser.add_argument("--args", type=str, default="{}", help="JSON arguments for --call")
    args = parser.parse_args()

    if args.list_tools:
        print(json.dumps(MCP_TOOLS_SPEC, indent=2, ensure_ascii=False))
        return 0

    if args.call:
        tool_name = args.call
        tool_args = json.loads(args.args)
        req = {
            "jsonrpc": "2.0",
            "id": "direct-call",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": tool_args},
        }
        res = process_jsonrpc_request(req)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    run_stdio_server()
    return 0


if __name__ == "__main__":
    sys.exit(main())
