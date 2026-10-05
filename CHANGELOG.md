# Changelog

All notable changes to the Wellmanifest Dockuri standard will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-05

### Added
- Initial specification `spec/DOCKURI_STANDARD.md` with rules `DOCK-MAN-001` through `DOCK-PIP-001`.
- JSON schema `schemas/dockuri-manifest.schema.json`.
- Conformance and latency validation tool `src/dockuri_check.py`.
- Reference client and pipeline chaining engine `src/dockuri_client.py`.
- Polyglot reference worker daemons for Python, Node.js, PHP, and Rust.
- Comprehensive test suite for conformance, fast IPC latency (< 2.0 ms), and chained pipelines.
