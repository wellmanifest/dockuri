# Changelog

All notable changes to the Wellmanifest Dockuri standard will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- DOCK-UDS-001: sockets are no longer looked up in `/tmp`; candidates must be sockets owned by the user or root with no access for others; registry and reference workers default to `DOCKURI_RUN_DIR` / `~/.dockuri/run`.
- DOCK-UDS-001: `dockuri-fast` and the NL pilot read the procedure cache from `DOCKURI_CACHE_DIR` / `$XDG_CACHE_HOME/dockuri` instead of `/tmp/dockuri_fast_cache.json`; the pilots and the Rust reference worker no longer use `/tmp` sockets or `/home/tom` paths (`DOCKURI_SCAN_ROOT`, `DOCKURI_PROJECTS_ROOT`).
- `register_dockuri_yaml_manifest` uses the declared proc-v2 `effect` (`pure | idempotent | mutating`); the URI-word guess is only a fallback and never marks a `/command/` process `pure` (hardware commands such as `c2004://test-head/inflate/command/start` were registered as side-effect free).
- Conformance no longer registers an echo stub that permanently replaced the matched URI process; dispatch without a safe probe is `INCONCLUSIVE`.
- `dry_run` of an unregistered URI returns `UNKNOWN_URI` instead of `status=ok, dispatched=true`.
- `{"ok": false}` results are normalized to `status=error`; the `uri` CLI exits non-zero for them.
- `dockuri_execute_sentence` reports the process status and refuses to fabricate `proc://<dir>/run/instruction/v1`.
- Mutating sprint/worktree calls require an explicit project; targeted `manage_process` actions require `target_uri`.
- Project readiness no longer counts built-in system services as project procedures (`builtin-only`).
- Manifest processes run with the manifest directory as cwd, the payload on stdin, and a timeout; failures are reported instead of swallowed.

### Changed
- `DOCK-DISP-001` and `DOCK-MCP-001` state the truthful-result, dry-run and mutation-scope rules above.

## [0.1.0] - 2026-10-05

### Added
- Initial specification `spec/DOCKURI_STANDARD.md` with rules `DOCK-MAN-001` through `DOCK-PIP-001`.
- JSON schema `schemas/dockuri-manifest.schema.json`.
- Conformance and latency validation tool `src/dockuri_check.py`.
- Reference client and pipeline chaining engine `src/dockuri_client.py`.
- Polyglot reference worker daemons for Python, Node.js, PHP, and Rust.
- Comprehensive test suite for conformance, fast IPC latency (< 2.0 ms), and chained pipelines.
