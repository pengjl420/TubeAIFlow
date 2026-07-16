"""Compatibility alias for the narration workflow's former import path."""

import sys

from app.workflows import narration_generation as _implementation

sys.modules[__name__] = _implementation
