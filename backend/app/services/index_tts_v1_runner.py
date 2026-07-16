"""Compatibility launcher for the relocated IndexTTS adapter."""

from app.integrations.tts.index_tts_v1_runner import main


if __name__ == "__main__":
    raise SystemExit(main())
