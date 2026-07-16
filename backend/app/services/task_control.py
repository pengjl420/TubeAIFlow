"""Compatibility alias for the task control service's former import path."""

import sys

from app.infrastructure import process_runner as _implementation

sys.modules[__name__] = _implementation
