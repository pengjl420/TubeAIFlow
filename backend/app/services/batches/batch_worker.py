"""Compatibility facade for the former batch-only worker.

All project generation now runs through the persistent global task worker.
"""

from app.services.tasks import task_worker


def start_worker() -> None:
    task_worker.start_worker()


def wake_worker() -> None:
    task_worker.wake_worker()


def recover_and_start_worker() -> None:
    task_worker.recover_and_start_worker()


def process_next_item() -> bool:
    return task_worker.process_next_task()
