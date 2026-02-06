from pathlib import Path

import yaml

from src.api.config import get_settings

settings = get_settings()

print(f"Default LLM Provider: {settings.default_llm_provider}")
print(f"Default LLM Model: {settings.default_llm_model}")
print(f"Default Embedding Provider: {settings.default_embedding_provider}")
print(f"Default Embedding Model: {settings.default_embedding_model}")

# Check if setting manually works
config_path = Path("config/settings.yaml")
if config_path.exists():
    with open(config_path) as f:
        data = yaml.safe_load(f)
        print("\nYAML Content:")
        print(f"LLM: {data.get('llm')}")
        print(f"Embeddings: {data.get('embeddings')}")
else:
    print("config/settings.yaml not found!")
