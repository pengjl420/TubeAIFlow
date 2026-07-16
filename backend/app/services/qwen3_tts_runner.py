"""Compatibility launcher for the relocated Qwen3-TTS adapter."""

from app.integrations.tts.qwen3_tts_runner import main


if __name__ == "__main__":
    raise SystemExit(main())
