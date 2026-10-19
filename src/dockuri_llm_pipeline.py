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
try:
    from .dockuri_client import DockuriClient
    from .dockuri_registry import DockuriRegistry, ProcedureRecord
except ImportError:
    from dockuri_client import DockuriClient  # type: ignore
    from dockuri_registry import DockuriRegistry, ProcedureRecord  # type: ignore

GENERIC_URI_PROMPTS: dict[str, dict[str, str]] = {
    "system_uri_first": {
        "pl": (
            "Stosuj zasadę URI-First (wellmanifest/dockuri DOCK-URI-001 & DOCK-LFC-001): "
            "zanim napiszesz nową funkcję pomocniczą lub skrypt w projekcie '{project_root}', "
            "sprawdź dostępne procesy w katalogu dockuri/urirun (`uri --catalog`). "
            "Wywołuj istniejące procesy przez `uri('<pełny_adres_uri>', payload)` lub strumieniowo "
            "`uri_jsonl('<pełny_adres_uri>', lines)` / `uri '<pełny_adres_uri>'` + JSONL. "
            "Gdy logika powtarza się między projektami, zarejestruj ją lub przenieś przez "
            "`uri('proc://system/process/manage/v1', {{'action': 'generate|modify|relocate|snippet', ...}})`."
        ),
        "en": (
            "Follow the URI-First policy (wellmanifest/dockuri DOCK-URI-001 & DOCK-LFC-001): "
            "before writing a new helper function or script in '{project_root}', inspect available "
            "URI processes via `uri --catalog`. Invoke reusable processes via `uri('<full_uri>', payload)` "
            "or `uri_jsonl('<full_uri>', lines)` / `uri '<full_uri>'` + JSONL. Manage shared process lifecycle "
            "via `uri('proc://system/process/manage/v1', {{'action': 'generate|modify|relocate|snippet', ...}})`."
        ),
    },
    "discover_and_run": {
        "pl": (
            "Dla zadania: \"{task_description}\" w repozytorium '{project_root}': "
            "1) dobierz odpowiedni proces URI z katalogu `dockuri` (`proc://...`) lub `urirun` (`task://...`), "
            "2) wywołaj go przez `uri('<pełny_adres_uri>', payload)` z wymaganym ładunkiem JSON, "
            "3) zweryfikuj pole `status` oraz zwróć wynik bez duplikowania logiki w lokalnym skrypcie."
        ),
        "en": (
            "For task \"{task_description}\" in repository '{project_root}': "
            "1) select the matching URI process from `dockuri` (`proc://...`) or `urirun` (`task://...`), "
            "2) invoke it via `uri('<full_uri>', payload)`, and "
            "3) verify `status` and return the result without duplicating logic locally."
        ),
    },
    "extract_to_dockuri": {
        "pl": (
            "Przeanalizuj plik '{target_file}' pod kątem logiki powtarzalnej w wielu projektach. "
            "Wyodrębnij ją jako proces URI '{target_uri}' za pomocą "
            "`uri('proc://system/process/manage/v1', {{'action': 'generate', 'target_uri': '{target_uri}', ...}})`, "
            "wygeneruj snippet wywołania dla języka '{language}' (`action='snippet'`) i zastąp lokalną implementację "
            "w '{target_file}' wywołaniem `uri('{target_uri}', payload)`."
        ),
        "en": (
            "Analyze '{target_file}' for logic duplicated across projects. "
            "Extract it into URI process '{target_uri}' via "
            "`uri('proc://system/process/manage/v1', {{'action': 'generate', 'target_uri': '{target_uri}', ...}})`, "
            "generate the '{language}' call snippet (`action='snippet'`), and replace the local implementation "
            "in '{target_file}' with `uri('{target_uri}', payload)`."
        ),
    },
    "modify_and_relocate": {
        "pl": (
            "Zaktualizuj lub przenieś proces URI '{target_uri}' pod nowy kanoniczny adres '{new_uri}' "
            "używając `uri('proc://system/process/manage/v1', {{'action': 'relocate', 'target_uri': '{target_uri}', 'new_uri': '{new_uri}'}})`. "
            "Zachowaj stary adres w liście `aliases`, aby wszystkie dotychczasowe wywołania `uri('{target_uri}', ...)` "
            "w innych projektach działały bez przerwania kompatybilności."
        ),
        "en": (
            "Update or relocate URI process '{target_uri}' to the new canonical address '{new_uri}' "
            "via `uri('proc://system/process/manage/v1', {{'action': 'relocate', 'target_uri': '{target_uri}', 'new_uri': '{new_uri}'}})`. "
            "Preserve the previous address in `aliases` so existing callers across repositories remain backward-compatible."
        ),
    },
    "batch_jsonl_stream": {
        "pl": (
            "Wykonaj operację '{target_uri}' wsadowo dla wielu celów w '{project_root}' w jednym przebiegu: "
            "przekaż listę obiektów wejściowych jako strumień JSONL do `uri_jsonl('{target_uri}', lines)` "
            "lub w terminalu `cat targets.jsonl | uri '{target_uri}'` i zagreguj wyniki."
        ),
        "en": (
            "Execute '{target_uri}' in batch across multiple targets in '{project_root}' in a single pass: "
            "stream the input records as JSONL to `uri_jsonl('{target_uri}', lines)` or "
            "`cat targets.jsonl | uri '{target_uri}'` and aggregate the responses."
        ),
    },
    "streamline_remediate": {
        "pl": (
            "Uruchom analizę `wellmanifest/streamline` dla projektu '{project_root}', odczytaj deskryptory "
            "`uriDelegation` z planu refaktoryzacji, zredukuj złożoność cyklomatyczną i naruszenia warstw "
            "w pliku '{target_file}', a następnie zweryfikuj poprawkę procesem "
            "`uri('proc://system/self-improvement/diagnose/v1', {{'path': '{target_file}', 'threshold': 10}})`."
        ),
        "en": (
            "Run `wellmanifest/streamline` on '{project_root}', inspect the `uriDelegation` descriptors in the plan, "
            "remediate cyclomatic complexity and layer violations in '{target_file}', and verify the fix via "
            "`uri('proc://system/self-improvement/diagnose/v1', {{'path': '{target_file}', 'threshold': 10}})`."
        ),
    },
    "project_sentence_dispatch": {
        "pl": (
            "Dla dowolnego polecenia: \"{sentence}\" w projekcie '{project_root}', który może być uruchomiony przez dockuri: "
            "1) dopasuj lub skieruj zdanie do procesu URI (`proc://{project}/...` lub `dockuri://{project}/exec`), "
            "2) wywołaj go szybką metodą `uri(...)` lub `uri <adres> [jsonl]`, "
            "3) odbierz wynik ze statusem i kwitem wykonania bez tworzenia nowych skryptów pomocniczych."
        ),
        "en": (
            "For any instruction: \"{sentence}\" in project '{project_root}' runnable via dockuri: "
            "1) route the sentence to a URI process (`proc://{project}/...` or `dockuri://{project}/exec`), "
            "2) execute it using the fast `uri(...)` or `uri <address> [jsonl]` method, "
            "3) retrieve the result with status and receipt without writing ad-hoc scripts."
        ),
    },
}


