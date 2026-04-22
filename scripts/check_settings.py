import os
import sys

sys.path.append(os.path.join(os.getcwd(), 'src'))
from api.config import get_settings

settings = get_settings()
print(f"OLLAMA_BASE_URL: {settings.ollama_base_url}")
print(f"DEFAULT_LLM_PROVIDER: {settings.default_llm_provider}")
print(f"DEFAULT_EMBEDDING_PROVIDER: {settings.default_embedding_provider}")
