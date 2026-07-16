"""Compatibility alias for the existing rough-cut renderer."""

import sys

from app.services.rendering import rough_cut_service as _implementation

sys.modules[__name__] = _implementation
