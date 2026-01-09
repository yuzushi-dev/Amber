
import asyncio
from sqlalchemy import select
from src.api.deps import _async_session_maker
from src.core.models.benchmark_run import BenchmarkRun

RUN_ID = "40d4d974-83eb-4dd7-9c6c-a8b34f757ea1"

async def check_status():
    async with _async_session_maker() as session:
        result = await session.execute(select(BenchmarkRun).where(BenchmarkRun.id == RUN_ID))
        run = result.scalars().first()
        if run:
            print(f"STATUS:{run.status.value}")
            print(f"METRICS:{run.metrics}")
            # Print first 3 details to see individual scores
            if run.details:
                print(f"DETAILS_SAMPLE:{run.details[:3]}")
        else:
            print("Run not found")

if __name__ == "__main__":
    asyncio.run(check_status())
