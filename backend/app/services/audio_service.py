"""Compatibility alias for the narration audio service."""

import sys

from app.services.narration import audio_service as _implementation

sys.modules[__name__] = _implementation
