"""Tests for DOCK-URI-001 universal uri() and uri_jsonl() interface in wellmanifest/dockuri."""

from __future__ import annotations

import json
from pathlib import Path

from src.dockuri_client import (
    parse_jsonl_payload,
    register_uri_process,
    render_uri_call_snippet,
    uri,
    uri_jsonl,
    uri_main,
)


def test_register_and_call_uri_single_and_query():
    register_uri_process(
        "proc://test/echo/v1",
        lambda params: {"status": "ok", "echo": params},
    )
    res = uri("proc://test/echo/v1?dry_run=true&limit=5", {"project": "planfile"})
    assert isinstance(res, dict)
    assert res["status"] == "ok"
    assert res["echo"]["dry_run"] is True
    assert res["echo"]["limit"] == 5
    assert res["echo"]["project"] == "planfile"


def test_uri_jsonl_batch_and_file(tmp_path: Path):
    register_uri_process(
        "proc://test/batch/v1",
        lambda params: {"status": "ok", "id": params.get("id"), "tag": params.get("tag")},
    )
    jsonl_str = '{"id": 1}\n{"id": 2}\n'
    batch_res = uri("proc://test/batch/v1?tag=std", jsonl_str)
    assert isinstance(batch_res, list)
    assert len(batch_res) == 2
    assert batch_res[0] == {"status": "ok", "id": 1, "tag": "std"}
    assert batch_res[1] == {"status": "ok", "id": 2, "tag": "std"}

    jsonl_file = tmp_path / "inputs.jsonl"
    jsonl_file.write_text('{"id": 10}\n{"id": 20}\n', encoding="utf-8")
    file_res = uri("proc://test/batch/v1?tag=file", f"@{jsonl_file}")
    assert isinstance(file_res, list)
    assert [r["id"] for r in file_res] == [10, 20]

    stream_res = uri_jsonl("proc://test/batch/v1?tag=stream", ['{"id": 100}', {"id": 200}])
    assert len(stream_res) == 2
    assert [r["id"] for r in stream_res] == [100, 200]


def test_render_polyglot_snippets():
    target = "proc://system/sprint/deduplicate/v1"
    for lang, marker in [
        ("python", "from dockuri import uri"),
        ("bash", "exec uri"),
        ("js", "execFileSync('uri'"),
        ("rust", 'Command::new("uri")'),
        ("go", 'exec.Command("uri"'),
        ("php", "function uri("),
    ]:
        snippet = render_uri_call_snippet(target, {"dry_run": True}, lang=lang)
        assert marker in snippet
        assert target in snippet


def test_uri_main_cli(capsys):
    register_uri_process(
        "proc://test/cli/v1",
        lambda params: {"status": "ok", "value": params.get("x", 0) * 2},
    )
    rc = uri_main(["proc://test/cli/v1", '{"x": 21}'])
    assert rc == 0
    out = json.loads(capsys.readouterr().out.strip())
    assert out == {"status": "ok", "value": 42}


def test_generic_prompts_and_uri_standard_conformance(tmp_path: Path):
    from src.dockuri_check import check_uri_standard_conformance, validate_proc_v2_manifest
    from src.dockuri_llm_pipeline import GENERIC_URI_PROMPTS, build_generic_uri_prompt

    for pid in GENERIC_URI_PROMPTS:
        pl_text = build_generic_uri_prompt(pid, lang="pl", project_root="/repo/demo")
        en_text = build_generic_uri_prompt(pid, lang="en", project_root="/repo/demo")
        assert "uri" in pl_text
        assert "uri" in en_text

    proc_manifest = tmp_path / "dockuri.yaml"
    proc_manifest.write_text(
        "version: 'dockuri/proc-v2'\n"
        "processes:\n"
        "  - uri: 'proc://system/sprint/deduplicate/v2'\n"
        "    aliases:\n"
        "      - 'proc://system/sprint/deduplicate/v1'\n"
        "    run: ['python3', '-m', 'willops']\n",
        encoding="utf-8",
    )
    v2_report = validate_proc_v2_manifest(proc_manifest)
    assert v2_report["status"] == "PASS"
    assert v2_report["process_count"] == 1
    assert v2_report["alias_count"] == 1

    std_report = check_uri_standard_conformance(
        proc_manifest,
        project_path=tmp_path,
        test_sentence="deduplicate sprint",
    )
    assert std_report["status"] == "INCONCLUSIVE"
    assert "DOCK-PRM-001" in std_report["rules_enforced"]
    assert "DOCK-DISP-001" in std_report["rules_unverified"]



def test_is_failure_truthful_envelope():
    from src.dockuri_client import is_failure
    assert is_failure({"ok": False}) is True
    assert is_failure({"status": "error"}) is True
    assert is_failure({"ok": True, "status": "ok"}) is False
    assert is_failure({"status": "ok"}) is False


def test_resolve_uds_socket_hierarchy(tmp_path: Path, monkeypatch):
    from src.dockuri_client import _resolve_uds_socket
    dummy_sock = tmp_path / "custom.sock"
    dummy_sock.touch()

    # 1. Explicit
    assert _resolve_uds_socket("custom", str(dummy_sock)) == str(dummy_sock)

    # 2. DOCKURI_SOCKET
    monkeypatch.setenv("DOCKURI_SOCKET", str(dummy_sock))
    assert _resolve_uds_socket("custom") == str(dummy_sock)

    # 3. DOCKURI_RUN_DIR
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    app_sock = run_dir / "my_app.sock"
    app_sock.touch()
    monkeypatch.delenv("DOCKURI_SOCKET")
    monkeypatch.setenv("DOCKURI_RUN_DIR", str(run_dir))
    assert _resolve_uds_socket("my_app") == str(app_sock)
