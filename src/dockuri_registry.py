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


def _stem_token(w: str) -> str:
    w = w.lower().strip()
    if w.startswith("z") and len(w) > 4 and w[1] in "bcdfgjklmnprstvwz":
        w = w[1:]
    for pref in ("wy", "od", "po", "roz", "za", "prze"):
        if w.startswith(pref) and len(w) > len(pref) + 3:
            w = w[len(pref):]
            break
    return (
        w.replace("k", "c")
        .replace("ń", "n")
        .replace("ó", "o")
        .replace("ą", "a")
        .replace("ę", "e")
        .replace("ś", "s")
        .replace("ł", "l")
        .replace("ż", "z")
        .replace("ź", "z")
    )


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
        self._proc_lower = proc.lower()
        self._uri_lower = uri.lower()
        self._desc_lower = desc.lower()
        self._app_lower = app.lower()
        search_corpus = f"{self._app_lower} {self._proc_lower} {self._desc_lower} {self._uri_lower}"
        self._corpus_tokens = [t for t in re.findall(r"\w+", search_corpus) if len(t) > 1]
        self._corpus_stems = {_stem_token(t) for t in self._corpus_tokens}

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
    ".worktrees", ".subactor", ".code2llm_cache", "logs", "conversations",
    ".rescue", "archive", "benchmarks", "evidence", "wheels", "__pycache__",
    "tests", "test", "docs", "assets", "public", "coverage", "htmlcov",
    "vendor", "third_party", "tmp", "out", ".planfile", ".wup", ".tox", ".mypy_cache",
}


def _safe_yaml_load(stream: Any) -> Any:
    import yaml  # type: ignore
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    return yaml.load(stream, Loader=loader)


