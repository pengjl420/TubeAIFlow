"""Compatibility alias for the narration ASS service."""

import sys

from app.services.narration import ass_service as _implementation

sys.modules[__name__] = _implementation
