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
