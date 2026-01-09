
import asyncio
from uuid import uuid4
from datetime import datetime
from src.api.deps import _async_session_maker
from src.core.models.api_key import ApiKey
from src.shared.security import generate_api_key, hash_api_key

async def create_temp_key():
    raw_key = generate_api_key()
    hashed = hash_api_key(raw_key)
    
    async with _async_session_maker() as session:
        new_key = ApiKey(
            id=str(uuid4()),
            name="temp-debug-key",
            prefix=raw_key.split("_")[0],
            hashed_key=hashed,
            last_chars=raw_key[-4:],
            scopes=["admin"],
            created_at=datetime.utcnow()
        )
        session.add(new_key)
        await session.commit()
        print(f"CREATED_KEY:{raw_key}")

if __name__ == "__main__":
    asyncio.run(create_temp_key())
