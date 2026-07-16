"""Compatibility alias for the native dialog service's former import path."""

import sys

from app.services.projects import native_dialog_service as _implementation

sys.modules[__name__] = _implementation
