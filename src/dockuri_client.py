"""Dockuri Reference Client and Pipeline Runner (DOCK-STD-001).

Supports zero-cold-start procedure invocation over UDS and pipeline chaining
with cryptographic CompositeExecutionReceipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlsplit, urlunsplit


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


_CUSTOM_URI_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}


def _coerce_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if lowered in ("null", "none"):
        return None
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        return int(value)
    if (value.startswith("{") and value.endswith("}")) or (value.startswith("[") and value.endswith("]")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _split_uri_and_query(address: str) -> tuple[str, dict[str, Any]]:
    raw = (address or "").strip()
    if not raw:
        raise ValueError("URI address must not be empty")
    parts = urlsplit(raw)
    if not parts.scheme:
        raise ValueError(f"Invalid URI (missing scheme): {raw}")
    query_params: dict[str, Any] = {}
    if parts.query:
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            coerced = _coerce_scalar(v)
            if k in query_params:
                existing = query_params[k]
                query_params[k] = existing + [coerced] if isinstance(existing, list) else [existing, coerced]
            else:
                query_params[k] = coerced
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")), query_params


def register_uri_process(uri_str: str, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
    """Register an in-process callable under a canonical URI (DOCK-URI-001)."""
    base_uri, _ = _split_uri_and_query(uri_str)
    _CUSTOM_URI_HANDLERS[base_uri] = handler


def parse_jsonl_payload(payload: Any) -> tuple[list[dict[str, Any]], bool]:
    """Parse payload into a list of parameter dicts and a flag indicating batch/JSONL mode."""
    if payload is None:
        return [{}], False
    if isinstance(payload, dict):
        return [dict(payload)], False
    if isinstance(payload, Path):
        return parse_jsonl_payload(payload.read_text(encoding="utf-8") if payload.exists() else "")
    if isinstance(payload, (list, tuple)):
        items: list[dict[str, Any]] = []
        for elem in payload:
            if isinstance(elem, dict):
                items.append(dict(elem))
            elif isinstance(elem, str) and elem.strip():
                parsed = json.loads(elem)
                items.append(parsed if isinstance(parsed, dict) else {"value": parsed})
        return (items or [{}]), True
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            return [{}], False
        if stripped.startswith("@") and len(stripped) > 1:
            file_path = Path(stripped[1:]).expanduser()
            if file_path.is_file():
                return parse_jsonl_payload(file_path.read_text(encoding="utf-8"))
        lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        if len(lines) == 1:
            parsed = json.loads(lines[0])
            if isinstance(parsed, dict):
                return [parsed], False
            if isinstance(parsed, list):
                return [x if isinstance(x, dict) else {"value": x} for x in parsed], True
            return [{"value": parsed}], False
        return [(p if isinstance(p, dict) else {"value": p}) for p in (json.loads(ln) for ln in lines)], True
    raise TypeError(f"Unsupported URI payload type: {type(payload)!r}")


def render_uri_call_snippet(
    target_uri: str,
    default_params: dict[str, Any] | None = None,
    lang: str = "python",
) -> str:
    """Render a minimal cross-language wrapper snippet calling `uri('<uri>', ...)` (DOCK-URI-001)."""
    sample = json.dumps(default_params or {}, ensure_ascii=False)
    norm_lang = lang.strip().lower()
    if norm_lang in ("sh", "bash", "shell"):
        return f"#!/usr/bin/env bash\nset -euo pipefail\nexec uri {json.dumps(target_uri)} \"${{1:-{sample}}}\"\n"
    if norm_lang in ("js", "javascript", "node", "ts", "typescript"):
        return (
            "import { execFileSync } from 'node:child_process';\n"
            f"export const callUri = (payload = {sample}) =>\n"
            f"  JSON.parse(execFileSync('uri', [{json.dumps(target_uri)}, JSON.stringify(payload)], {{ encoding: 'utf8' }}));\n"
        )
    if norm_lang in ("rs", "rust"):
        return (
            "use std::process::Command;\n"
            "pub fn uri(address: &str, jsonl_payload: &str) -> Result<String, String> {\n"
            "    let out = Command::new(\"uri\").arg(address).arg(jsonl_payload).output().map_err(|e| e.to_string())?;\n"
            "    String::from_utf8(out.stdout).map_err(|e| e.to_string())\n"
            "}\n"
            f"// Example: uri({json.dumps(target_uri)}, {json.dumps(sample)})\n"
        )
    if norm_lang in ("go", "golang"):
        return (
            "package uribridge\n\nimport \"os/exec\"\n\n"
            "func Uri(address string, jsonl string) ([]byte, error) {\n"
            "    return exec.Command(\"uri\", address, jsonl).Output()\n"
            "}\n"
            f"// Example: Uri({json.dumps(target_uri)}, {json.dumps(sample)})\n"
        )
    if norm_lang == "php":
        return (
            "<?php\n"
            f"function uri(string $address = {json.dumps(target_uri)}, array $payload = []): array {{\n"
            "    $cmd = sprintf('uri %s %s', escapeshellarg($address), escapeshellarg(json_encode($payload)));\n"
            "    return json_decode((string) shell_exec($cmd), true) ?? [];\n"
            "}\n"
        )
    return (
        "from dockuri import uri\n\n"
        f"def invoke(payload: dict | str | None = None):\n"
        f"    return uri({target_uri!r}, payload or {sample})\n"
    )


def _invoke_single(clean_uri: str, params: dict[str, Any], socket_path: str | None = None) -> dict[str, Any]:
    if clean_uri in _CUSTOM_URI_HANDLERS:
        return _CUSTOM_URI_HANDLERS[clean_uri](params)

    sock = socket_path or params.pop("_socket", None) or os.environ.get("DOCKURI_SOCKET")
    if sock and os.path.exists(str(sock)):
        parts = urlsplit(clean_uri)
        proc_parts = [p for p in parts.path.strip("/").split("/") if p and not re.fullmatch(r"v\d+", p)]
        proc_name = f"{parts.netloc}.{'.'.join(proc_parts)}" if proc_parts else parts.netloc
        return DockuriClient(str(sock)).call(proc_name, params)

    try:
        import dockuri_uri as _runtime_uri  # type: ignore
        res = _runtime_uri.uri(clean_uri, params)
        return res if isinstance(res, dict) else {"status": "ok", "results": res}
    except ImportError:
        pass

    uri_bin = shutil.which("uri") or shutil.which("dockuri")
    if uri_bin:
        cmd = [uri_bin, clean_uri] if os.path.basename(uri_bin) == "uri" else [uri_bin, "uri", clean_uri]
        proc = subprocess.run(
            cmd,
            input=json.dumps(params, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=False,
        )
        out = proc.stdout.strip()
        if out:
            lines = [ln for ln in out.splitlines() if ln.strip()]
            return json.loads(lines[-1])
        return {"status": "error", "error": proc.stderr.strip() or f"Exit {proc.returncode}"}

    return {"status": "error", "uri": clean_uri, "error": f"No handler or runtime found for {clean_uri}"}


import re  # noqa: E402


def uri(address: str, payload: Any = None, *, socket_path: str | None = None, **kwargs: Any) -> dict[str, Any] | list[dict[str, Any]]:
    """Standard `uri('<full-uri>', [payload])` function for cross-project URI execution (DOCK-URI-001)."""
    clean_uri, query_params = _split_uri_and_query(address)
    records, is_batch = parse_jsonl_payload(payload)
    results = [_invoke_single(clean_uri, {**query_params, **rec, **kwargs}, socket_path=socket_path) for rec in records]
    return results if is_batch else results[0]


def uri_jsonl(
    address: str,
    lines: Iterable[str | dict[str, Any]],
    *,
    socket_path: str | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Invoke a URI process over a stream of JSONL lines or dicts and return list of results (DOCK-URI-001)."""
    clean_uri, query_params = _split_uri_and_query(address)
    outputs: list[dict[str, Any]] = []
    for item in lines:
        if isinstance(item, str):
            stripped = item.strip()
            if not stripped:
                continue
            parsed = json.loads(stripped)
            record = parsed if isinstance(parsed, dict) else {"value": parsed}
        elif isinstance(item, dict):
            record = dict(item)
        else:
            record = {"value": item}
        outputs.append(_invoke_single(clean_uri, {**query_params, **record, **kwargs}, socket_path=socket_path))
    return outputs


