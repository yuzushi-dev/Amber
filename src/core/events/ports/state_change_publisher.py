from typing import Protocol, Any


class StateChangePublisher(Protocol):
    async def publish(self, payload: dict[str, Any]) -> None:
        ...
