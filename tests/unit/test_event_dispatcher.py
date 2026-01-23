import pytest

from src.core.events.dispatcher import EventDispatcher, StateChangeEvent
from src.core.state.machine import DocumentStatus


class FakePublisher:
    def __init__(self) -> None:
        self.published = []

    async def publish(self, payload):
        self.published.append(payload)


@pytest.mark.asyncio
async def test_event_dispatcher_calls_publisher():
    dispatcher = EventDispatcher(publisher=FakePublisher())
    event = StateChangeEvent(
        document_id="doc-1",
        old_status=None,
        new_status=DocumentStatus.INGESTED,
        tenant_id="tenant-1",
        details={"progress": 1},
    )

    await dispatcher.emit_state_change(event)

    assert dispatcher.publisher.published
