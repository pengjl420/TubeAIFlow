"""Compatibility alias for filesystem safety helpers."""

import sys

from app.infrastructure import file_storage as _implementation

sys.modules[__name__] = _implementation
