import subprocess
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable


class TaskCancelledError(RuntimeError):
    pass


@dataclass
class _TaskState:
    stage: str
    cancelled: bool = False
    process: subprocess.Popen | None = None
    cancel_callback: Callable[[], None] | None = None


_lock = threading.Lock()
_states: dict[str, _TaskState] = {}


@contextmanager
def controlled(project_id: str, stage: str):
    begin(project_id, stage)
    try:
        yield
        check_cancelled(project_id)
    finally:
        finish(project_id)


def begin(project_id: str, stage: str) -> None:
    with _lock:
        state = _states.get(project_id)
        if state:
            raise RuntimeError(f"Project already has a running {state.stage} task")
        _states[project_id] = _TaskState(stage=stage)


def finish(project_id: str) -> None:
    with _lock:
        _states.pop(project_id, None)


def check_cancelled(project_id: str) -> None:
    with _lock:
        cancelled = bool(_states.get(project_id) and _states[project_id].cancelled)
    if cancelled:
        raise TaskCancelledError("Task was stopped by the user")


def register_process(project_id: str, process: subprocess.Popen) -> None:
    with _lock:
        state = _states.get(project_id)
        if state is None:
            state = _TaskState(stage="running")
            _states[project_id] = state
        state.process = process
        cancelled = state.cancelled
    if cancelled and process.poll() is None:
        process.kill()


def register_cancel_callback(project_id: str, callback: Callable[[], None] | None) -> None:
    with _lock:
        state = _states.get(project_id)
        if state:
            state.cancel_callback = callback


def cancel(project_id: str) -> dict:
    with _lock:
        state = _states.get(project_id)
        if state is None:
            return {"cancelled": False, "stage": None}
        state.cancelled = True
        process = state.process
        callback = state.cancel_callback
        stage = state.stage
    if callback:
        try:
            callback()
        except Exception:
            pass
    if process and process.poll() is None:
        process.kill()
    return {"cancelled": True, "stage": stage}


def status(project_id: str) -> dict:
    with _lock:
        state = _states.get(project_id)
        if state is None:
            return {"running": False, "stage": None, "cancelled": False}
        return {
            "running": True,
            "stage": state.stage,
            "cancelled": state.cancelled,
        }
