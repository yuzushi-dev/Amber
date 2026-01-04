import sys
import os
import asyncio
import logging

# Add project root to path
sys.path.insert(0, os.getcwd())

logging.basicConfig(level=logging.INFO)

from src.api.services.setup_service import SetupService, get_setup_service

async def verify():
    print(f"Current Working Directory: {os.getcwd()}")
    
    # Initialize service
    service = SetupService()
    print(f"Resolved PACKAGES_DIR: {service.PACKAGES_DIR}")
    
    # Verify path correctness relative to root
    expected_path = os.path.join(os.getcwd(), ".packages")
    if service.PACKAGES_DIR == expected_path:
        print("SUCCESS: PACKAGES_DIR matches expected local path.")
    else:
        print(f"WARNING: PACKAGES_DIR {service.PACKAGES_DIR} does not match expected {expected_path}")

    # Check if directory exists
    if os.path.isdir(service.PACKAGES_DIR):
        print("SUCCESS: Packages directory exists.")
    else:
        print("ERROR: Packages directory does not exist.")
        return

    # Attempt installation of a small feature first? 
    # Or just try local_embeddings as requested.
    print("Attempting to install 'local_embeddings'...")
    result = await service.install_feature("local_embeddings")
    print(f"Installation Result: {result}")
    
    if result.get("success"):
        print("SUCCESS: Installation reported success.")
    else:
        print("FAILURE: Installation failed.")

if __name__ == "__main__":
    asyncio.run(verify())
