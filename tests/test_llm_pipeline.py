import pytest
from src.dockuri_registry import DockuriRegistry
from src.dockuri_llm_pipeline import (
    build_llm_context,
    resolve_json_pointer,
    resolve_inputs,
    validate_pipeline_dag,
)

def test_resolve_json_pointer():
    data = {
        "content": "hello world",
        "meta": {"author": "tom", "tags": ["fast", "ipc"]},
        "counts": [10, 20, 30]
    }
    assert resolve_json_pointer(data, "/content") == "hello world"
    assert resolve_json_pointer(data, "/meta/author") == "tom"
    assert resolve_json_pointer(data, "/meta/tags/0") == "fast"
    assert resolve_json_pointer(data, "/counts/1") == 20

    with pytest.raises(KeyError):
        resolve_json_pointer(data, "/non_existent")

    with pytest.raises(ValueError):
        resolve_json_pointer(data, "invalid_no_slash")


def test_resolve_inputs():
    previous = {
        "read_step": {"content": "Sample file content", "size": 19},
        "enc_step": {"encoded": "U2FtcGxlIGZpbGU="}
    }
    raw = {
        "text": {"$from": "read_step", "path": "/content"},
        "static_flag": True,
        "nested": {"val": {"$from": "enc_step", "path": "/encoded"}}
    }
    resolved = resolve_inputs(raw, previous)
    assert resolved["text"] == "Sample file content"
    assert resolved["static_flag"] is True
    assert resolved["nested"]["val"] == "U2FtcGxlIGZpbGU="


def test_dag_validation_and_cycle_detection():
    # Valid branching DAG:
    #      step1
    #     /     \
    #  step2a   step2b
    #     \     /
    #      step3
    valid_dag = {
        "name": "diamond_dag",
        "flow": [
            {"id": "step1", "uri": "proc://a/b/c/v1", "input": {}},
            {"id": "step2a", "uri": "proc://a/b/c/v1", "depends_on": ["step1"], "input": {}},
            {"id": "step2b", "uri": "proc://a/b/c/v1", "depends_on": ["step1"], "input": {}},
            {"id": "step3", "uri": "proc://a/b/c/v1", "depends_on": ["step2a", "step2b"], "input": {}},
        ]
    }
    order = validate_pipeline_dag(valid_dag)
    assert order[0] == "step1"
    assert order[-1] == "step3"

    # Cyclic pipeline: step1 -> step2 -> step1
    cyclic_dag = {
        "name": "bad_cyclic",
        "flow": [
            {"id": "step1", "uri": "proc://a/b/c/v1", "depends_on": ["step2"], "input": {}},
            {"id": "step2", "uri": "proc://a/b/c/v1", "depends_on": ["step1"], "input": {}},
        ]
    }
    with pytest.raises(ValueError, match="Cycle detected"):
        validate_pipeline_dag(cyclic_dag)


def test_build_llm_context():
    reg = DockuriRegistry()
    reg.register_manifest({
        "app": "calc",
        "version": "1.0.0",
        "transport": {"type": "uds", "socket": "/tmp/calc.sock"},
        "procedures": {
            "calc.add": {
                "description": "Add two numbers",
                "effect": "pure",
                "schema": {"input": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}}
            }
        }
    }, "/dummy/path")

    prompt = build_llm_context(reg)
    assert "dockuri/workflow-v1" in prompt
    assert "proc://calc/calc/add/v1" in prompt
    assert "RFC 6901" in prompt
    assert "$from" in prompt
