"""Compatibility alias for FFmpeg infrastructure."""

import sys

from app.infrastructure import ffmpeg as _implementation

sys.modules[__name__] = _implementation
