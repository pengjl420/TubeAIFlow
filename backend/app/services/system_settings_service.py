"""Compatibility alias for the settings service's former import path."""

import sys

from app.services.settings import system_settings_service as _implementation

sys.modules[__name__] = _implementation