def uri_main(argv: list[str] | None = None) -> int:
    """Reference CLI entrypoint for `uri <full-uri> [jsonl_or_json ...]`."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(
            "Usage: uri <scheme://authority/path[?k=v]> [json_or_jsonl_payload | @file.jsonl | -]\n"
            "       echo '{\"k\":\"v\"}' | uri <scheme://authority/path>\n"
            "       uri --snippet <lang> <scheme://authority/path>"
        )
        return 0
    if args[0] == "--snippet" and len(args) >= 3:
        print(render_uri_call_snippet(args[2], lang=args[1]), end="")
        return 0

    address, rest = args[0], args[1:]
    payload: Any = None
    if rest:
        payload = sys.stdin.read() if (len(rest) == 1 and rest[0] == "-") else (rest[0] if len(rest) == 1 else "\n".join(rest))
    elif not sys.stdin.isatty():
        stdin_data = sys.stdin.read().strip()
        if stdin_data:
            payload = stdin_data

    result = uri(address, payload)
    if isinstance(result, list):
        for item in result:
            print(json.dumps(item, ensure_ascii=False))
        return 0 if all(r.get("status") != "error" for r in result if isinstance(r, dict)) else 1
    print(json.dumps(result, ensure_ascii=False))
    return 0 if (isinstance(result, dict) and result.get("status") != "error") else 1

