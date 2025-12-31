
try:
    import unstructured
    print(f"Unstructured version: {unstructured.__version__}")
except ImportError as e:
    print(f"Failed to import unstructured: {e}")

try:
    from unstructured.partition.auto import partition
    print("Successfully imported partition!")
except Exception as e:
    print(f"Failed to import partition: {e}")
    import traceback
    traceback.print_exc()

import magic
print("Magic imported successfully")
