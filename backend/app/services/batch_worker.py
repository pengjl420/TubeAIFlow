"""Compatibility alias for the batch worker's former import path."""

import sys

from app.services.batches import batch_worker as _implementation

sys.modules[__name__] = _implementation
