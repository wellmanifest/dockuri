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


def test_project_readiness_and_sentence_dispatch(tmp_path):
    from src.dockuri_check import (
        check_sentence_dispatch,
        check_uri_standard_conformance,
        inspect_project_dockuri_readiness,
    )

    proj_dir = tmp_path / "sample_service"
    proj_dir.mkdir()
    proc_yaml = proj_dir / "dockuri.yaml"
    proc_yaml.write_text(
        "version: dockuri/proc-v2\n"
        "processes:\n"
        "  proc://sample/health/check/v1:\n"
        "    run: ['python3', '-c', 'print(\"ok\")']\n"
        "    description: 'Verify system health and database connectivity'\n",
        encoding="utf-8",
    )

    readiness = inspect_project_dockuri_readiness(proj_dir)
    assert readiness["status"] == "PASS"
    assert readiness["descriptor_type"] == "proc-v2"
    assert readiness["runnable_procedures_count"] == 1
    assert "proc://sample/health/check/v1" in readiness["procedures"]

    dispatch = check_sentence_dispatch(proj_dir, "sprawdź stan bazy i health check", max_latency_ms=20.0)
    assert dispatch["status"] == "INCONCLUSIVE"
    assert dispatch["matched_uri"] == "proc://sample/health/check/v1"
    assert dispatch["dispatch_attempted"] is False
    assert dispatch["route_lookup_ms"] <= 20.0

    report = check_uri_standard_conformance(
        project_path=proj_dir,
        test_sentence="sprawdź stan bazy i health check",
    )
    assert report["status"] == "INCONCLUSIVE"
    assert "DOCK-DISP-001" not in report["rules_enforced"]
    assert "DOCK-DISP-001" in report["rules_unverified"]
    assert report["sentence_dispatch"]["matched_uri"] == "proc://sample/health/check/v1"
    assert report["sentence_dispatch"]["dispatch_attempted"] is False


def test_dispatch_probe_must_return_uri_bound_execution_receipt(tmp_path):
    from src.dockuri_check import check_sentence_dispatch

    proj_dir = tmp_path / "sample_service"
    proj_dir.mkdir()
    (proj_dir / "dockuri.yaml").write_text(
        "version: dockuri/proc-v2\n"
        "processes:\n"
        "  proc://sample/health/check/v1:\n"
        "    run: ['true']\n"
        "    description: 'health check'\n",
        encoding="utf-8",
    )
    seen = {}

    def probe(uri, payload):
        seen["uri"] = uri
        seen["payload"] = payload
        return {"status": "ok", "execution_receipt": {"status": "completed", "uri": uri, "executed": True}}

    result = check_sentence_dispatch(proj_dir, "health check", dispatch_probe=probe)
    assert result["status"] == "PASS"
    assert result["dispatch_attempted"] is True
    assert seen["uri"] == "proc://sample/health/check/v1"


def test_conformance_fails_when_no_route_is_registered(tmp_path):
    from src.dockuri_check import check_sentence_dispatch

    result = check_sentence_dispatch(tmp_path, "unknown request")
    assert result["status"] == "FAIL"
    assert result["matched_uri"] is None
    assert result["dispatch_attempted"] is False