def build_generic_uri_prompt(template_id: str, lang: str = "pl", **kwargs: Any) -> str:
    """Render a normative generic prompt (DOCK-PRM-001) for any project or target."""
    if template_id not in GENERIC_URI_PROMPTS:
        raise KeyError(f"Unknown generic prompt template '{template_id}'. Available: {sorted(GENERIC_URI_PROMPTS)}")
    lang_map = GENERIC_URI_PROMPTS[template_id]
    template = lang_map.get(lang) or lang_map["pl"]
    defaults = {
        "project_root": "<ścieżka_projektu>",
        "target_file": "<ścieżka_pliku>",
        "task_description": "<opis_zadania>",
        "target_uri": "proc://<domena>/<moduł>/<akcja>/v1",
        "new_uri": "proc://<domena>/<moduł>/<akcja>/v2",
        "language": "python",
        "sentence": "<zdanie_lub_polecenie>",
        "project": "<projekt>",
    }
    defaults.update({k: str(v) for k, v in kwargs.items()})
    return template.format(**defaults)


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

    prompt = f"""You are the Dockuri Pipeline Compiler (DOCK-FLOW-001, DOCK-URI-001, DOCK-LFC-001, DOCK-PRM-001).
Given a natural language request, construct a valid DAG execution pipeline conforming to standard 'dockuri/workflow-v1' or invoke canonical URI processes via `uri('<full_uri>', payload)` / `uri_jsonl('<full_uri>', lines)`.

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
5. Prefer `uri('<full_uri>', payload)` and `proc://system/process/manage/v1` (`generate`, `modify`, `relocate`, `snippet`) over duplicating helper logic across repositories.
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
