"""Compatibility alias for the project layout infrastructure."""

import sys

from app.infrastructure import project_layout as _implementation

sys.modules[__name__] = _implementation
