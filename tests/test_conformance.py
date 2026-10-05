import json
import pytest
from pathlib import Path
from src.dockuri_check import validate_manifest

def test_manifest_valid(tmp_path):
    manifest = {
        "$schema": "https://wellmanifest.org/schemas/dockuri-v1.json",
        "app": "demo-app",
        "version": "1.0.0",
        "transport": {
            "type": "uds",
            "socket": "/tmp/demo.sock"
        },
        "procedures": {
            "demo.add": {
                "effect": "pure",
                "timeout_ms": 100,
                "schema": {
                    "input": {"type": "object"},
                    "output": {"type": "object"}
                }
            }
        }
    }
    m_file = tmp_path / "dockuri.json"
    m_file.write_text(json.dumps(manifest), encoding="utf-8")

    loaded = validate_manifest(m_file)
    assert loaded["app"] == "demo-app"
    assert "demo.add" in loaded["procedures"]


def test_manifest_missing_field(tmp_path):
    manifest = {
        "app": "bad-app"
    }
    m_file = tmp_path / "dockuri.json"
    m_file.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="Missing required field"):
        validate_manifest(m_file)
