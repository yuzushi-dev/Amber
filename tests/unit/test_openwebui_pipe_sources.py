import importlib.util
from pathlib import Path

PIPE = Path(__file__).resolve().parents[2] / "integrations" / "openwebui" / "amber_pipe.py"
spec = importlib.util.spec_from_file_location("amber_pipe", PIPE)
amber_pipe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(amber_pipe)


def test_source_snippet_blockquote_has_no_literal_quotes():
    # OpenWebUI's blockquote style adds its own quotes; literal ones render doubled.
    entry = amber_pipe.format_source_entry(
        1, "**install_requirements.html**", "", "This chunk is part of\n the Firewall   Ports section"
    )
    assert entry == "1. 📄 **install_requirements.html**\n   > This chunk is part of the Firewall Ports section"


def test_source_snippet_truncated_at_200_chars():
    entry = amber_pipe.format_source_entry(2, "**doc**", " (Page 3)", "x" * 250)
    assert entry.endswith("> " + "x" * 200 + "...")
    assert " (Page 3)\n" in entry
