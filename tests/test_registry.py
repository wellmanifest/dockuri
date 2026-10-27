import pytest
from pathlib import Path
from src.dockuri_registry import DockuriRegistry

def test_registry_scan_and_nl_search():
    reg = DockuriRegistry()
    
    # 1. Register base64 manifest
    b64_manifest = {
        "app": "base64",
        "version": "0.1.0",
        "transport": {"type": "uds", "socket": "/tmp/b64.sock"},
        "procedures": {
            "base64.encode": {
                "description": "Encode string or payload into Base64 format.",
                "effect": "pure",
                "schema": {"input": {"type": "object", "properties": {"text": {"type": "string"}}}}
            },
            "base64.decode": {
                "description": "Decode Base64 string into plaintext.",
                "effect": "pure",
                "schema": {"input": {"type": "object", "properties": {"text": {"type": "string"}}}}
            }
        }
    }
    # 2. Register curi manifest
    curi_manifest = {
        "app": "curi",
        "version": "0.1.0",
        "transport": {"type": "uds", "socket": "/tmp/curi.sock"},
        "procedures": {
            "curi.classify_uri": {
                "description": "Classify URI into scheme, class, verb and mutation capability.",
                "effect": "pure",
                "schema": {"input": {"type": "object", "properties": {"uri": {"type": "string"}}}}
            }
        }
    }

    reg.register_manifest(b64_manifest, "/dummy/b64/dockuri.json")
    reg.register_manifest(curi_manifest, "/dummy/curi/dockuri.json")

    assert len(reg.procedures) == 3
    assert "base64.encode" in reg.procedures
    assert "curi.classify_uri" in reg.procedures

    # Verify canonical URI
    b64_rec = reg.procedures["base64.encode"]
    assert b64_rec.uri == "proc://base64/base64/encode/v1"
    assert len(b64_rec.contract_digest) == 64

    # 3. Test NL Search
    res_b64 = reg.search_for_nl("proszę zakoduj tekst base64", limit=2)
    assert len(res_b64) > 0
    assert res_b64[0].proc == "base64.encode"

    res_curi = reg.search_for_nl("classify and parse uri capabilities", limit=2)
    assert len(res_curi) > 0
    assert res_curi[0].proc == "curi.classify_uri"

    # 4. Test LLM Tool Export
    tools = reg.export_llm_tools([b64_rec])
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "base64.encode"
    assert "proc://base64/base64/encode/v1" in tools[0]["function"]["description"]

    # 5. Test GBNF Grammar Export
    grammar = reg.export_gbnf_grammar([b64_rec])
    assert '"base64.encode"' in grammar


def test_proc_v2_declared_effect_wins_and_commands_are_never_pure():
    reg = DockuriRegistry()
    reg.register_dockuri_yaml_manifest({"processes": [
        {"uri": "c2004://test-head/inflate/command/start", "effect": "idempotent"},
        {"uri": "c2004://test-head/deflate/command/start"},
        {"uri": "c2004://sensors/pressure/query/read"},
        {"uri": "c2004://sensors/pressure/query/read-all", "effect": "unknown-word"},
        {"uri": "proc://store/item/upsert/v1"},
    ]}, "dockuri.yaml")
    effects = {r.uri: r.effect for r in reg.procedures.values()}
    assert effects == {
        "c2004://test-head/inflate/command/start": "idempotent",
        "c2004://test-head/deflate/command/start": "mutating",
        "c2004://sensors/pressure/query/read": "pure",
        "c2004://sensors/pressure/query/read-all": "pure",
        "proc://store/item/upsert/v1": "mutating",
    }


def test_unified_manifest_mcp_projection_and_effect_normalization():
    from src.dockuri_registry import normalize_effect

    assert normalize_effect("read", target="dockuri") == "idempotent"
    assert normalize_effect("write", target="dockuri") == "mutating"
    assert normalize_effect("idempotent", target="mcp") == "read"
    assert normalize_effect("mutating", target="mcp") == "write"

    reg = DockuriRegistry()
    reg.register_manifest(
        {
            "app": "edialog",
            "version": "0.4.5",
            "transport": {"type": "uds", "socket": "~/.dockuri/run/edialog.sock"},
            "procedures": {
                "pipeline.run": {
                    "uri": "proc://edialog/pipeline/run/v1",
                    "effect": "read",
                    "description": "Run 6-stage pipeline",
                    "inputSchema": {"type": "object"},
                    "outputSchema": {"type": "object"},
                }
            },
        },
        "/dummy/edialog/dockuri.json",
    )
    rec = reg.procedures["pipeline.run"]
    assert rec.uri == "proc://edialog/pipeline/run/v1"
    assert rec.effect == "idempotent"

    mcp_reg = reg.to_mcp_registry(app="edialog", version="0.4.5")
    assert mcp_reg["schema"] == "wellmanifest.mcp/registry/v1"
    assert mcp_reg["operations"][0]["effect"] == "read"
    assert mcp_reg["operations"][0]["uri"] == "proc://edialog/pipeline/run/v1"

