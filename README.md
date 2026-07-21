# TubeAIFlow

TubeAIFlow is a local web app for voiceover, subtitles, AI storyboards, local media retrieval, AI-generated storyboard images, and FFmpeg video synthesis.

Current scope:

- Import and clean a raw transcript
- Split Chinese text into TTS-friendly segments
- Generate segmented voice audio with Qwen3-TTS (default) or CosyVoice
- Generate timeline JSON from real audio durations
- Generate SRT subtitle files from real audio timing
- Generate structured visual scenes and storyboard queries
- Generate and review local AI storyboard image candidates
- Turn approved images into deterministic FFmpeg motion shots
- Render resumable scene videos and a video-only `visual_track.mp4`
- Mix the visual track with narration and run project-level QA
- Export project manifests, render reports, and quality reports

## Local URLs

- Frontend: http://127.0.0.1:5173
- Backend: http://127.0.0.1:18080

## Windows double-click start

From the project root, double-click:

- `Start_TubeAIFlow.bat` to start the backend and frontend
- `Restart_TubeAIFlow.bat` to stop the running app, then start again

The start script uses the existing backend virtual environment without requiring a
system-wide Python on `PATH`. If the environment does not exist, Python 3.12 is required
once to create it. The launcher installs missing dependencies and opens separate terminal
windows for the backend and frontend services.
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

## Notes

- Runtime configuration is managed on the **System Settings** page and stored locally in SQLite.
- Qwen3-TTS inference shares `backend/.venv`; CosyVoice keeps an isolated Python
  environment because its Torch, CUDA, and Python requirements may conflict.
- API keys are never returned to the frontend after they are saved.
- Generated project files live under `backend/workspace/projects/{project_id}` by default.
- FFmpeg, ffprobe, Qwen3-TTS, CosyVoice, DeepSeek, workspace, host, and port are configured on the System Settings page.
- AI image assignments support stable automatic motion or explicit zoom, pan, portrait, environment, breathing, and static presets. Updating one assignment only invalidates the affected scene render cache.
- Every intermediate scene and `renders/visual_track.mp4` is validated with ffprobe and must contain exactly one H.264 video stream, 30 FPS CFR, yuv420p, and no audio stream under the default render profile.
- Project render settings may be stored in `config.render.video` and `config.render.policy`; missing values use the validated 1920×1080, 30 FPS defaults.
- On Windows 10/11 64-bit, the System Settings page can automatically download the latest FFmpeg release essentials build, verify its published SHA-256 checksum, install only `ffmpeg.exe` and `ffprobe.exe` under `workspace/tools/ffmpeg`, and save both absolute paths to SQLite. The downloaded tools are local runtime files and are not committed to Git.
- The automatic FFmpeg installer uses the Windows builds linked by the FFmpeg project and currently downloads the GPLv3 Gyan essentials build from `https://www.gyan.dev/ffmpeg/builds/`.
- Qwen3-TTS voice cloning works best when the project includes an accurate transcript of the reference audio. Without it, TubeAIFlow automatically uses speaker-embedding-only mode.
- CosyVoice uses zero-shot cloning and requires an exact transcript of the reference audio. Fun-CosyVoice 3 prompt formatting is handled automatically.
- Host and port changes take effect after restarting the app.
