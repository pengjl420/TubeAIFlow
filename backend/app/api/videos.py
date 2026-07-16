"""Compatibility alias for the render API module's former import path."""

import sys

from app.api import renders as _implementation

sys.modules[__name__] = _implementation
