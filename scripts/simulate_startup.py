import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from src.core.services.api_key_service import ApiKeyService
from src.core.database.session import async_session_maker

async def main():
    try:
        # Define a mock dev key (same as one used in main.py)
        dev_key = "amber-dev-key-2024" # Default fallback in main.py
        
        print("Simulating API Bootstrap...")
        async with async_session_maker() as session:
            service = ApiKeyService(session)
            # This calls the modified function
            await service.ensure_bootstrap_key(dev_key, name="Development Key")
            print("Bootstrap complete.")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
