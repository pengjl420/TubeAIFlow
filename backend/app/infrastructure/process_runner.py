import subprocess
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable


class TaskCancelledError(RuntimeError):
    pass


@dataclass
class _TaskState:
    stage: str
    cancelled: bool = False
    process: subprocess.Popen | None = None
    cancel_callback: Callable[[], None] | None = None
    deferred_calls: list["DeferredCall"] | None = None


class DeferredCall:
    """A call queued behind the currently running project stage."""

    def __init__(self, callback: Callable[[], Any]):
        self.callback = callback
        self._finished = threading.Event()
        self._result: Any = None
        self._error: BaseException | None = None

    def wait(self) -> Any:
        self._finished.wait()
        if self._error is not None:
            raise self._error
        return self._result

    def succeed(self, result: Any) -> None:
        self._result = result
        self._finished.set()

    def fail(self, error: BaseException) -> None:
        self._error = error
        self._finished.set()


_lock = threading.Lock()
_states: dict[str, _TaskState] = {}


@contextmanager
def controlled(project_id: str, stage: str):
    begin(project_id, stage)
    try:
        yield
        check_cancelled(project_id)
    except BaseException as exc:
        _fail_deferred_and_finish(project_id, exc)
        raise
    else:
        _run_deferred_and_finish(project_id)


def begin(project_id: str, stage: str) -> None:
    with _lock:
        state = _states.get(project_id)
        if state:
            raise RuntimeError(f"Project already has a running {state.stage} task")
        _states[project_id] = _TaskState(stage=stage, deferred_calls=[])


def defer_if_running(
    project_id: str,
    stage: str,
    callback: Callable[[], Any],
) -> DeferredCall | None:
    """Queue work behind a matching active stage, or return None if it is idle.

    Registration and stage teardown share the same lock, so a request cannot be
    lost in the small window where the active operation is about to finish.
    """
    with _lock:
        state = _states.get(project_id)
        if state is None or state.stage != stage or state.cancelled:
            return None
        deferred = DeferredCall(callback)
        if state.deferred_calls is None:
            state.deferred_calls = []
        state.deferred_calls.append(deferred)
        return deferred


def finish(project_id: str) -> None:
    with _lock:
        _states.pop(project_id, None)


def _run_deferred_and_finish(project_id: str) -> None:
    first_error: BaseException | None = None
    while True:
        with _lock:
            state = _states.get(project_id)
            if state is None:
                break
            deferred = state.deferred_calls.pop(0) if state.deferred_calls else None
            if deferred is None:
                _states.pop(project_id, None)
                break
        try:
            deferred.succeed(deferred.callback())
        except BaseException as exc:
            deferred.fail(exc)
            first_error = first_error or exc
    if first_error is not None:
        raise first_error


def _fail_deferred_and_finish(project_id: str, error: BaseException) -> None:
    with _lock:
        state = _states.pop(project_id, None)
        deferred_calls = list(state.deferred_calls or []) if state else []
    for deferred in deferred_calls:
        deferred.fail(error)


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
        _terminate_process_tree(process)


def unregister_process(project_id: str, process: subprocess.Popen) -> None:
    """Forget a completed child without clearing the surrounding stage state."""
    with _lock:
        state = _states.get(project_id)
        if state and state.process is process:
            state.process = None


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
        _terminate_process_tree(process)
    return {"cancelled": True, "stage": stage}


def _terminate_process_tree(process: subprocess.Popen) -> None:
    """Terminate the registered command and its descendants.

    TTS runners commonly create worker processes.  Killing only their direct
    parent leaves those workers running (especially on Windows), so a user
    cancellation must target the whole process tree.
    """
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        process.kill()
    except (OSError, subprocess.SubprocessError):
        # The process may have exited between poll() and kill().
        pass


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
