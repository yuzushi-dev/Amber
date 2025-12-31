"""
Prompt Registry
===============

Manages prompt versions and retrieval.
"""

import logging
from typing import Dict, Optional, Any
from src.core.generation.prompts import PROMPTS

logger = logging.getLogger(__name__)

class PromptRegistry:
    """
    Service for managing and retrieving prompt templates.
    """

    def __init__(self, overrides: Optional[Dict[str, Dict[str, str]]] = None):
        # Allow dynamic overrides (e.g. from a DB or config file)
        self._prompts = PROMPTS.copy()
        if overrides:
            for key, versions in overrides.items():
                if key in self._prompts:
                    self._prompts[key].update(versions)
                else:
                    self._prompts[key] = versions

    def get_prompt(self, name: str, version: str = "latest") -> str:
        """
        Retrieve a prompt by name and version.
        
        Args:
            name: Key in the PROMPTS dictionary (e.g., 'rag_system')
            version: Specific version string or 'latest'
            
        Returns:
            The prompt template string.
            
        Raises:
            KeyError: If prompt name or version not found.
        """
        if name not in self._prompts:
            logger.error(f"Prompt '{name}' not found in registry")
            raise KeyError(f"Prompt '{name}' not found")
            
        versions = self._prompts[name]
        if version not in versions:
            logger.warning(f"Version '{version}' for prompt '{name}' not found, falling back to 'latest'")
            return versions.get("latest", "")
            
        return versions[version]

    def list_prompts(self) -> Dict[str, list]:
        """List all available prompts and their versions."""
        return {name: list(versions.keys()) for name, versions in self._prompts.items()}
