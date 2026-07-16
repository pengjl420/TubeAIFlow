"""Compatibility alias for the narration translation service."""

import sys

from app.services.narration import translation_service as _implementation

sys.modules[__name__] = _implementation
