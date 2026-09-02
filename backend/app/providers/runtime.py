from __future__ import annotations

from typing import Protocol, TypeVar, runtime_checkable


@runtime_checkable
class ProviderRuntime(Protocol):
    """Marker protocol for an executable provider implementation.

    Category-specific protocols extend this contract.  The core registry deliberately
    keeps the runtime type generic so adding a provider category never requires changing
    the registry itself.
    """


ProviderRuntimeT = TypeVar("ProviderRuntimeT", bound=ProviderRuntime)

