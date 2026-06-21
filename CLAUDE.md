# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fusion360 CAM cloud AI process recommender — a local-first CNC machining parameter generation system. A Fusion360 Python script detects BRep features from 3D models, sends them to a local FastAPI relay service, which calls a local Ollama LLM (Qwen 2.5) to generate structured cutting parameters (tool, spindle speed, feed rate, depth of cut). All data stays on the machine.

## Commands

```bash
# Start the service (primary entry point)
python cam_cloud_api.py

# Or use the one-click Windows launcher
start_service.bat

# Quick diagnostic — test Ollama connectivity and model inference
python test_api.py

# Install dependencies
pip install -r requirements.txt
```

There is no test suite, build system, or linting configuration. Verification is manual: `GET http://127.0.0.1:8000/health`, Swagger UI at `/docs`, admin UI at `/admin`.

## Architecture

**Three-layer system:**

1. **Client** (`fusion360_cam_ai.py`, ~1340 lines) — Fusion360 built-in Python script. Uses `adsk` namespace for BRep feature detection, builds a CAM Assist-style step-by-step dialog UI. Posts to backend via HTTP.

2. **Backend** (`cam_cloud_api.py`, ~2500 lines) — FastAPI on port 8000. The core hub. Responsibilities: Pydantic input validation, prompt assembly (injecting knowledge base into system prompt), Ollama API call via OpenAI SDK in compatibility mode, output parsing/cleaning, and persistence.

3. **AI** — Ollama running locally on port 11434, default model `qwen2.5:7b-instruct-q4_K_M`, temperature=0.1 for deterministic outputs.

**Key design decisions:**
- No database, no Redis, no Docker — pure Python + FastAPI
- OpenAI SDK compatibility mode to talk to Ollama (`api_key="ollama"` placeholder)
- Thread-safe persistence with `threading.Lock` per data file
- FastMCP/trimesh imports are optional (try/except, degrade gracefully)
- Server binding defaults to `127.0.0.1` (configure with `HOST` env var)

**Data flow for the main `/auto_craft` path:**
1. Fusion360 script scans BRep faces → classifies by surface type (plane/cylinder/cone/torus/NURBS) → estimates dimensions → produces `list[dict]`
2. POST to `/auto_craft` with features + material + machine + part name + dimensions
3. Backend validates → builds system prompt with knowledge base + toolpath strategies + tool material knowledge → calls Ollama (max_tokens=600)
4. Response parsed by `parse_process_plan()` (splits on `---`/`===`/`***`, parses per-line) → fallback to `_fallback_process_plan()` if parsing fails
5. Structured `ProcessStep` list returned to Fusion360 for display

**Persistence files (JSON, auto-created):**
- `personal_craft_library.json` — user's custom process parameters (UUID-keyed)
- `machine_registry.json` — machine definitions (8 seed machines, runtime CRUD)

**Knowledge bases (in-memory dicts in cam_cloud_api.py):**
- `CRAFT_KNOWLEDGE_BASE` — 14 materials × 8 features with baseline cutting params
- `TOOL_MATERIAL_KNOWLEDGE` — 12 tool material types (HSS→PCD)
- `TOOLPATH_STRATEGIES` — 8 strategy categories from open-source CAM projects

## Version alignment

The codebase has version drift between modules. The README says v1.8.0, `cam_cloud_api.py` `__version__` says 1.5.0, `fusion360_cam_ai.py` `__version__` says 1.7.0. When updating versions, update the module-level `__version__` string, the README badges, and CHANGELOG.md together.

## Key files

| File | Role |
|---|---|
| `cam_cloud_api.py` | Main backend — all API endpoints, knowledge bases, prompt building, parsing, persistence |
| `fusion360_cam_ai.py` | Fusion360 client script — feature detection, UI, HTTP calls to backend |
| `static/index.html` | Admin web UI — dashboard, craft library CRUD, machine registry, import/export |
| `test_api.py` | Standalone Ollama connectivity diagnostic (does not require the service to be running) |
| `start_service.bat` | Windows launcher — env vars, dependency auto-install, Ollama pre-check |

## Encoding

All Python files use UTF-8 with Chinese comments and log messages. The `logging.basicConfig` sets `encoding="utf-8"`. Fusion360 script uses `urllib` (not `requests`) because the Fusion360 Python environment has no pip packages.