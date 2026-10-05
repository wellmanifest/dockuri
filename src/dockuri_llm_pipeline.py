"""Dockuri LLM Pipeline Synthesizer and DAG Runner (DOCK-FLOW-001).

Implements:
1. LLM Prompt Context Builder: serializes registry procedures into instructions for models.
2. Pipeline Validator: RFC 6901 JSON pointer verification and Kahn's DAG acyclicity check.
3. DAG Executor: Topological dispatch over UDS sockets with CompositeExecutionReceipt.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any
from .dockuri_client import DockuriClient
from .dockuri_registry import DockuriRegistry, ProcedureRecord


def build_llm_context(registry: DockuriRegistry, candidates: list[ProcedureRecord] | None = None) -> str:
    """Build system instructions and catalog of available URI operations for LLM."""
    records = candidates if candidates is not None else list(registry.procedures.values())

    procs_catalog = []
    for r in records:
        procs_catalog.append({
            "uri": r.uri,
            "proc": r.proc,
            "description": r.desc,
            "effect": r.effect,
            "input_schema": r.schema.get("input", {}),
            "output_schema": r.schema.get("output", {}),
        })

    prompt = f"""You are the Dockuri Pipeline Compiler.
Given a natural language request, construct a valid DAG execution pipeline conforming to standard 'dockuri/workflow-v1'.

### AVAILABLE URI PROCEDURES:
{json.dumps(procs_catalog, indent=2, ensure_ascii=False)}

### PIPELINE SCHEMA SPECIFICATION (dockuri/workflow-v1):
- "name": String identifier of the workflow.
- "flow": Array of stages ordered logically.
  Each stage must contain:
    * "id": Unique string identifier for the stage (e.g. "step1_read").
    * "uri": Exact canonical URI from the catalog (e.g. "proc://urirun-connector-fs/fs/read_text/v1").
    * "depends_on": Optional array of step IDs that must finish before this step.
    * "input": Dictionary matching the procedure's input_schema.
      To pass output from a previous stage, use RFC 6901 reference:
      {{"$from": "<previous_step_id>", "path": "/property_name"}}

### RULES:
1. Do not hallucinate URIs. Only use URIs declared in the catalog.
2. If a step uses {{"$from": "stepA", "path": "..."}}, it MUST declare "depends_on": ["stepA"].
3. Pipelines must be acyclic (DAG).
4. Output must be raw JSON conforming to this schema without extra conversational markdown.
"""
    return prompt


def resolve_json_pointer(data: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON pointer against data."""
    if not pointer or pointer == "/" or pointer == "":
        return data
    if not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer (must start with '/'): '{pointer}'")

    tokens = pointer.lstrip("/").split("/")
    current = data
    for tok in tokens:
        tok = tok.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            if tok not in current:
                raise KeyError(f"Property '{tok}' not found in data: {list(current.keys())}")
            current = current[tok]
        elif isinstance(current, list):
            try:
                idx = int(tok)
                current = current[idx]
            except (ValueError, IndexError):
                raise IndexError(f"List index out of range or invalid: '{tok}'")
        else:
            raise TypeError(f"Cannot traverse into scalar value with token '{tok}'")
    return current


def resolve_inputs(raw_input: Any, previous_results: dict[str, Any]) -> Any:
    """Recursively resolve {\"$from\": \"...\", \"path\": \"...\"} references in input values."""
    if isinstance(raw_input, dict):
        if "$from" in raw_input and "path" in raw_input and len(raw_input) == 2:
            source_id = raw_input["$from"]
            pointer = raw_input["path"]
            if source_id not in previous_results:
                raise ValueError(f"Referenced stage '{source_id}' has not produced results yet")
            return resolve_json_pointer(previous_results[source_id], pointer)
        return {k: resolve_inputs(v, previous_results) for k, v in raw_input.items()}
    elif isinstance(raw_input, list):
        return [resolve_inputs(item, previous_results) for item in raw_input]
    return raw_input


