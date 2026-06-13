# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] — 2026-06-13

### Added
- Initial release: Fusion360 CAM + Tongyi Qianwen cloud AI process recommendation system
- FastAPI relay service (`cam_cloud_api.py`) on port 8000
  - POST `/get_craft` endpoint for AI-powered cutting parameter generation
  - GET `/health` health check with API connectivity verification
  - GET `/knowledge_base` and `/knowledge_base/lookup` offline knowledge base queries
- Built-in CNC process knowledge base covering:
  - 6 machining features: face milling, pocket, keyway, drilling, tapping, surface finishing
  - 4 materials: 6061 aluminum, 45# steel, 304 stainless steel, H62 brass
  - All with safe, shop-floor-validated cutting parameters
- Fusion360 Python script (`fusion360_cam_ai.py`) with interactive dialog UI
  - Feature / material / machine dropdown selection
  - One-click AI parameter query
  - Offline knowledge base reference button (no API cost)
  - Color-coded result display
- Windows one-click startup script (`start_service.bat`)
- Windows auto-start VBScript (`auto_start.vbs`)
- Complete deployment documentation (CN)
- Fixed model: `qwen2.5-14b-instruct` via Alibaba Cloud DashScope SDK
- Fixed output format: `Tool | SpindleSpeed S | FeedRate F | DepthOfCut ap`
- Low temperature (0.1) for stable, low-hallucination output

### Technical Stack
- **Backend:** Python 3.10+, FastAPI 0.115, Uvicorn 0.30, DashScope SDK 1.20
- **AI Model:** Alibaba Cloud Tongyi Qianwen (`qwen2.5-14b-instruct`)
- **Client:** Autodesk Fusion360 Python API (`adsk` namespace)
- **Platform:** Windows 11 (primary target)
