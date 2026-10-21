"""Regression: dockuri_search_procedures also searches the Dockuri process catalog, without padding."""

from __future__ import annotations

from pathlib import Path

import src.dockuri_mcp as mcp

CATALOG = {"status": "ok", "total_registry_count": 51, "shortlist": [
    {"uri": "proc://ast-scan/complexity/horizontal", "description": "Przeskanuj złożoność kodu Python", "effect": "read"},
    {"uri": "proc://willgit/worktree/inspect", "description": "Read worktrees and leases", "effect": "read"},
    {"uri": "proc://system/queue/heal/v1", "description": "Queue audit", "effect": "write"},
]}


def test_catalog_matches_are_added_with_effect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mcp, "uri", lambda address, payload: CATALOG)
    res = mcp.TOOL_DISPATCHERS["dockuri_search_procedures"]({"query": "złożoność kodu", "project": str(tmp_path), "limit": 5})
    assert [c["uri"] for c in res["candidates"]] == ["proc://ast-scan/complexity/horizontal"]
    assert res["candidates"][0]["effect"] == "read" and res["candidates"][0]["source"] == "dockuri_catalog"
    assert res["total_indexed"] >= 51


def test_unrelated_catalog_entries_are_not_padded(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mcp, "uri", lambda address, payload: CATALOG)
    res = mcp.TOOL_DISPATCHERS["dockuri_search_procedures"]({"query": "xyzzy kwakwa", "project": str(tmp_path)})
    assert res["candidates"] == []


def test_catalog_failure_keeps_local_results(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mcp, "uri", lambda address, payload: {"status": "error", "error": {"code": "UNAVAILABLE"}})
    res = mcp.TOOL_DISPATCHERS["dockuri_search_procedures"]({"query": "worktree", "project": str(tmp_path)})
    assert all(c.get("source") != "dockuri_catalog" for c in res["candidates"])


def test_state_changing_matches_are_listed_last(tmp_path: Path, monkeypatch) -> None:
    catalog = {"status": "ok", "total_registry_count": 2, "shortlist": [
        {"uri": "proc://system/worktree/promote/v1", "description": "Promote worktrees", "effect": "write"},
        {"uri": "proc://willgit/worktree/inspect", "description": "Read worktrees", "effect": "read"}]}
    monkeypatch.setattr(mcp, "uri", lambda address, payload: catalog)
    res = mcp.TOOL_DISPATCHERS["dockuri_search_procedures"]({"query": "worktrees", "project": str(tmp_path), "limit": 5})
    effects = [c.get("effect") for c in res["candidates"]]
    assert effects.index("read") < effects.index("write")
