<p align="center">
  <img src="frontend/public/brand/tubeaifolw-logo.png" alt="TubeAiFolw Logo" width="128" />
</p>

<h1 align="center">TubeAiFolw</h1>

<p align="center">
  A local-first AI production workflow for YouTube, faceless, and long-form video creators
</p>

<p align="center"><a href="README.md">简体中文</a> · <strong>English</strong></p>

> [!IMPORTANT]
> TubeAiFolw is under active development. It currently runs as a Vue 3 web UI backed by a local FastAPI engine. A desktop shell and production installer are not available yet.

## Overview

TubeAiFolw is not another one-click AI video generator. It is a **local-first production workflow for professional YouTube, faceless, and long-form video creators**.

It organizes scripting, segmented TTS, subtitle alignment, semantic storyboarding, local asset matching, local AI illustration, delivery QC, and editable project export into a recoverable, human-in-the-loop workflow. The target is reliable production of 20–60 minute videos, not a short demo clip.

Design principles:

- **Local first:** keep heavy computation, project data, media, and logs on the user's machine.
- **BYOK:** users provide credentials for optional third-party services.
- **Replaceable providers:** models and vendors integrate through registries and adapters.
- **Scene first:** a Scene is the central unit for text, audio, subtitles, visuals, and quality state.
- **Recoverable:** long-running tasks support persistence, pause, resume, cancel, retry, and checkpoints.
- **Human in the loop:** users can edit and lock scenes, replace assets, and regenerate local results.
- **Editable delivery:** the primary delivery is a real `.prproj` plus WAV, SRT, and linked assets—not an opaque final MP4.

## Current capabilities

```text
Create project
  ↓
Import, normalize, and segment a TXT or Markdown script
  ↓
Generate segmented local TTS and merge the final WAV
  ↓
Align subtitles and generate SRT
  ↓
Build a semantic storyboard / visual scenes
  ↓
Match local media or generate local AI images
  ↓
Preview scenes and run delivery QC
  ↓
Use Adobe Premiere Pro to convert and export a real PRPROJ
```

Implemented features include:

- Project CRUD, custom output directories, atomic writes, artifact manifests, and SQLite migrations.
- Persistent queues with CPU, GPU, API, FFmpeg, and network resource limits.
- TXT / Markdown normalization, line-based segmentation, and AI semantic segmentation.
- Local IndexTTS, MOSS-TTS, CosyVoice, and Qwen3-TTS generation.
- Voice profiles, reference audio, per-segment regeneration, retry, pause, and recovery.
- Faster-Whisper alignment with a proportional-timing fallback requiring manual review.
- Structured storyboards through Local Qwen or DeepSeek BYOK.
- Scene editing, revision restore, and text/audio/visual locks.
- Local media scanning, SHA-256 deduplication, candidate ranking, and manual selection.
- Local SDXL plus an advanced BGE-M3, Qwen, FLUX/ComfyUI, and Qwen3-VL pipeline.
- An `anime_full_coverage` strategy with stable visual beats and multiple shots per Scene.
- Scene previews, technical validation, and delivery-quality reports.
- FCPXML, Premiere XML, and real PRPROJ project export.
- Batch creation and execution for up to 100 TXT / Markdown scripts.
- Compatibility tools for voice generation, local video merging, and digital humans.
- Windows DPAPI secret storage, sensitive-field filtering, diagnostics, and cleanup.

## Not implemented or not fully validated

- Tauri/Electron shell, Windows installer, auto updater, and code signing.
- Accounts, login, licensing, device activation, payment, and version services.
- Per-project `project.db`; the global SQLite database is still authoritative.
- Cloud TTS, cloud image, AI video, and stock-media providers.
- Complete keyframe extraction, shot detection, AI captions, and unified embedding search.
- Channel profiles, style bibles, workflow presets, and complete cost accounting.
- A 20–60 minute golden test using real local models, GPU, Premiere Pro, and the target Jianying/CapCut build.
- macOS, mobile, cloud project sync, and multi-user collaboration.

TubeAiFolw is **not** a general-purpose NLE. It does not provide a draggable multitrack timeline, keyframe editor, or a replacement for Premiere, DaVinci Resolve, or CapCut.

## Architecture

```text
┌─────────────────────────────────────┐
│ Vue 3 + TypeScript + Vite Web UI    │
└──────────────────┬──────────────────┘
                   │ localhost HTTP
┌──────────────────▼──────────────────┐
│ FastAPI + Python Local Engine       │
│ Workflow / Task Queue / Providers   │
└──────────┬──────────────┬───────────┘
           │              │
     SQLite + Files   FFmpeg + Local AI
                          │
                    Optional BYOK APIs
```

The current development shell is browser-based. Workflow orchestration and heavy computation stay in the local engine.

## Requirements

Base environment:

- 64-bit Windows 10 or Windows 11, the current primary platform.
- Python 3.12 to create the backend virtual environment.
- Node.js 20 LTS or newer, with npm.
- Sufficient storage for models, audio, images, and project media.

Optional production components:

