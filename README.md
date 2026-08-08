# TubeAIFlow

TubeAIFlow is a local web app for voiceover, subtitles, locally generated storyboard images, landscape rough cuts, and FFmpeg video synthesis.

Current scope:

- Import and clean a raw transcript
- Split Chinese text into TTS-friendly segments
- Generate segmented voice audio with IndexTTS (Chinese), MOSS-TTS (English), CosyVoice (Cantonese), or Qwen3-TTS (compatibility)
- Generate timeline JSON from real audio durations
- Generate SRT subtitle files from real audio timing
- Generate structured visual scenes for local image generation
- Generate local storyboard images and assign them directly to scenes
- Turn generated images into deterministic FFmpeg motion shots
- Render resumable scene videos and a video-only `visual_track.mp4`
- Mix the visual track with narration and run final-output QA
- Export FCPXML editable timelines and Premiere PRPROJ projects, plus manifests and reports

## Local URLs

- Frontend: http://127.0.0.1:5173
- Backend: http://127.0.0.1:18080

## Windows double-click start

From the project root, double-click:

- `Start_TubeAIFlow.bat` to start the backend and frontend
- `Restart_TubeAIFlow.bat` to stop the running app, then start again
- `Start_TTS_WebUI.bat index_tts|moss_tts|cosyvoice` to run one engine's standalone WebUI

The start script uses the existing backend virtual environment without requiring a
system-wide Python on `PATH`. If the environment does not exist, Python 3.12 is required
once to create it. The launcher installs missing dependencies, keeps one visible backend
command window for runtime logs, and starts the frontend without another persistent window.
It records both process IDs and writes frontend output to `backend/workspace/logs`. Restart
uses the recorded process trees plus listener ports, so the previous instance is stopped
before new processes are created.
Backend runtime configuration is loaded from the local SQLite system settings table.

## Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.run
```

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

## Checks

```powershell
cd backend
pip install -r requirements-dev.txt
pytest -q
ruff check app tests

cd ..\frontend
npm run build
```

## Notes

- Runtime configuration is managed on the **System Settings** page and stored locally in SQLite.
- IndexTTS uses `D:\index-tts\python310`; MOSS-TTS and CosyVoice use their own isolated
  environments. Qwen3-TTS remains compatible with the existing backend environment.
- API keys are never returned to the frontend after they are saved.
- Generated project files live under `backend/workspace/projects/{project_id}` by default.
- FFmpeg, ffprobe, all four TTS engines, DeepSeek, workspace, host, and port are configured on the System Settings page.
- PRPROJ export retains the Final Cut Pro X FCPXML, converts the timeline to Premiere-compatible Final Cut Pro 7 XML, and then uses Adobe Premiere Pro's `openFCPXML()` API to create the native project. Configure the Premiere executable under **System Settings → Basic & Storage** when Windows App Paths and standard installation folders do not detect it automatically. FCPXML and Premiere XML export do not require Premiere.
- AI image assignments support stable automatic motion presets. Network stock search, semantic vector retrieval, candidate review, and manual material approval are not part of the video workflow.
- Every intermediate scene and `renders/visual_track.mp4` is validated with ffprobe and must contain exactly one H.264 video stream, 30 FPS CFR, yuv420p, and no audio stream under the default render profile.
- Project render settings may be stored in `config.render.video` and `config.render.policy`; missing values use the validated 1920×1080, 30 FPS defaults.
- On Windows 10/11 64-bit, the System Settings page can automatically download the latest FFmpeg release essentials build, verify its published SHA-256 checksum, install only `ffmpeg.exe` and `ffprobe.exe` under `workspace/tools/ffmpeg`, and save both absolute paths to SQLite. The downloaded tools are local runtime files and are not committed to Git.
- The automatic FFmpeg installer uses the Windows builds linked by the FFmpeg project and currently downloads the GPLv3 Gyan essentials build from `https://www.gyan.dev/ffmpeg/builds/`.
- Qwen3-TTS voice cloning works best when the project includes an accurate transcript of the reference audio. Without it, TubeAIFlow automatically uses speaker-embedding-only mode.
- CosyVoice uses zero-shot cloning and requires an exact transcript of the reference audio. Fun-CosyVoice 3 prompt formatting is handled automatically.
- Host and port changes take effect after restarting the app.
