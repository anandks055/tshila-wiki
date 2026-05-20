"""Generate wiki articles for every topic in list_of_pages.txt

This script reads the list file, skips entries already marked "- done", invokes
`agent.chatbot` for each topic to produce a long-form article, and writes the
result into the corresponding markdown file under `static_files/`.

Usage:
    python generate_static_pages.py

The script will also append " - done" to each topic in the list once its page
has been generated. It prints progress to stdout.
"""

import json
import re
import time
import sys
from pathlib import Path
from agent import chatbot, chatbot_flexible


class APIError(Exception):
    """Raised when a critical API call fails during article generation."""
    def __init__(self, message: str, api_name: str = "", error_message: str = "", topic: str = ""):
        super().__init__(message)
        self.api_name = api_name
        self.error_message = error_message
        self.topic = topic


LIST_PATH = Path("all_words_deduped.txt")
STATIC_DIR = Path("/home/anandks/wiki-articles")
STATIC_DIR.mkdir(exist_ok=True)


def filter_unused_references(text: str) -> str:
    """Standalone utility: drop unused references block entries, keep body unchanged."""
    REF_HEADERS = ["## Sources and References", "## Sources & References", "## References", "## Sources"]

    header_idx = -1
    header = None
    for h in REF_HEADERS:
        prefix = "\n" + h
        if prefix in text:
            header_idx = text.index(prefix)
            header = h
            break
        if text.startswith(h):
            header_idx = 0
            header = h
            break

    if header_idx == -1:
        return text

    if header_idx == 0:
        body = ""
        refs_block = text
    else:
        body = text[:header_idx].rstrip() + "\n"
        refs_block = text[header_idx:]

    lines = refs_block.splitlines()
    if not lines:
        return text

    header_line = lines[0]
    entry_lines = lines[1:]

    used_nums = {int(n) for n in re.findall(r"\[(\d+)\]", body)}

    filtered_entries = []
    for line in entry_lines:
        m = re.match(r"^\s*\[(\d+)\]\s*:\s*.*$", line)
        if m:
            num = int(m.group(1))
            if num in used_nums:
                filtered_entries.append(line)
        else:
            filtered_entries.append(line)

    if not filtered_entries:
        return body.rstrip() + "\n"

    out = [body.rstrip(), header_line] + filtered_entries
    return "\n".join(out).rstrip() + "\n"


def renumber_references(text: str) -> str:
    """Renumber all references sequentially (1, 2, 3, ...) and update inline citations."""
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
        return text
    
    if header_idx == 0:
        body = ""
        refs_section = text
    else:
        body = text[:header_idx]
        refs_section = text[header_idx:]
    
    # Parse references: [N]: text
    ref_pattern = re.compile(r'^\[(\d+)\]:\s*(.+)$', re.MULTILINE)
    old_refs = {}
    for match in ref_pattern.finditer(refs_section):
        old_num = int(match.group(1))
        ref_text = match.group(2).strip()
        old_refs[old_num] = ref_text
    
    if not old_refs:
        return text
    
    # Find inline citations in order of first appearance
    citation_pattern = re.compile(r'\[(\d+)\]')
    seen_nums = []
    for match in citation_pattern.finditer(body):
        num = int(match.group(1))
        if num in old_refs and num not in seen_nums:
            seen_nums.append(num)
    
    # Only renumber refs that are actually cited (filter_unused_references already removed others)
    all_old_nums = seen_nums
    
    # Create old -> new mapping
    old_to_new = {old: idx + 1 for idx, old in enumerate(all_old_nums)}
    
    # Replace inline citations
    def replace_citation(match):
        old_num = int(match.group(1))
        return f"[{old_to_new[old_num]}]" if old_num in old_to_new else match.group(0)
    
    new_body = citation_pattern.sub(replace_citation, body)
    
    # Rebuild references section
    new_refs_lines = [f"\n{header_used}"]
    for old_num in all_old_nums:
        new_num = old_to_new[old_num]
        new_refs_lines.append(f"[{new_num}]: {old_refs[old_num]}")
    
    return new_body.rstrip() + "\n" + "\n".join(new_refs_lines) + "\n"


