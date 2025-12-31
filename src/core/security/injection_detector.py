import re
from typing import List

class InjectionDetector:
    """
    Service to detect prompt injection attempts using heuristics and patterns.
    """
    
    # Common injection patterns
    INJECTION_PATTERNS = [
        r"(ignore|disregard)\s+(all\s+)?(previous|prior)\s+instructions",
        r"(ignore|disregard)\s+(all\s+)?instructions",
        r"system\s+override",
        r"delete\s+all\s+files",
        r"drop\s+table",
        r"show\s+me\s+your\s+instructions",
        r"what\s+are\s+your\s+instructions",
        r"output\s+source\s+code",
        r"endoftext",
        r"<\|endoftext\|>"
    ]

    def __init__(self):
        self.compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.INJECTION_PATTERNS]

    def detect(self, text: str) -> bool:
        """
        Heuristic detection of prompt injection attempts.
        Returns True if potential injection detected.
        """
        if not text:
            return False
            
        for pattern in self.compiled_patterns:
            if pattern.search(text):
                return True
        return False
