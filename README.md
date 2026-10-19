# Wellmanifest Dockuri

Standard and runtime profile for **Zero-Cold-Start URI Function Invocation, Fast IPC, and Pipeline Chaining** across heterogeneous language environments (Python, Node.js, Rust, PHP, Go).

---

## 🎯 Purpose & Latency Budget

When functions from different projects are combined into an automated pipeline, traditional container spin-up (`docker run`) or interpreter boots (`python script.py`) incur massive 400ms – 2500ms penalties per hop.

**Dockuri eliminates this overhead down to < 2.0 ms per hop** using:
1. **Pre-warmed Worker Daemons** listening on **Unix Domain Sockets (UDS)** or `stdio`.
2. **Standardized NDJSON IPC Framing** (`id`, `proc`, `args`, `ctx`, `shm`).
3. **Zero-Copy Shared Memory (`/dev/shm`)** for media/binary payloads > 64 KB.
4. **Declarative DAG Pipeline Chaining** with a single, tamper-proof **CompositeExecutionReceipt** (`wellmanifest.wellman/receipt/v1`).

---

## 📐 Specification & Rules

Detailed normative specification is in [`spec/DOCKURI_STANDARD.md`](spec/DOCKURI_STANDARD.md):
- `DOCK-MAN-001`: Procedure Manifest Contract (`dockuri.json`)
- `DOCK-IPC-001`: IPC Protocol Envelope (NDJSON)
- `DOCK-UDS-001`: Unix Domain Socket Path & Permissions (`0660`)
- `DOCK-SHM-001`: Zero-Copy Shared Memory Protocol (`/dev/shm/dockuri/`)
- `DOCK-LFT-001`: Auto-Spawn and Graceful Fallback
- `DOCK-PNG-001`: System Ping & Latency Budget (< 2.0 ms)
- `DOCK-PIP-001`: Pipeline Composition & Composite Execution Receipt
- `DOCK-URI-001`: Universal Polyglot URI Invocation Contract (`uri('')` & `uri <address> + JSONL`)
- `DOCK-LFC-001`: Declarative URI Process Lifecycle & Cross-Project Deduplication (`proc://system/process/manage/v1`)
- `DOCK-PRM-001`: Normative Generic Prompts & URI-First Enforcement (`--check-uri-standard`)
- `DOCK-DISP-001`: Universal NL Sentence Dispatch on Any Dockuri-Runnable Project
- `DOCK-ACC-001`: Fast URI Execution Acceleration (Floor -> Standard -> Opportunistic)
- `DOCK-MCP-001`: Model Context Protocol (MCP) Standard Server Bridge (`dockuri-mcp`)

---

## 🚀 Quick Start

### 0. Use via MCP (Model Context Protocol for Google Gemini, Claude, Codex)
Configure `dockuri-mcp` in your agent's MCP configuration (`mcpServers`):
```json
{
  "mcpServers": {
    "dockuri": {
      "command": "dockuri-mcp"
    }
  }
}
```
Available tools (with `dockuri_*` and `dockuri.*` aliases):
* `dockuri_execute_sentence` (`dockuri.uri` + `sentence`): Execute any NL command on any project (`< 1 ms` dry-run / `< 6 ms` exec).
* `dockuri_call_uri` (`dockuri.uri`): Call canonical URI processes with args or JSONL.
* `dockuri_search_procedures` (`dockuri.search`): Search organization procedures semantically/lexically (`< 0.5 ms`).
* `dockuri_list_projects`: Discover all Dockuri-runnable projects (`~12.5 ms` warm).
* `dockuri_manage_process` (`dockuri.process_manage`): Generate, modify, relocate, and render polyglot snippets (`DOCK-LFC-001`).
* `dockuri_check_conformance`: Validate project against Dockuri standards (`< 2.5 ms`).
* `dockuri_prompt_registry` (`dockuri.prompt_registry`): Emit dynamic bounded TOON registry (`dockuri.llm-bounded-registry/v1`, 97.4% size reduction) + constrained JSON Schema.
* `dockuri_provider_config` (`dockuri.provider_config`): Generate ready-to-use MCP configs for Google Antigravity/Gemini, OpenAI Codex, Anthropic Claude, IDE, and Shell CLI.

### 1. Execute Any Sentence on Any Project Runnable via Dockuri (Fast Method)
```bash
# 1. Enforce readiness & test sentence dispatch for any project:
python3 src/dockuri_check.py --check-uri-standard --project /home/tom/github/dockuri/willops/willops --test-sentence "wyszukaj dockuri root w willops"

# 2. Call directly via universal CLI (streaming JSONL stdin/args):
uri "proc://willops/run/instruction/v1" '{"instruction": "audyt zależności", "dry_run": true}'

# 3. Call in Python (sub-millisecond in-process / UDS dispatch):
from src.dockuri_client import uri
result = uri("proc://system/sprint/deduplicate/v1", {"action": "audit", "dry_run": True})
```

### 2. Validate a Project's `dockuri.json` or `dockuri.yaml`
```bash
python3 src/dockuri_check.py --manifest path/to/dockuri.json
python3 src/dockuri_check.py --check-uri-standard --proc-manifest /home/tom/github/dockuri/dockuri.yaml
```

### 3. Probe a Live Worker for Latency Compliance (< 2.0 ms)
```bash
python3 src/dockuri_check.py --manifest dockuri.json --ping
```

### 4. Run Multi-Stage Pipeline
```python
from src.dockuri_client import run_pipeline

stages = [
    {"proc": "codec.base64_encode", "socket": "/run/dockuri/codec.sock", "input_key": "text"},
    {"proc": "taskand.calc_metrics", "socket": "/run/dockuri/taskand.sock", "input_key": "payload"}
]

result = run_pipeline(stages, initial_input="invoice data")
print(result["receipt"])  # CompositeExecutionReceipt (SHA-256 DAG)
```

---

## ⚡ Why the Fast Method Accelerates LLMs (DOCK-ACC-001)

1. **90–95% Token Savings**: Instead of generating a 50-line custom Python/Bash script, an LLM outputs 1 concise line: `uri('proc://<app>/<action>', payload)`.
2. **Sub-Millisecond Execution**: Pre-warmed UDS daemons and in-process cdylib eliminate cold container spin-up (400ms – 2500ms $\to$ < 2.0 ms).
3. **Cross-Project Reusability**: All projects in the ecosystem reuse centralized URI processes from `dockuri` without duplicating code.

---

## 🧪 Testing

```bash
pytest tests/ -v
```
