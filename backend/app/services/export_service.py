"""Compatibility alias for the manifest service's former import path."""

import sys

from app.services.projects import manifest_service as _implementation

sys.modules[__name__] = _implementation
