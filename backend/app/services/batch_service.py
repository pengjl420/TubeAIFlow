"""Compatibility alias for the batch service's former import path."""

import sys

from app.services.batches import batch_service as _implementation

sys.modules[__name__] = _implementation