def generate_for_topic(topic: str, user_id: str = "script_user", flexible: bool = False) -> str:
    """Call the appropriate chatbot and return the final article text.

    `flexible` selects the new agent that produces variable‑length output based on
    the size of the API context. When False the original `chatbot` is used.

    Raises APIError if dict API call fails.
    """
    session_id = None
    article_text = ""
    agent = chatbot_flexible if flexible else chatbot

    for chunk in agent(topic, user_id, session_id):
        try:
            data = json.loads(chunk)
        except Exception:
            continue

        # Heavily guard against `dict`-failure from tool output.
        # If DICT API response includes error, stop immediately.
        def inspect_for_dict_failure(container):
            if not isinstance(container, dict):
                return None
            if "definition" in container:
                definition = container["definition"]
                if isinstance(definition, dict) and "error" in definition:
                    return definition
            # Might also be nested inside `results`
            results = container.get("results")
            if isinstance(results, dict) and "definition" in results:
                definition = results["definition"]
                if isinstance(definition, dict) and "error" in definition:
                    return definition
            return None

        failure = inspect_for_dict_failure(data)
        if failure is None and isinstance(data, dict) and "event" in data:
            content = data.get("content")
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                    failure = inspect_for_dict_failure(parsed)
                except Exception:
                    pass
            elif isinstance(content, dict):
                failure = inspect_for_dict_failure(content)

        if failure is not None:
            endpoint = failure.get("endpoint", "https://project.iith.ac.in/bheri/dict/v1_5/get_defs/")
            status_code = failure.get("status_code", "unknown")
            message = failure.get("error", "unknown error")
            reason = failure.get("reason", "")
            raise APIError(
                f"DICT API failed for '{topic}' (status {status_code}) on endpoint {endpoint}: {message} {reason}",
                api_name="DICT API",
                error_message=f"{status_code} {message} {reason}".strip(),
                topic=topic,
            )

        if data.get("event") == "RunContent":
            article_text = data.get("content", "")
            break

    return article_text



def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate static pages from topic list")
    parser.add_argument("--flexible", action="store_true",
                        help="Use the flexible-length agent instead of the default")
    args = parser.parse_args()

    lines = LIST_PATH.read_text().splitlines()
    new_lines = []
    try:
        for line in lines:
            stripped = line.strip()
            if not stripped:
                new_lines.append(line)
                continue
            if stripped.endswith(" - done"):
                new_lines.append(line)
                continue
            topic = stripped
            print(f"Generating page for '{topic}'{' (flexible)' if args.flexible else ''}...")
            article = generate_for_topic(topic, flexible=args.flexible)
            if article:
                filename = topic.lower().replace(' ', '_').replace("'", "").replace('"', "").replace('/', '_') + '.md'
                filepath = STATIC_DIR / filename
                filepath.write_text(article)

                # Post-process to remove any unused references (isolated behavior as requested).
                # This keeps all content unchanged except the Sources/References block.
                filtered = filter_unused_references(filepath.read_text(encoding='utf-8'))
                
                # Renumber references sequentially (1, 2, 3, ...) without gaps
                renumbered = renumber_references(filtered)
                filepath.write_text(renumbered, encoding='utf-8')

                print(f"  wrote {filepath} ({len(renumbered.split())} words)")
                # mark done
                new_lines.append(stripped + ' - done')
            else:
                print(f"  no content produced for {topic}, leaving unmodified")
                new_lines.append(line)
            # flush to disk after each
            LIST_PATH.write_text("\n".join(new_lines + lines[len(new_lines):]))
            # politely pause to avoid overloading APIs
            time.sleep(1)
        print("All done.")
    except APIError as e:
        print("\n" + "="*70, file=sys.stderr)
        print("🚨 API FAILURE — GENERATION STOPPED", file=sys.stderr)
        print("="*70, file=sys.stderr)
        print(f"Topic: {e.topic}", file=sys.stderr)
        print(f"API: {e.api_name}", file=sys.stderr)
        print(f"Error Code/Message: {e.error_message}", file=sys.stderr)
        print(f"\nReason: {str(e)}", file=sys.stderr)
        print("="*70, file=sys.stderr)
        print("\n⚠️  Process stopped. No further articles will be generated.", file=sys.stderr)
        print(f"Resume from '{e.topic}' once the API issue is resolved.\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