- FFmpeg and ffprobe; System Settings can download and verify a Windows build.
- An NVIDIA CUDA GPU for local large models, image generation, and selected TTS engines.
- Adobe Premiere Pro only when generating a real `.prproj`. TubeAiFolw never renames XML to pretend it is PRPROJ.
- Relevant local TTS, LLM, embedding, image, or vision models.

## Quick start on Windows

Double-click `Start_TubeAIFlow.bat` in the repository root. The first run creates `backend/.venv`, installs dependencies, starts both services, and opens the browser. Later runs skip unchanged installation steps.

```powershell
# Start
.\Start_TubeAIFlow.bat

# Restart / stop
.\Start_TubeAIFlow.bat --restart
.\Start_TubeAIFlow.bat --stop

# Read-only check / repair dependencies
.\Start_TubeAIFlow.bat --check
.\Start_TubeAIFlow.bat --repair
```

`Restart_TubeAIFlow.bat` is also available. Shared launcher logic lives in `scripts/Launch_TubeAiFolw.ps1`.

Local URLs:

- Frontend: <http://127.0.0.1:5173>
- Backend health: <http://127.0.0.1:18080/api/health>
- FastAPI documentation: <http://127.0.0.1:18080/docs>

If the default backend port is unavailable, the launcher selects an open port and configures the frontend.

Create a desktop shortcut:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/Create_DesktopShortcut.ps1
```

Run the command again after moving the repository.

## Manual development setup

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m app.run
```

Dependency groups:

- `requirements-core.txt`: engine and cloud-provider fundamentals.
- `requirements-tts-asr.txt`: TTS and ASR integrations.
- `requirements-local-ai-cu128.txt`: local CUDA AI dependencies.
- `requirements.txt`: complete Windows local-AI environment.
- `requirements-dev.txt`: tests and static analysis.

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

## Local models and advanced visual pipeline

Models are separated by responsibility and are not committed to Git:

```text
models/
  llm/qwen3-8b-q4_k_m/
  embedding/bge-m3-onnx/
  image_generation/flux2-klein-4b-fp8/
  vision/qwen3-vl-4b-instruct-bf16/
```

```powershell
# Download pinned revisions and install local services
backend\.venv\Scripts\python.exe scripts\download_visual_models.py
backend\.venv\Scripts\python.exe scripts\install_llama_cpp.py
backend\.venv\Scripts\python.exe scripts\install_comfyui.py

# Start one service as needed
backend\.venv\Scripts\python.exe scripts\start_visual_model_service.py semantic
backend\.venv\Scripts\python.exe scripts\start_visual_model_service.py image
```

The default RTX 5060 Ti profile permits one large GPU workload at a time. Run semantic analysis, image generation, and Qwen3-VL QC serially. See `config/production_5060ti.yaml`.

Run a deterministic check without loading models:

```powershell
python run.py `
  --project tests/fixtures/demo `
  --config config/production_5060ti.yaml `
  --dry-run
```

Use `--stage ingest|semantic|plan|generate|qc|timeline|render` for one stage, `--resume` to reuse SHA-256-verified artifacts, or `--force` to rebuild.

## Project data and outputs

```text
project-name/
  project.json
  input/
  audio/
  subtitles/
  scenes/
  assets/
  cache/
  renders/
  logs/
  reports/
  exports/
```

The default development workspace is `backend/workspace`. Workspaces, models, media, and secrets must not be committed.

## Tests and delivery verification

```powershell
cd backend
python -m pip install -r requirements-dev.txt
pytest -q
ruff check app tests

cd ..\frontend
npm test
npm run build
```

Verify a completed long-form delivery:

```powershell
backend\.venv\Scripts\python.exe scripts\verify_long_form_delivery.py `
  --qa-report "<project-directory>\reports\qa.json" `
  --export-report "<project-directory>\reports\prproj_export_report.json"
```

Automated verification does not replace opening the project in Premiere Pro and the target Jianying/CapCut version to inspect audio, subtitles, linked media, and relinking behavior.

## Security and privacy

- Project content and heavy computation remain local by default.
- Secrets are protected with Windows DPAPI; SQLite stores credential IDs only.
- Saved API keys are never returned to the frontend.
- Task snapshots filter API keys, tokens, secrets, and passwords.
- Data sent through a BYOK provider is governed by that provider's terms.
- Never commit `.env` files, databases, workspaces, model weights, logs, or generated media.

## Contributing

Issues, documentation improvements, bug fixes, and tested pull requests are welcome. Before submitting:

1. Keep the product name exactly **TubeAiFolw**.
2. Keep business logic, AI inference, and FFmpeg command construction out of UI components.
3. Add providers through registry and adapter interfaces.
4. Add or update tests for behavioral changes.
5. Run backend tests, Ruff, frontend tests, and the production build.
6. Do not commit models, credentials, user media, or runtime artifacts.

See `AGENTS.md` for architecture and maintenance constraints, and `docs/` for additional documentation.

## License

This repository does not currently contain a `LICENSE` file. Until a license is formally added, default copyright law applies; public source visibility does not grant permission to copy, modify, or redistribute the code.

Please wait for an explicit license release before redistributing or commercially integrating TubeAiFolw. The recommended release direction is **AGPL-3.0-only plus a separate commercial license**, but that model does not take effect until the corresponding legal files are added to the repository root.
