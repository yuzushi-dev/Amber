
import sys

# Ensure custom packages are loadable
if "/app/.packages" not in sys.path:
    sys.path.insert(0, "/app/.packages")

from src.workers.tasks import process_communities

print("Triggering community processing task...")
result = process_communities.delay(tenant_id="default")
print(f"Task triggered with ID: {result.id}")
