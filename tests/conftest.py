import sys
from unittest.mock import MagicMock

# Mock dependencies that might be missing in the host environment
mock_modules = [
    "neo4j",
    "pymilvus",
    "cdlib",
    "leidenalg",
    "igraph",
    "tiktoken",
    "sentence_transformers",
    "flashrank",
    "pydantic_settings",
    "minio",
    "pydantic",
    "fastapi",
    "pydantic_core",
    "tenacity",
    "numpy",
    "pandas",
    "scipy",
    "sklearn"
]

for module_name in mock_modules:
    if module_name not in sys.modules:
        sys.modules[module_name] = MagicMock()

# Specifically mock AsyncGraphDatabase for neo4j
import neo4j
neo4j.AsyncGraphDatabase = MagicMock()
neo4j.AsyncDriver = MagicMock()
neo4j.AsyncSession = MagicMock()
