from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.models.narration import Segment
from app.models.project import Project
from app.providers.runtime import ProviderRuntime


RequiredPaths = Callable[[Settings], dict[str, Path | None]]
ValidateAssets = Callable[[Settings, Project], None]
SynthesizeBatch = Callable[[Project, Path, list[Segment], Path, Path], None]


@dataclass(frozen=True, slots=True)
class TTSProviderRuntime(ProviderRuntime):
    """Executable TTS adapter used by narration services.

    Callables keep existing, well-tested local runner implementations intact while
    moving provider selection out of business logic.  Individual adapters can later be
    promoted to standalone classes without changing consumers.
    """

    required_paths: RequiredPaths
    validate_assets: ValidateAssets
    synthesize_batch: SynthesizeBatch

