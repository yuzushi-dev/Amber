
import logging
import sys
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from src.core.utils.batching import batch_texts_for_embedding
    print("Imported batch_texts_for_embedding")
except ImportError as e:
    print(f"Failed to import: {e}")
    sys.exit(1)

texts = ["This is a test sentence." for _ in range(316)]
model = "nomic-embed-text:latest"

print(f"Starting batching for {len(texts)} texts using model {model}...")
start = time.time()

try:
    batches = batch_texts_for_embedding(texts, model=model)
    end = time.time()
    print(f"Batching completed in {end - start:.4f}s")
    print(f"Generated {len(batches)} batches")
except Exception as e:
    print(f"Batching failed: {e}")
    sys.exit(1)

print("Success.")
