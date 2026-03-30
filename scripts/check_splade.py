
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

model_name = "naver/splade-cocondenser-ensembledistil"

print(f"Testing load of {model_name}...")

try:
    from transformers import AutoModelForMaskedLM, AutoTokenizer
    print("Transformers imported.")
except ImportError:
    print("Transformers not installed.")
    sys.exit(1)

try:
    print("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    print("Tokenizer loaded.")

    print("Loading model...")
    model = AutoModelForMaskedLM.from_pretrained(model_name)
    print("Model loaded.")

except Exception as e:
    print(f"Error loading model: {e}")
    sys.exit(1)

print("Success.")
