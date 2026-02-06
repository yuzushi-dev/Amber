from typing import Any, Protocol


class StateChangePublisher(Protocol):
    async def publish(self, payload: dict[str, Any]) -> None: ...
