"""Compatibility alias for the narration subtitle splitter."""

import sys

from app.services.narration import subtitle_splitter as _implementation

sys.modules[__name__] = _implementation
