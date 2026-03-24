#!/usr/bin/env python3
"""Renumber references sequentially without gaps.

This script takes a markdown file with a ## Sources and References section,
renumbers all references sequentially (1, 2, 3, ...) based on their first
appearance in the body text, and updates both inline citations and the
references list accordingly.

Usage:
  python3 renumber_references.py path/to/file.md [--in-place]

If --in-place is omitted, output goes to stdout.
"""

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple


def renumber_references(text: str) -> str:
    """Renumber all references sequentially and update inline citations."""
    
    # Find the references section
    REF_HEADERS = ["## Sources and References", "## Sources & References", "## References", "## Sources"]
    
    header_idx = -1
    header_used = None
    for h in REF_HEADERS:
        marker = "\n" + h
        if marker in text:
            header_idx = text.index(marker)
            header_used = h
            break
        if text.startswith(h):
            header_idx = 0
            header_used = h
            break
    
    if header_idx == -1:
        # No references section found
        return text
    
    # Split body and references
    if header_idx == 0:
        body = ""
        refs_section = text
    else:
        body = text[:header_idx]
        refs_section = text[header_idx:]
    
    # Parse references from the references section
    # Format: [N]: source text
    ref_pattern = re.compile(r'^\[(\d+)\]:\s*(.+)$', re.MULTILINE)
    old_refs: Dict[int, str] = {}
    
    for match in ref_pattern.finditer(refs_section):
        old_num = int(match.group(1))
        ref_text = match.group(2).strip()
        old_refs[old_num] = ref_text
    
    if not old_refs:
        # No references found
        return text
    
    # Find all inline citations in body, in order of first appearance
    citation_pattern = re.compile(r'\[(\d+)\]')
    seen_nums = []
    for match in citation_pattern.finditer(body):
        num = int(match.group(1))
        if num in old_refs and num not in seen_nums:
            seen_nums.append(num)
    
    # Also include any refs that weren't cited but exist in the references section
    # (append them at the end in sorted order)
    uncited = sorted([n for n in old_refs.keys() if n not in seen_nums])
    all_old_nums = seen_nums + uncited
    
    # Create mapping: old number -> new sequential number
    old_to_new: Dict[int, int] = {}
    for new_num, old_num in enumerate(all_old_nums, start=1):
        old_to_new[old_num] = new_num
    
    # Replace inline citations in body
    def replace_citation(match):
        old_num = int(match.group(1))
        if old_num in old_to_new:
            return f"[{old_to_new[old_num]}]"
        return match.group(0)  # keep unchanged if not in mapping
    
    new_body = citation_pattern.sub(replace_citation, body)
    
    # Rebuild references section with new sequential numbers
    new_refs_lines = [f"\n{header_used}"]
    for old_num in all_old_nums:
        new_num = old_to_new[old_num]
        ref_text = old_refs[old_num]
        new_refs_lines.append(f"[{new_num}]: {ref_text}")
    
    # Combine and return
    return new_body.rstrip() + "\n" + "\n".join(new_refs_lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Renumber references sequentially without gaps"
    )
    parser.add_argument("file", help="Markdown file to process")
    parser.add_argument("--in-place", action="store_true", help="Overwrite input file")
    args = parser.parse_args()
    
    path = Path(args.file)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    
    text = path.read_text(encoding="utf-8")
    result = renumber_references(text)
    
    if args.in_place:
        path.write_text(result, encoding="utf-8")
        print(f"✓ Renumbered references in: {path}")
    else:
        print(result, end="")


if __name__ == "__main__":
    main()
