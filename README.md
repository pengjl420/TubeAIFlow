# TubeAIFlow

TubeAIFlow is a local web app for first-stage voiceover and subtitle automation.

Current scope:

- Import and clean a raw transcript
- Split Chinese text into TTS-friendly segments
- Keep index-tts calls centralized in the backend TTS service
- Generate timeline JSON from real audio durations
- Generate English SRT subtitle files with DeepSeek translation
- Export a simple project manifest

## Local URLs

- Frontend: http://127.0.0.1:5173
- Backend: http://127.0.0.1:18080

## Windows double-click start

From the project root, double-click:

- `Start_TubeAIFlow.bat` to start the backend and frontend
- `Restart_TubeAIFlow.bat` to release ports `18080` and `5173`, then start again

The start script creates `backend\.env` from `backend\.env.example` if needed,
creates the backend virtual environment if needed, installs missing dependencies,
and opens separate terminal windows for the backend and frontend services.

## Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 18080 --reload
```

## Frontend

```powershell
cd frontend
npm install
npm run dev
```

## Notes

- `.env` is intentionally ignored.
- Generated project files live under `backend/workspace/projects/{project_id}` by default.
- FFmpeg and ffprobe must be available on PATH, or configured in `.env`.
- The default index-tts command is `index-tts`; adjust `INDEX_TTS_COMMAND` in `.env` if your local CLI differs.
- English subtitles use DeepSeek by default. Set `DEEPSEEK_API_KEY` in `backend\.env`.
