"""Compatibility alias for the narration timeline service."""

import sys

from app.services.narration import timeline_service as _implementation

sys.modules[__name__] = _implementation
