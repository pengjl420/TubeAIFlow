"""Compatibility alias for the narration TTS service."""

import sys

from app.services.narration import tts_service as _implementation

sys.modules[__name__] = _implementation
