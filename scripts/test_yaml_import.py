
import sys

print(f"Python executable: {sys.executable}")
print(f"Sys path before: {sys.path}")

if "/app/.packages" not in sys.path:
    sys.path.insert(0, "/app/.packages")

print(f"Sys path after: {sys.path}")

try:
    import yaml
    print(f"YAML imported successfully: {yaml}")
except ImportError as e:
    print(f"Failed to import yaml: {e}")

try:
    import pydantic
    print(f"Pydantic imported successfully: {pydantic}")
except ImportError as e:
    print(f"Failed to import pydantic: {e}")