def validate_pipeline_dag(pipeline: dict[str, Any], registry: DockuriRegistry | None = None) -> list[str]:
    """Validate DAG acyclicity using Kahn's algorithm and ensure all dependencies exist."""
    if "flow" not in pipeline or not isinstance(pipeline["flow"], list):
        raise ValueError("Pipeline must contain a 'flow' array")

    stages = pipeline["flow"]
    stage_ids = {s["id"] for s in stages if "id" in s}
    if len(stage_ids) != len(stages):
        raise ValueError("Duplicate stage IDs found in pipeline")

    uri_map = {}
    if registry:
        for r in registry.procedures.values():
            uri_map[r.uri] = r

    in_degree: dict[str, int] = {}
    adj: dict[str, list[str]] = {s_id: [] for s_id in stage_ids}

    for s in stages:
        s_id = s["id"]
        uri = s.get("uri")
        if registry and uri not in uri_map:
            raise ValueError(f"Unknown URI in stage '{s_id}': {uri}")

        deps = s.get("depends_on", [])
        in_degree[s_id] = len(deps)
        for d in deps:
            if d not in stage_ids:
                raise ValueError(f"Unknown dependency '{d}' in stage '{s_id}'")
            adj[d].append(s_id)

    # Kahn's algorithm
    queue = [s_id for s_id, deg in in_degree.items() if deg == 0]
    sorted_order = []

    while queue:
        curr = queue.pop(0)
        sorted_order.append(curr)
        for nxt in adj[curr]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if len(sorted_order) != len(stage_ids):
        raise ValueError("Cycle detected in pipeline dependencies (not a valid DAG)")

    return sorted_order


def execute_pipeline_dag(pipeline: dict[str, Any], registry: DockuriRegistry) -> dict[str, Any]:
    """Execute pipeline in topological order, routing each step to its live UDS socket."""
    order = validate_pipeline_dag(pipeline, registry)
    stages_by_id = {s["id"]: s for s in pipeline["flow"]}
    uri_to_proc = {r.uri: r for r in registry.procedures.values()}

    stage_results: dict[str, Any] = {}
    step_reports = []
    step_digests = []

    t_start = time.perf_counter()

    for s_id in order:
        stage = stages_by_id[s_id]
        uri = stage["uri"]
        raw_input = stage.get("input", {})

        # Resolve references
        actual_input = resolve_inputs(raw_input, stage_results)

        proc_rec = uri_to_proc[uri]
        socket_path = proc_rec.transport.get("socket")
        if not socket_path:
            raise ValueError(f"No socket path registered for {uri}")

        client = DockuriClient(socket_path)
        resp = client.call(proc_rec.proc, actual_input)

        if not resp.get("ok"):
            raise RuntimeError(f"Stage '{s_id}' ({proc_rec.proc}) failed: {resp.get('error')}")

        result_val = resp["result"]
        stage_results[s_id] = result_val

        # Step digest
        step_hash = hashlib.sha256(json.dumps({
            "stage_id": s_id,
            "uri": uri,
            "input": actual_input,
            "result": result_val
        }, sort_keys=True).encode()).hexdigest()
        step_digests.append(step_hash)

        step_reports.append({
            "id": s_id,
            "uri": uri,
            "proc": proc_rec.proc,
            "duration_ms": resp["_client_duration_ms"],
            "result": result_val,
        })

    t_end = time.perf_counter()
    total_ms = round((t_end - t_start) * 1000.0, 3)

    receipt = {
        "schema": "wellmanifest.wellman/receipt/v1",
        "kind": "dockuri_workflow_receipt",
        "pipeline_name": pipeline.get("name", "unnamed_workflow"),
        "total_stages": len(order),
        "total_duration_ms": total_ms,
        "pipeline_digest": hashlib.sha256("".join(step_digests).encode()).hexdigest(),
        "step_digests": step_digests,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    return {
        "ok": True,
        "pipeline_name": pipeline.get("name"),
        "stages": step_reports,
        "final_output": stage_results[order[-1]],
        "receipt": receipt,
    }
