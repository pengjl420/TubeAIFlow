"""Compatibility alias for shared time helpers."""

import sys

from app.shared import time as _implementation

sys.modules[__name__] = _implementation
