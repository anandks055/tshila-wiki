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
from pathlib import Path
from agent import chatbot, chatbot_flexible

LIST_PATH = Path("small_test_list.txt")
STATIC_DIR = Path("static_files")
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


def generate_for_topic(topic: str, user_id: str = "script_user", flexible: bool = False) -> str:
    """Call the appropriate chatbot and return the final article text.

    `flexible` selects the new agent that produces variable‑length output based on
    the size of the API context. When False the original `chatbot` is used.
    """
    session_id = None
    article_text = ""
    agent = chatbot_flexible if flexible else chatbot
    for chunk in agent(topic, user_id, session_id):
        try:
            data = json.loads(chunk)
        except Exception:
            continue
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
            filename = topic.lower().replace(' ', '_').replace('’','').replace("'","") + '.md'
            filepath = STATIC_DIR / filename
            filepath.write_text(article)

            # Post-process to remove any unused references (isolated behavior as requested).
            # This keeps all content unchanged except the Sources/References block.
            filtered = filter_unused_references(filepath.read_text(encoding='utf-8'))
            filepath.write_text(filtered, encoding='utf-8')

            print(f"  wrote {filepath} ({len(filtered.split())} words)")
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


if __name__ == "__main__":
    main()
