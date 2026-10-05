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

---

## 🚀 Quick Start

### 1. Validate a project's `dockuri.json`
```bash
python3 src/dockuri_check.py --manifest path/to/dockuri.json
```

### 2. Probe a live worker for latency compliance
```bash
python3 src/dockuri_check.py --manifest dockuri.json --ping
```

### 3. Run multi-stage pipeline
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

## 🧪 Testing

```bash
pytest tests/ -v
```
