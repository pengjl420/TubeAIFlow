"""Compatibility alias for the narration SRT service."""

import sys

from app.services.narration import srt_service as _implementation

sys.modules[__name__] = _implementation
