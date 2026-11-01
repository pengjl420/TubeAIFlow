from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

from app.providers.runtime import ProviderRuntime
from app.providers.types import ProviderBillingMode, ProviderCostEstimate, ProviderHealth


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
    local: bool = True

    def health_check(self, request: ImageBatchRequest) -> ProviderHealth:
        if not self.local:
            return ProviderHealth(available=True)
        missing = [
            str(path)
            for path in (request.python_path, request.model_path, request.config_dir)
            if not path.exists()
        ]
        if missing:
            return ProviderHealth(
                available=False,
                error=f"Required local assets are missing: {', '.join(missing)}",
            )
        return ProviderHealth(available=True)

    def estimate_cost(self, request: ImageBatchRequest) -> ProviderCostEstimate:
        """Expose billing ownership without inventing a volatile per-image price."""
        return ProviderCostEstimate(
            billing=ProviderBillingMode.LOCAL if self.local else ProviderBillingMode.EXTERNAL,
            estimated_usd=0,
            usage={"images": len(request.jobs)},
        )
