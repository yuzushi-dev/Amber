"""
Task Dispatcher Port
====================

Protocol for dispatching asynchronous tasks (e.g. background ingestion).
"""

from typing import Any, Protocol


class TaskDispatcher(Protocol):
    """
    Interface for dispatching background tasks.
    """

    async def dispatch(
        self, task_name: str, args: list[Any] | None = None, kwargs: dict[str, Any] | None = None
    ) -> str:
        """
        Dispatch a task.

        Args:
            task_name: Name of the task to execute
            args: Positional arguments
            kwargs: Keyword arguments

        Returns:
            str: Task ID
        """
        ...

    async def cancel_task(self, task_id: str, terminate: bool = False) -> None:
        """
        Cancel a running or queued task.
        """
        ...
