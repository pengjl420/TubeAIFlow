from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from app.providers.runtime import ProviderRuntime


@dataclass(frozen=True, slots=True)
class ImageBatchRequest:
    """Persistence-free request passed from workflow orchestration to a provider."""

    project_id: str
    jobs: tuple[dict, ...]
    batch_path: Path
    result_path: Path
    progress_path: Path
    python_path: Path
    model_path: Path
    config_dir: Path
    device: str
    dtype: str
    cpu_offload: bool


GenerateImageBatch = Callable[[ImageBatchRequest], None]


@dataclass(frozen=True, slots=True)
class ImageProviderRuntime(ProviderRuntime):
    """Executable image adapter isolated from workflow and persistence models."""

    generate_batch: GenerateImageBatch
