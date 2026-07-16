"""Compatibility alias for the narration segmenter."""

import sys

from app.services.narration import segmenter as _implementation

sys.modules[__name__] = _implementation
