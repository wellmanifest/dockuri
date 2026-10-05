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


class DockuriRegistry:
    def __init__(self):
        self.procedures: dict[str, ProcedureRecord] = {}

    def scan_path(self, root_dir: str | Path) -> int:
        """Scan a directory recursively for dockuri.json files and register procedures."""
        root = Path(root_dir)
        count = 0
        for manifest_file in root.rglob("dockuri.json"):
            # Skip hidden folders, venvs, git
            parts = manifest_file.parts
            if any(p.startswith(".") or p in ("venv", "node_modules", "target") for p in parts[:-1]):
                continue
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                count += self.register_manifest(manifest, str(manifest_file))
            except Exception as e:
                print(f"Warning: Failed to parse {manifest_file}: {e}")
        return count

    def register_manifest(self, manifest: dict[str, Any], file_path: str) -> int:
        app = manifest.get("app", "unknown")
        transport = manifest.get("transport", {})
        procs = manifest.get("procedures", {})
        count = 0

        for proc_name, defn in procs.items():
            # Canonical URI: proc://<app>/<proc_name>/v1
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
