# TubeAIFlow

TubeAIFlow is a local web app for first-stage voiceover and subtitle automation.

Current scope:

- Import and clean a raw transcript
- Split Chinese text into TTS-friendly segments
- Generate segmented voice audio with Qwen3-TTS (default), Chatterbox, or CosyVoice
- Generate timeline JSON from real audio durations
- Generate English SRT subtitle files with DeepSeek translation
- Export a simple project manifest

## Local URLs

- Frontend: http://127.0.0.1:5173
- Backend: http://127.0.0.1:18080

## Windows double-click start

From the project root, double-click:

- `Start_TubeAIFlow.bat` to start the backend and frontend
- `Restart_TubeAIFlow.bat` to stop the running app, then start again

The start script creates the backend virtual environment if needed, installs missing
dependencies, and opens separate terminal windows for the backend and frontend services.
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
- API keys are never returned to the frontend after they are saved.
- Generated project files live under `backend/workspace/projects/{project_id}` by default.
- FFmpeg, ffprobe, Qwen3-TTS, Chatterbox, CosyVoice, translation services, workspace, host, and port are configured on the System Settings page.
- Qwen3-TTS voice cloning works best when the project includes an accurate transcript of the reference audio. Without it, TubeAIFlow automatically uses speaker-embedding-only mode.
- Chatterbox uses a local Multilingual V2/V3 snapshot and does not require a reference transcript; its language code should match the reference clip.
- CosyVoice uses zero-shot cloning and requires an exact transcript of the reference audio. Fun-CosyVoice 3 prompt formatting is handled automatically.
- Host and port changes take effect after restarting the app.
