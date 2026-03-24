
import asyncio
import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from src.shared.kernel.runtime import configure_settings
from src.api.config import settings as api_settings
from src.core.database.session import configure_database, async_session_maker
from src.core.admin_ops.application.rules_service import RulesService

async def main():
    # Initialize settings and database
    configure_settings(api_settings)
    configure_database(api_settings)
    
    rules_service = RulesService(session_factory=async_session_maker)
    rules = await rules_service.get_active_rules(force_refresh=True)
    
    print("ACTIVE RULES:")
    if not rules:
        print("No active rules found.")
    for i, r in enumerate(rules):
        print(f"{i+1}. {r}")

if __name__ == "__main__":
    asyncio.run(main())
