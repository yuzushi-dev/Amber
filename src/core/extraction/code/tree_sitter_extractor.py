"""
Tree-Sitter Code Extractor
==========================

Extracts semantic structure (functions, classes) from code using Tree-Sitter.
"""

import logging
from typing import Any

from tree_sitter import Node
from tree_sitter_languages import get_language, get_parser

from src.core.extraction.base import BaseExtractor, ExtractionResult

logger = logging.getLogger(__name__)


class TreeSitterExtractor(BaseExtractor):
    """
    Code extractor using Tree-Sitter to identify semantic blocks.
    """

    def __init__(self):
        self._parsers = {}
        self._languages = {}
        
        # Mapping: MIME types / extensions -> tree-sitter language names
        self.supported_langs = {
            ".py": "python",
            "text/x-python": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            "application/typescript": "typescript",
            ".js": "javascript",
            "application/javascript": "javascript"
        }

    @property
    def name(self) -> str:
        return "TreeSitterCodeExtractor"

    def _get_parser(self, lang_name: str):
        """Lazy load parsers."""
        if lang_name not in self._parsers:
            try:
                language = get_language(lang_name)
                parser = get_parser(lang_name)
                self._languages[lang_name] = language
                self._parsers[lang_name] = parser
            except Exception as e:
                logger.error(f"Failed to load tree-sitter parser for {lang_name}: {e}")
                return None
        return self._parsers.get(lang_name)

    async def extract(self, file_content: bytes, file_type: str, **kwargs) -> ExtractionResult:
        """
        Extract code structure from content.
        """
        # 1. Determine language
        lang_name = self.supported_langs.get(file_type)
        if not lang_name:
            # Fallback for common extensions if passed as type like ".py"
            for ext, name in self.supported_langs.items():
                if file_type.endswith(ext):
                    lang_name = name
                    break
        
        if not lang_name:
            # Default to text extraction if language unknown
            return ExtractionResult(
                content=file_content.decode("utf-8", errors="ignore"),
                extractor_used="FallbackText",
                metadata={"error": "Unsupported language"}
            )

        # 2. Parse
        parser = self._get_parser(lang_name)
        if not parser:
             return ExtractionResult(
                content=file_content.decode("utf-8", errors="ignore"),
                extractor_used="FallbackText",
                metadata={"error": "Parser load failed"}
            )

        text_content = file_content.decode("utf-8", errors="ignore")
        try:
            tree = parser.parse(bytes(text_content, "utf8"))
            root_node = tree.root_node
            
            definitions = []
            self._traverse(root_node, definitions, text_content)
            
            return ExtractionResult(
                content=text_content,
                extractor_used=self.name,
                metadata={
                    "language": lang_name,
                    "definitions": definitions,
                    "loc": len(text_content.splitlines())
                }
            )

        except Exception as e:
            logger.error(f"Tree-sitter extraction error: {e}")
            return ExtractionResult(
                content=text_content,
                extractor_used=self.name,
                metadata={"error": str(e)}
            )

    def _traverse(self, node: Node, definitions: list, source_code: str):
        """Recursively traverse AST to find definitions."""
        
        # Check if node is interesting
        if node.type in ("function_definition", "class_definition", "async_function_definition"):
            name = self._get_name(node, source_code)
            if name:
                definitions.append({
                    "type": node.type,
                    "name": name,
                    "start_line": node.start_point[0] + 1, # 1-indexed
                    "end_line": node.end_point[0] + 1,
                    # We could store content here, but might be too heavy for metadata.
                    # "signature": ... 
                })
        
        # Retrieve children
        for child in node.children:
            self._traverse(child, definitions, source_code)

    def _get_name(self, node: Node, source: str) -> str | None:
        """Extract name from a definition node."""
        # Python: name is usually a child node of type 'identifier'
        for child in node.children:
            if child.type == "identifier":
                return source[child.start_byte : child.end_byte]
        return None
