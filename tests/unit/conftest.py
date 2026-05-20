"""Unit-test-specific conftest.

Ensures that the mocked ``tiktoken`` module installed by ``tests/conftest.py``
exposes a valid ``__spec__`` attribute. Some transitive imports (notably
``transformers``) call ``importlib.util.find_spec("tiktoken")`` which raises
``ValueError: tiktoken.__spec__ is not set`` if the module object lacks a
proper ``ModuleSpec``.

This conftest runs after ``tests/conftest.py`` (pytest collects parent
conftests first), so by the time we execute, ``sys.modules["tiktoken"]`` is
already the ``MockTiktoken`` instance. We attach a synthetic ``ModuleSpec``
to it so ``find_spec`` succeeds.
"""

from __future__ import annotations

import sys
from importlib.machinery import ModuleSpec


def _ensure_module_spec(module_name: str) -> None:
    mod = sys.modules.get(module_name)
    if mod is None:
        return
    spec = getattr(mod, "__spec__", None)
    if spec is None:
        try:
            mod.__spec__ = ModuleSpec(module_name, loader=None)
        except (AttributeError, TypeError):
            # Some mock objects don't allow arbitrary attribute assignment;
            # fall back to wrapping in a minimal module-like shim.
            pass
    if not hasattr(mod, "__name__"):
        try:
            mod.__name__ = module_name
        except (AttributeError, TypeError):
            pass


# Modules that may be mocked by tests/conftest.py and need a valid __spec__
# so that importlib.util.find_spec() works when third-party libs probe them.
for _name in ("tiktoken", "neo4j", "pymilvus", "sentence_transformers"):
    _ensure_module_spec(_name)
