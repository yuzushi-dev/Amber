#!/usr/bin/env python3
"""
Compare HTML extraction: flat text (html_bs4) vs Markdown normalization
(html_markdown, content scoping + MarkItDown).

Usage:
    python3 scripts/compare_html_normalization.py <dir-with-html-files> [--show N]

For each .html file in the directory, runs both extractors and reports:
  - output length delta (noise removed)
  - structure gained (markdown headers, pipe tables, code fences)
  - residual noise lines (chrome patterns) per extractor

Exit code 0 always; this is a diagnostic, not a gate.
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.ingestion.infrastructure.extraction.local.html_extractor import HtmlExtractor
from src.core.ingestion.infrastructure.extraction.local.markdown_html_extractor import (
    MarkdownHtmlExtractor,
)

NOISE_PATTERNS = (
    re.compile(r"^\s*(previous|next)\s*$", re.IGNORECASE),
    re.compile(r"©|copyright", re.IGNORECASE),
    re.compile(r"^\s*(repository|open issue|skip to (main )?content)\s*", re.IGNORECASE),
    re.compile(r"privacy\s*&\s*legal", re.IGNORECASE),
)


def noise_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if any(p.search(line) for p in NOISE_PATTERNS))


def structure_stats(text: str) -> dict:
    return {
        "headers": len(re.findall(r"^#{1,6} ", text, re.MULTILINE)),
        "tables": len(re.findall(r"^\| --- ", text, re.MULTILINE)),
        "code_fences": text.count("```") // 2,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus_dir", type=Path)
    parser.add_argument("--show", type=int, default=0, help="print full diff for first N files")
    args = parser.parse_args()

    files = sorted(args.corpus_dir.glob("*.html"))
    if not files:
        print(f"No .html files in {args.corpus_dir}")
        return

    flat = HtmlExtractor()
    norm = MarkdownHtmlExtractor()

    tot = {"files": 0, "flat_chars": 0, "norm_chars": 0, "flat_noise": 0, "norm_noise": 0,
           "headers": 0, "tables": 0, "code_fences": 0, "fallbacks": 0}

    for path in files:
        content = path.read_bytes()
        old = await flat.extract(content, "text/html")
        new = await norm.extract(content, "text/html")

        if new.extractor_used != "html_markdown":
            tot["fallbacks"] += 1
        stats = structure_stats(new.content)
        tot["files"] += 1
        tot["flat_chars"] += len(old.content)
        tot["norm_chars"] += len(new.content)
        tot["flat_noise"] += noise_lines(old.content)
        tot["norm_noise"] += noise_lines(new.content)
        for k in ("headers", "tables", "code_fences"):
            tot[k] += stats[k]

        if args.show and tot["files"] <= args.show:
            print(f"{'=' * 70}\n{path.name}\n{'-' * 30} FLAT\n{old.content[:600]}")
            print(f"{'-' * 30} NORMALIZED\n{new.content[:600]}\n")

    delta = 100 * (1 - tot["norm_chars"] / tot["flat_chars"]) if tot["flat_chars"] else 0
    print(f"files: {tot['files']} (fallback to flat: {tot['fallbacks']})")
    print(f"chars: {tot['flat_chars']} -> {tot['norm_chars']} ({delta:+.1f}% = noise removed)")
    print(f"noise lines: {tot['flat_noise']} -> {tot['norm_noise']}")
    print(f"structure gained: {tot['headers']} headers, {tot['tables']} tables, "
          f"{tot['code_fences']} code fences")


if __name__ == "__main__":
    asyncio.run(main())
