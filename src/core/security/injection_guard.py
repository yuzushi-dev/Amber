"""
InjectionGuard - Prompt injection defense.

Uses prompt_guard library when available; falls back to HTML escaping
and whitespace normalization if the library is not installed.
"""
import html
import logging
import re

logger = logging.getLogger(__name__)

try:
    from prompt_guard import Action as _Action
    from prompt_guard import PromptGuard as _PromptGuard
    _BLOCKING_ACTIONS = {_Action.BLOCK, _Action.BLOCK_NOTIFY}
    _PROMPT_GUARD_AVAILABLE = True
except ImportError:
    _PromptGuard = None
    _BLOCKING_ACTIONS = set()
    _PROMPT_GUARD_AVAILABLE = False
    logger.warning("prompt_guard not installed — using basic input sanitization fallback")


class InjectionGuard:
    """
    Security component to defend against prompt injection attacks.
    Uses prompt_guard when available, otherwise escapes HTML/XML tags
    and normalizes whitespace.
    """

    def __init__(self):
        self._guard: object | None = None

    @property
    def guard(self) -> object | None:
        if not _PROMPT_GUARD_AVAILABLE:
            return None
        if self._guard is None:
            self._guard = _PromptGuard()
        return self._guard

    def sanitize_input(self, text: str) -> str:
        if not text:
            return ""

        if _PROMPT_GUARD_AVAILABLE and self.guard is not None:
            sanitized, was_modified, has_encoding = self.guard.normalize(text)
            if was_modified or has_encoding:
                logger.debug(
                    "Input sanitized: was_modified=%s, has_encoding=%s, original=%s...",
                    was_modified, has_encoding, text[:50],
                )
            return sanitized

        # Fallback: escape XML/HTML tags, normalize whitespace
        sanitized = html.escape(text)
        sanitized = re.sub(r"\s+", " ", sanitized).strip()
        return sanitized

    def validate_input(self, text: str) -> bool:
        if not text:
            return True

        if _PROMPT_GUARD_AVAILABLE and self.guard is not None:
            result = self.guard.analyze(text)
            if result.action in _BLOCKING_ACTIONS:
                logger.warning(
                    "Prompt injection detected: action=%s, reasons=%s, text=%s...",
                    result.action.value,
                    result.reasons,
                    text[:100],
                )
            return result.action not in _BLOCKING_ACTIONS

        return True

    def get_analysis(self, text: str) -> object:
        if not text or not _PROMPT_GUARD_AVAILABLE or self.guard is None:
            return None
        return self.guard.analyze(text)
