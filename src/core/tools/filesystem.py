"""
File System Tools
=================

Tools that allow the Agent to explore the codebase structure and content.
"""

import os
import glob
from typing import Any

def create_filesystem_tools(base_path: str = ".") -> list[dict[str, Any]]:
    """
    Create a list of filesystem tool definitions.
    """
    
    # 1. list_directory
    async def list_directory(path: str = ".") -> str:
        """List files and directories in a given path."""
        try:
            full_path = os.path.join(base_path, path)
            if not os.path.exists(full_path):
                return f"Error: Path '{path}' does not exist."
            
            items = os.listdir(full_path)
            # Filter out hidden files and common ignore folders
            items = [i for i in items if not i.startswith(".") and i not in ("__pycache__", "node_modules", "venv", ".git", ".gemini")]
            
            output = []
            for item in sorted(items):
                item_path = os.path.join(full_path, item)
                if os.path.isdir(item_path):
                    output.append(f"[DIR]  {item}")
                else:
                    output.append(f"[FILE] {item}")
            
            return "\n".join(output) if output else "(empty directory)"
        except Exception as e:
            return f"Error listing directory: {str(e)}"

    # 2. read_file
    async def read_file(path: str, start_line: int = 1, end_line: int = -1) -> str:
        """Read the contents of a file."""
        try:
            full_path = os.path.join(base_path, path)
            if not os.path.exists(full_path):
                return f"Error: File '{path}' does not exist."
            if not os.path.isfile(full_path):
                return f"Error: '{path}' is not a file."
            
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            total_lines = len(lines)
            if start_line < 1: start_line = 1
            if end_line == -1 or end_line > total_lines: end_line = total_lines
            
            # 0-indexed slicing
            selected_lines = lines[start_line-1 : end_line]
            content = "".join(selected_lines)
            
            return f"--- File: {path} ({start_line}-{end_line}/{total_lines}) ---\n{content}"
            
        except UnicodeDecodeError:
            return "Error: File appears to be binary or non-UTF-8."
        except Exception as e:
            return f"Error reading file: {str(e)}"

    # 3. grep_search (Simple regex/string search)
    async def grep_search(pattern: str, path: str = ".", recursive: bool = True) -> str:
        """Search for a string pattern in files."""
        try:
             # Basic implementation using glob and reading files
             # In a real system, we might shell out to grep/ripgrep for speed, 
             # but keeping it python-native is safer for this demo.
             
            matches = []
            search_path = os.path.join(base_path, path)
            
            # Walk through directory
            for root, dirs, files in os.walk(search_path):
                # Skip hidden/ignored
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules", "venv", ".git", ".gemini")]
                
                for file in files:
                    if file.startswith("."): continue
                    
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, base_path)
                    
                    try:
                        with open(file_path, "r", encoding="utf-8", errors='ignore') as f:
                            for i, line in enumerate(f, 1):
                                if pattern in line: # Simple substring match for MVP
                                    matches.append(f"{rel_path}:{i}: {line.strip()[:100]}")
                                    if len(matches) >= 20: # Limit results
                                        return "Found matches (truncated at 20):\n" + "\n".join(matches)
                    except Exception:
                        continue # Skip unreadable files
                        
            if not matches:
                return f"No matches found for '{pattern}'."
            return "Found matches:\n" + "\n".join(matches)
            
        except Exception as e:
            return f"Error executing grep: {str(e)}"

    # Define Schemas
    schemas = [
        {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": "CRITICAL TOOL. Lists all files and folders. Use this FIRST when you need to explore the codebase structure or locate a specific file that is not found by search.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to list (default: root)"}
                    }
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "CRITICAL TOOL. Reads the actual content of a file. Use this AFTER finding a file path with list_directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to the file"},
                        "start_line": {"type": "integer", "description": "Start line number (1-based)"},
                        "end_line": {"type": "integer", "description": "End line number"}
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "grep_search",
                "description": "Search for a string pattern across all files. Use this when you know the exact string (e.g. function name) but not the file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "String or pattern to search for"},
                        "path": {"type": "string", "description": "Directory to search in (default: root)"}
                    },
                    "required": ["pattern"]
                }
            }
        }
    ]

    return [
        {"name": "list_directory", "func": list_directory, "schema": schemas[0]},
        {"name": "read_file", "func": read_file, "schema": schemas[1]},
        {"name": "grep_search", "func": grep_search, "schema": schemas[2]}
    ]