class DockuriRegistry:
    def __init__(self):
        self.procedures: dict[str, ProcedureRecord] = {}

    def scan_path(self, root_dir: str | Path, max_depth: int = 3) -> int:
        """Fast depth-bounded pruned scan for dockuri.yaml, dockuri.json, uriprocess.json, connector.manifest.json, and apx.yaml."""
        root = Path(root_dir).resolve()
        if not root.exists():
            return 0
        count = 0

        for dirpath, dirnames, filenames in os.walk(root):
            cur = Path(dirpath)
            try:
                rel_depth = len(cur.relative_to(root).parts)
            except ValueError:
                rel_depth = 0
            if rel_depth >= max_depth:
                dirnames[:] = []
            else:
                dirnames[:] = [
                    d for d in dirnames
                    if d not in EXCLUDED_DIRS and not d.startswith(".") and not d.endswith("-archive")
                ]

            fset = set(filenames)
            # 0. Native dockuri.yaml / dockuri.yml (dockuri/proc-v2)
            if "dockuri.yaml" in fset or "dockuri.yml" in fset:
                f_name = "dockuri.yaml" if "dockuri.yaml" in fset else "dockuri.yml"
                f_path = cur / f_name
                try:
                    with open(f_path, "r", encoding="utf-8") as f:
                        count += self.register_dockuri_yaml_manifest(_safe_yaml_load(f), str(f_path))
                except Exception:
                    pass

            # 1. Native dockuri.json
            elif "dockuri.json" in fset:
                f_path = cur / "dockuri.json"
                try:
                    with open(f_path, "r", encoding="utf-8") as f:
                        count += self.register_manifest(json.load(f), str(f_path))
                except Exception:
                    pass

            # 2. uriprocess.json (uriprocess/v1)
            elif "uriprocess.json" in fset:
                f_path = cur / "uriprocess.json"
                try:
                    with open(f_path, "r", encoding="utf-8") as f:
                        count += self.register_uriprocess_manifest(json.load(f), str(f_path))
                except Exception:
                    pass

            # 3. urirun connector.manifest.json
            elif "connector.manifest.json" in fset:
                f_path = cur / "connector.manifest.json"
                try:
                    with open(f_path, "r", encoding="utf-8") as f:
                        count += self.register_connector_manifest(json.load(f), str(f_path))
                except Exception:
                    pass

            # 4. apx.yaml
            elif "apx.yaml" in fset:
                f_path = cur / "apx.yaml"
                try:
                    with open(f_path, "r", encoding="utf-8") as f:
                        count += self.register_apx_manifest(_safe_yaml_load(f), str(f_path))
                except Exception:
                    pass

        if (root / "python" / "dockuri_uri.py").is_file() or (root / ".planfile").is_dir():
            count += self._register_builtin_dockuri_runtime(root)

        return count

    def register_dockuri_yaml_manifest(self, data: dict[str, Any], file_path: str) -> int:
        """Adapt a dockuri.yaml (dockuri/proc-v2) into canonical ProcedureRecords."""
        if not isinstance(data, dict):
            return 0
        raw_procs = data.get("processes")
        if raw_procs is not None:
            proc_list = raw_procs if isinstance(raw_procs, list) else [
                {"uri": u, **(defn if isinstance(defn, dict) else {})}
                for u, defn in raw_procs.items()
            ]
        elif data.get("uri"):
            proc_list = [data]
        else:
            proc_list = []
        count = 0
        for item in proc_list:
            if not isinstance(item, dict):
                continue
            uri = str(item.get("uri") or "").strip()
            if not uri or "://" not in uri:
                continue
            parts = uri.split("://")[-1].strip("/").split("/")
            app = parts[0] if parts else "proc"
            proc_sub = ".".join(parts[1:]) if len(parts) > 1 else "run"
            proc_name = f"{app}.{proc_sub}"
            desc = str(item.get("description") or f"Process {uri}")
            effect = "mutating" if any(w in uri for w in ("modify", "relocate", "upsert", "delete", "heal")) else "pure"
            record = ProcedureRecord(
                app=app,
                proc=proc_name,
                uri=uri,
                desc=desc,
                effect=effect,
                transport={"type": "cli", "run": item.get("run", [])},
                schema={"input": {"type": "object"}, "output": {"type": "object"}},
                manifest_path=file_path,
            )
            self.procedures[proc_name] = record
            count += 1
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

    def register_uriprocess_manifest(self, data: dict[str, Any], file_path: str) -> int:
        """Adapt a uriprocess.json (uriprocess/v1) into canonical ProcedureRecords."""
        if not isinstance(data, dict):
            return 0
        pkg = str(data.get("package") or Path(file_path).parent.name or "uriprocess")
        uris = data.get("public_uris") or []
        desc_base = str(data.get("description") or f"URI process in {pkg}")
        count = 0
        for raw_uri in uris:
            uri = str(raw_uri or "").strip()
            if not uri or "://" not in uri:
                continue
            parts = uri.split("://")[-1].strip("/").split("/")
            app = parts[0] if parts else pkg
            proc_sub = ".".join(parts[1:]) if len(parts) > 1 else "run"
            proc_name = f"{app}.{proc_sub}"
            record = ProcedureRecord(
                app=app,
                proc=proc_name,
                uri=uri,
                desc=f"[{pkg}] {desc_base} ({uri})",
                effect="mutating" if any(w in uri for w in ("run", "modify", "relocate", "upsert", "heal")) else "pure",
                transport={"type": "cdylib", "package": pkg},
                schema={"input": {"type": "object"}, "output": {"type": "object"}},
                manifest_path=file_path,
            )
            self.procedures[proc_name] = record
            count += 1
        return count

    def _register_builtin_dockuri_runtime(self, root: Path) -> int:
        """Register built-in Dockuri system URI processes for the dockuri runtime repository."""
        builtins = [
            ("system", "system.sprint.deduplicate.v1", "proc://system/sprint/deduplicate/v1", "Deduplicate .planfile/sprints/current.yaml and reconcile done/stale tickets across projects", "mutating"),
            ("system", "system.process.manage.v1", "proc://system/process/manage/v1", "Generate, modify, relocate, extract, catalog, and render snippets for URI processes", "mutating"),
            ("system", "system.process.prompt_registry.v1", "proc://system/process/prompt-registry/v1", "Generate prompt-tailored URI command shortlist, TOON bounded registry, and constrained JSON Schema for LLM", "pure"),
            ("system", "system.process.llm_context.v1", "proc://system/process/llm-context/v1", "Emit bounded TOON registry and constrained JSON Schema for LLM context injection", "pure"),
            ("system", "system.worktree.promote.v1", "proc://system/worktree/promote/v1", "Promote verified worktrees onto main and prune clean detached staging checkouts", "mutating"),
            ("system", "system.self_improvement.diagnose.v1", "proc://system/self-improvement/diagnose/v1", "Przeprowadź audyt stanu projektu, diagnostykę autonomii i wykonaj testy", "pure"),
            ("system", "system.queue.heal.v1", "proc://system/queue/heal/v1", "Audit and heal stalled task queues and expired leases", "mutating"),
        ]
        mpath = str(root / "python" / "dockuri_uri.py")
        count = 0
        for app, proc_name, uri, desc, effect in builtins:
            if proc_name not in self.procedures:
                self.procedures[proc_name] = ProcedureRecord(
                    app=app,
                    proc=proc_name,
                    uri=uri,
                    desc=desc,
                    effect=effect,
                    transport={"type": "in-process", "module": "dockuri_uri"},
                    schema={"input": {"type": "object"}, "output": {"type": "object"}},
                    manifest_path=mpath,
                )
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
        """Fast pre-tokenized lexical and stem retrieval matching NL intent against procedures."""
        raw_tokens = [t for t in re.findall(r"\w+", nl_query.lower()) if len(t) > 1]
        stems = {_stem_token(t) for t in raw_tokens}
        scored: list[tuple[float, ProcedureRecord]] = []

        for record in self.procedures.values():
            score = 0.0
            for tok in raw_tokens:
                if tok in record._proc_lower or tok in record._uri_lower:
                    score += 3.0
                elif tok in record._desc_lower:
                    score += 1.5
                elif tok in record._app_lower:
                    score += 1.0

            for st in stems:
                if st in record._corpus_stems:
                    score += 1.0
                elif len(st) >= 4:
                    prefix = st[:4]
                    for c_st in record._corpus_stems:
                        if len(c_st) >= 4 and (st.startswith(c_st[:4]) or c_st.startswith(prefix)):
                            score += 1.0
                            break

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


_REGISTRY_CACHE: dict[tuple[str, int], tuple[int, DockuriRegistry]] = {}


def get_cached_registry(root_dir: str | Path, max_depth: int = 3) -> DockuriRegistry:
    """Return an mtime-cached DockuriRegistry for root_dir to avoid repeated os.walk scans."""
    resolved = Path(root_dir).resolve()
    key = (str(resolved), max_depth)
    try:
        mtime = resolved.stat().st_mtime_ns
        for mname in ("dockuri.yaml", "dockuri.yml", "dockuri.json", "uriprocess.json", "apx.yaml", "connector.manifest.json"):
            mf = resolved / mname
            if mf.is_file():
                mtime ^= mf.stat().st_mtime_ns
    except OSError:
        mtime = 0
    cached = _REGISTRY_CACHE.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    reg = DockuriRegistry()
    reg.scan_path(resolved, max_depth=max_depth)
    _REGISTRY_CACHE[key] = (mtime, reg)
    return reg


