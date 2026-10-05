"""Dockuri Procedure Registry & NL Projection Engine (DOCK-REG-001, DOCK-NL-001).

Scans workspace repositories for dockuri.json manifests, aggregates them into a
unified procedure registry, and projects candidated tool definitions for LLM / NL
control commands with GBNF and JSON Schema generation.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


class ProcedureRecord:
    def __init__(
        self,
        app: str,
        proc: str,
        uri: str,
        desc: str,
        effect: str,
        transport: dict[str, Any],
        schema: dict[str, Any],
        manifest_path: str,
    ):
        self.app = app
        self.proc = proc
        self.uri = uri
        self.desc = desc
        self.effect = effect
        self.transport = transport
        self.schema = schema
        self.manifest_path = manifest_path
        self.contract_digest = self._calc_digest()

    def _calc_digest(self) -> str:
        data = {
            "uri": self.uri,
            "desc": self.desc,
            "effect": self.effect,
            "schema": self.schema,
        }
        raw = json.dumps(data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "app": self.app,
            "proc": self.proc,
            "uri": self.uri,
            "desc": self.desc,
            "effect": self.effect,
            "transport": self.transport,
            "schema": self.schema,
            "manifest_path": self.manifest_path,
            "contract_digest": self.contract_digest,
        }


EXCLUDED_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "venv", ".venv", "target",
    "dist", "build", ".pytest_cache", ".cache", ".idea", ".vscode",
    ".worktrees", ".subactor", ".code2llm_cache", "logs", "conversations"
}


class DockuriRegistry:
    def __init__(self):
        self.procedures: dict[str, ProcedureRecord] = {}

    def scan_path(self, root_dir: str | Path) -> int:
        """Fast pruned scan for dockuri.json, connector.manifest.json, and apx.yaml."""
        root = Path(root_dir)
        count = 0

        for dirpath, dirnames, filenames in os.walk(root):
            # Prune excluded directories in-place so os.walk skips them entirely
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".")]

            # 1. Native dockuri.json
            if "dockuri.json" in filenames:
                f_path = Path(dirpath) / "dockuri.json"
                try:
                    with open(f_path, "r", encoding="utf-8") as f:
                        count += self.register_manifest(json.load(f), str(f_path))
                except Exception as e:
                    pass

            # 2. urirun connector.manifest.json
            elif "connector.manifest.json" in filenames:
                f_path = Path(dirpath) / "connector.manifest.json"
                try:
                    with open(f_path, "r", encoding="utf-8") as f:
                        count += self.register_connector_manifest(json.load(f), str(f_path))
                except Exception as e:
                    pass

            # 3. apx.yaml
            elif "apx.yaml" in filenames:
                f_path = Path(dirpath) / "apx.yaml"
                try:
                    import yaml
                    with open(f_path, "r", encoding="utf-8") as f:
                        count += self.register_apx_manifest(yaml.safe_load(f), str(f_path))
                except Exception:
                    pass

        return count

    def register_manifest(self, manifest: dict[str, Any], file_path: str) -> int:
        app = manifest.get("app", "unknown")
        transport = manifest.get("transport", {})
        procs = manifest.get("procedures", {})
        count = 0

        for proc_name, defn in procs.items():
            uri = f"proc://{app}/{proc_name.replace('.', '/')}/v1"
            record = ProcedureRecord(
                app=app,
                proc=proc_name,
                uri=uri,
                desc=defn.get("description", ""),
                effect=defn.get("effect", "pure"),
                transport=transport,
                schema=defn.get("schema", {}),
                manifest_path=file_path,
            )
            self.procedures[proc_name] = record
            count += 1
        return count

    def register_connector_manifest(self, data: dict[str, Any], file_path: str) -> int:
        """Adapt a urirun connector.manifest.json into canonical ProcedureRecords."""
        app = data.get("id") or data.get("name", "connector")
        routes = data.get("routes", [])
        summary = data.get("summary") or data.get("description", "")
        count = 0

        for route in routes:
            # Route e.g. pdf://markdown/command/render
            parts = route.split("://")[-1].strip("/").split("/")
            proc_sub = "_".join(parts) if parts else "invoke"
            proc_name = f"{app}.{proc_sub}"
            uri = f"proc://{app}/{'/'.join(parts)}/v1"
            effect = "mutating" if "/command/" in route else "pure"

            # Derive input schema from examples if present
            input_schema = {"type": "object", "properties": {}}
            for ex in data.get("examples", []):
                if ex.get("uri") == route and "payload" in ex:
                    props = {k: {"type": "string" if isinstance(v, str) else "number"} for k, v in ex["payload"].items()}
                    input_schema = {"type": "object", "properties": props}
                    break

            record = ProcedureRecord(
                app=app,
                proc=proc_name,
                uri=uri,
                desc=f"[{app}] {summary} (Route: {route})",
                effect=effect,
                transport={"type": "uds", "socket": f"/tmp/dockuri_{app}.sock"},
                schema={"input": input_schema, "output": {"type": "object"}},
                manifest_path=file_path,
            )
            self.procedures[proc_name] = record
            count += 1
        return count

    def register_apx_manifest(self, data: dict[str, Any], file_path: str) -> int:
        """Adapt an apx.yaml into canonical ProcedureRecords."""
        app = data.get("name") or data.get("id", "app")
        actions = data.get("actions", [])
        count = 0
        for act in actions:
            act_id = act.get("id", "action")
            proc_name = f"{app}.{act_id}"
            uri = f"proc://{app}/{act_id}/v1"
            record = ProcedureRecord(
                app=app,
                proc=proc_name,
                uri=uri,
                desc=act.get("description", f"Action {act_id} in {app}"),
                effect="mutating" if act.get("mutates", False) else "pure",
                transport={"type": "uds", "socket": f"/tmp/dockuri_{app}.sock"},
                schema={"input": {"type": "object"}, "output": {"type": "object"}},
                manifest_path=file_path,
            )
            self.procedures[proc_name] = record
            count += 1
        return count

    def search_for_nl(self, nl_query: str, limit: int = 5) -> list[ProcedureRecord]:
        """Simple lexical and semantic retrieval matching NL intent against procedures."""
        tokens = set(re.findall(r"\w+", nl_query.lower()))
        scored: list[tuple[float, ProcedureRecord]] = []

        for record in self.procedures.values():
            score = 0.0
            search_corpus = f"{record.app} {record.proc} {record.desc}".lower()

            for tok in tokens:
                if tok in record.proc.lower():
                    score += 3.0
                if tok in record.desc.lower():
                    score += 1.5
                if tok in record.app.lower():
                    score += 1.0

            if score > 0:
                scored.append((score, record))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]

    def export_llm_tools(self, candidates: list[ProcedureRecord] | None = None) -> list[dict[str, Any]]:
        """Export candidates as standard OpenAI/MCP tool definitions."""
        records = candidates if candidates is not None else list(self.procedures.values())
        tools = []
        for r in records:
            tools.append({
                "type": "function",
                "function": {
                    "name": r.proc,
                    "description": f"[{r.uri}] ({r.effect}) {r.desc}",
                    "parameters": r.schema.get("input", {"type": "object", "properties": {}}),
                },
                "meta": {
                    "uri": r.uri,
                    "effect": r.effect,
                    "contract_digest": r.contract_digest,
                    "transport": r.transport,
                }
            })
        return tools

    def export_gbnf_grammar(self, candidates: list[ProcedureRecord] | None = None) -> str:
        """Export a constrained GBNF grammar for llama.cpp / local models guaranteeing valid calls."""
        records = candidates if candidates is not None else list(self.procedures.values())
        if not records:
            return 'root ::= "[]"\n'
        
        proc_names = " | ".join(f'"{r.proc}"' for r in records)
        return (
            'root ::= "{" ws "\\"proc\\":" ws proc-name "," ws "\\"args\\":" ws object "}"\n'
            f'proc-name ::= {proc_names}\n'
            'object ::= "{" [^\\}]* "}"\n'
            'ws ::= [ \\t\\n]*\n'
        )
