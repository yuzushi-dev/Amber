import re
from typing import List

class PIIScrubber:
    """
    Security component to redact Personally Identifiable Information (PII) 
    from text streams or documents.
    """
    
    # Regex patterns for common PII
    PATTERNS = {
        # US Phone numbers: (123) 456-7890, 123-456-7890, 123.456.7890
        "PHONE": r'\b(\+?1?[-.]?)?\(?([2-9][0-8][0-9])\)?[-. ]?([2-9][0-9]{2})[-. ]?([0-9]{4})\b',
        
        # Email: basic pattern
        "EMAIL": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        
        # SSN: 000-00-0000
        "SSN": r'\b(?!000|666|9\d{2})\d{3}[- ](?!00)\d{2}[- ](?!0000)\d{4}\b',
        
        # Credit Card: 16 digits with optional separators (refined to reduce false positives)
        "CREDIT_CARD": r'\b(?:\d{4}[- ]?){3}\d{4}\b'
    }

    def __init__(self):
        self.compiled_patterns = {
            name: re.compile(pattern) 
            for name, pattern in self.PATTERNS.items()
        }

    def scrub_text(self, text: str) -> str:
        """
        Redacts PII from the given text.
        """
        if not text:
            return ""
            
        scrubbed = text
        
        # Phone
        scrubbed = self.compiled_patterns["PHONE"].sub("[PHONE REDACTED]", scrubbed)
        
        # Email - Masking first part: j***@gmail.com
        def mask_email(match):
            email = match.group(0)
            parts = email.split('@')
            if len(parts) == 2:
                name, domain = parts
                if len(name) > 2:
                    return f"{name[0]}***@{domain}"
                else:
                    return f"***@{domain}"
            return "[EMAIL REDACTED]"
            
        scrubbed = self.compiled_patterns["EMAIL"].sub(mask_email, scrubbed)
        
        # SSN
        scrubbed = self.compiled_patterns["SSN"].sub("[SSN REDACTED]", scrubbed)
        
        # Credit Card (refined pattern to reduce false positives)
        scrubbed = self.compiled_patterns["CREDIT_CARD"].sub("[CREDIT CARD REDACTED]", scrubbed)
        
        return scrubbed

    def scrub_context_chunks(self, chunks: List[str]) -> List[str]:
        """
        Scrubs PII from a list of context chunks.
        Preferred over streaming scrub for MVP simplicity.
        """
        return [self.scrub_text(chunk) for chunk in chunks]
