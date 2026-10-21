"""Regression tests: MCP bridge and client never report success for work that did not happen."""

from __future__ import annotations

from pathlib import Path

from src.dockuri_check import inspect_project_dockuri_readiness
from src.dockuri_client import normalize_result, uri
from src.dockuri_mcp import TOOL_DISPATCHERS


def test_dry_run_of_unknown_uri_is_error(tmp_path: Path) -> None:
    res = uri("proc://nonexistent/thing/v1", {"dry_run": True, "project": str(tmp_path)})
    assert res["status"] == "error"
    assert res["error"]["code"] == "UNKNOWN_URI"
    assert res["dispatched"] is False


def test_ok_false_envelope_gets_error_status() -> None:
    assert normalize_result({"ok": False, "error": {"code": "INVALID_URI"}})["status"] == "error"
    assert normalize_result({"status": "ok", "ok": False})["status"] == "ok"


def test_execute_sentence_without_match_does_not_dispatch(tmp_path: Path) -> None:
    res = TOOL_DISPATCHERS["dockuri_execute_sentence"]({"sentence": "xyzzy kwakwa", "project": str(tmp_path), "dry_run": True})
    assert res["status"] == "error"
    assert res["error"]["code"] == "NO_MATCHING_PROCEDURE"
    assert "execution_result" not in res


def test_mutating_call_without_project_is_refused() -> None:
    res = TOOL_DISPATCHERS["dockuri_call_uri"]({"uri": "proc://system/worktree/promote/v1", "payload": {"action": "heal"}})
    assert res["status"] == "error"
    assert res["error"]["code"] == "PROJECT_REQUIRED"


def test_targeted_manage_action_requires_target_uri() -> None:
    res = TOOL_DISPATCHERS["dockuri_manage_process"]({"action": "relocate", "new_uri": "proc://x/y/v1"})
    assert res["status"] == "error"
    assert res["error"]["code"] == "TARGET_URI_REQUIRED"


def test_builtin_services_alone_do_not_make_project_ready(tmp_path: Path) -> None:
    (tmp_path / ".planfile").mkdir()
    rd = inspect_project_dockuri_readiness(tmp_path)
    assert rd["status"] == "WARN"
    assert rd["descriptor_type"] == "builtin-only"
    assert rd["project_procedures_count"] == 0
    assert rd["builtin_procedures_count"] > 0
