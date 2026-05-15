"""
InjectionGuard - Prompt injection defense using PromptGuard library.
"""
import logging
from typing import Optional

from prompt_guard import PromptGuard
from prompt_guard import Action

logger = logging.getLogger(__name__)

# Actions that should be treated as blocking
BLOCKING_ACTIONS = {Action.BLOCK, Action.BLOCK_NOTIFY}


class InjectionGuard:
    """
    Security component to defend against prompt injection attacks.
    Uses prompt-guard library for detection and sanitization.
    """

    def __init__(self):
        self._guard: Optional[PromptGuard] = None

    @property
    def guard(self) -> PromptGuard:
        """Lazy initialization of PromptGuard."""
        if self._guard is None:
            self._guard = PromptGuard()
        return self._guard

    def sanitize_input(self, text: str) -> str:
        """
        Sanitizes user input using prompt-guard normalize.
        Returns sanitized text, preserving normal queries unchanged.
        """
        if not text:
            return ""

        sanitized, was_modified, has_encoding = self.guard.normalize(text)
        
        if was_modified or has_encoding:
            logger.debug(
                "Input sanitized: was_modified=%s, has_encoding=%s, original=%s...",
                was_modified, has_encoding, text[:50]
            )
        
        return sanitized

    def validate_input(self, text: str) -> bool:
        """
        Validates input against injection patterns.
        Returns False if injection/unsafe content detected (BLOCK or BLOCK_NOTIFY).
        """
        if not text:
            return True

        result = self.guard.analyze(text)
        
        # Log detection for monitoring
        if result.action in BLOCKING_ACTIONS:
            logger.warning(
                "Prompt injection detected: action=%s, reasons=%s, text=%s...",
                result.action.value,
                result.reasons,
                text[:100]
            )
        
        return result.action not in BLOCKING_ACTIONS

    def get_analysis(self, text: str) -> object:
        """
        Returns full analysis result from prompt-guard.
        Useful for logging and auditing.
        """
        if not text:
            return None
        return self.guard.analyze(text)
