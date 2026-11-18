"""Compute control contract; image execution remains a separate provider."""
from typing import Protocol

from pydantic import BaseModel


class ComputeError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class ComputeInstance(BaseModel):
    instance_id: str
    name: str = ""
    state: str = "unknown"
    region: str = ""
    zone: str = ""
    gpu_type: str = ""
    gpu_count: int = 0
    is_spot: bool = False


class InstancePage(BaseModel):
    total: int
    instances: list[ComputeInstance]


class ComputeProvider(Protocol):
    def list_instances(self, *, region: str = "", zone: str = "",
                       project_id: str = "", instance_id: str = "",
                       offset: int = 0, limit: int = 20) -> InstancePage: ...

    def start_instance(self, *, region: str, zone: str, project_id: str = "", instance_id: str) -> None: ...
    def stop_instance(self, *, region: str, zone: str, project_id: str = "", instance_id: str) -> None: ...
