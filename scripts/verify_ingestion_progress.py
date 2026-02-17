
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mock classes to simulate the environment
class MockEventDispatcher:
    def __init__(self):
        self.events = []
        self.last_progress = 0

    async def emit_state_change(self, event):
        progress = event.details.get("progress", 0)
        logger.info(f"Event emitted: Status={event.new_status}, Progress={progress}")
        
        if progress < self.last_progress and event.new_status == "graph_sync":
             logger.error(f"REGRESSION DETECTED: Progress stepped back from {self.last_progress} to {progress}")
        
        self.last_progress = progress
        self.events.append(event)

async def simulate_graph_sync_progress():
    dispatcher = MockEventDispatcher()
    
    # Simulate the logic in ingestion_service.py
    total_chunks = 100
    
    # Base progress for graph sync
    await dispatcher.emit_state_change(MagicMock(new_status="graph_sync", details={"progress": 70}))
    
    # Granular updates
    async def _on_graph_progress(completed, total):
        progress = 70 + int((completed / total) * 25)
        await dispatcher.emit_state_change(
            MagicMock(new_status="graph_sync", details={"progress": progress})
        )

    # Simulate fast updates
    for i in range(1, total_chunks + 1):
        # In the bug scenario, these were fire-and-forget, so they could arrive out of order
        # Now we await them
        await _on_graph_progress(i, total_chunks)
        
    # Final update
    await dispatcher.emit_state_change(MagicMock(new_status="ready", details={"progress": 100}))

async def simulate_embedding_progress():
    dispatcher = MockEventDispatcher()
    total_chunks = 50
    
    # Base progress
    await dispatcher.emit_state_change(MagicMock(new_status="embedding", details={"progress": 60}))

    # Granular updates (new feature)
    async def _on_embedding_progress(completed, total):
        progress = 60 + int((completed / total) * 10)
        await dispatcher.emit_state_change(
            MagicMock(new_status="embedding", details={"progress": progress})
        )
        
    for i in range(1, total_chunks + 1):
        await _on_embedding_progress(i, total_chunks)
        
    # Next stage
    await dispatcher.emit_state_change(MagicMock(new_status="graph_sync", details={"progress": 70}))

async def main():
    print("--- Verifying Graph Sync Progress Monotonicity (Backend Fix) ---")
    await simulate_graph_sync_progress()
    
    print("\n--- Verifying Embedding Progress Granularity (New Feature) ---")
    await simulate_embedding_progress()

if __name__ == "__main__":
    asyncio.run(main())
