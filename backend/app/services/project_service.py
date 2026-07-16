"""Compatibility alias for the project service's former import path."""

import sys

from app.services.projects import project_service as _implementation

sys.modules[__name__] = _implementation
