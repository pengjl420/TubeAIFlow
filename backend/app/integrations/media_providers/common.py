from dataclasses import dataclass

from app.schemas.media import RemoteMediaCandidate


@dataclass
class ProviderSearchResponse:
    candidates: list[RemoteMediaCandidate]
    rate_limit: int | None = None
    remaining: int | None = None
    reset_at: str | None = None


class ProviderRequestError(RuntimeError):
    pass


class ProviderRateLimitError(ProviderRequestError):
    def __init__(self, message: str, reset_at: str):
        super().__init__(message)
        self.reset_at = reset_at
