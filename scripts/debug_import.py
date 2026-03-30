import os
import sys

# Add src to path
sys.path.append(os.getcwd())

try:
    print("Import successful")
except Exception as e:
    print(f"Import failed: {e}")
    import traceback
    traceback.print_exc()
