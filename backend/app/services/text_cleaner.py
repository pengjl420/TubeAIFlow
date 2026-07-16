"""Compatibility alias for the narration text cleaner."""

import sys

from app.services.narration import text_cleaner as _implementation

sys.modules[__name__] = _implementation
