"""Batch-oriented page generator for faster throughput.

This is a drop-in companion to :mod:`generate_static_pages`.  It reads the
same list file (`yoga_ayurveda_pages.txt` by default) but will dispatch
multiple topics to the `agent.chatbot` in parallel using a thread pool.  The
existing script is left untouched so the original sequential workflow can
still be used when needed.

Usage examples:

    # run with the default of 5 concurrent workers
    python generate_static_pages_batch.py

    # customise concurrency and spacing
    python generate_static_pages_batch.py --workers 10 --pause 0.5

The script still honours lines marked "- done" and will update the list file
in-place when pages are successfully generated.  Blank lines are preserved and
unprocessed topics remain untouched.
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agent import chatbot


# default list path; overridden by `--list` argument if provided
# prefer a "new" list if present, otherwise fall back to the original file
possible = [Path("list_of_pages_new.txt"), Path("yoga_ayurveda_pages.txt")]
LIST_PATH = next((p for p in possible if p.exists()), possible[-1])

STATIC_DIR = Path("static_files")
STATIC_DIR.mkdir(exist_ok=True)


# copied almost verbatim from generate_static_pages so behaviour is identical

def generate_for_topic(topic: str, user_id: str = "script_user") -> str:
    """Call the chatbot and return the final article text.

    This wrapper also logs the start and end times so that it's easy to see
    whether multiple workers are actually running concurrently or are being
    serialized by the underlying model/IO.
    """
    start = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] beginning generation for '{topic}'")
    session_id = None
    article_text = ""
    for chunk in chatbot(topic, user_id, session_id):
        try:
            data = json.loads(chunk)
        except Exception:  # pragma: no cover - defensive
            continue
        if data.get("event") == "RunContent":
            article_text = data.get("content", "")
            break
    end = time.time()
    dur = end - start
    print(f"[{time.strftime('%H:%M:%S')}] finished '{topic}' ({dur:.1f}s)")
    return article_text


def _filename_for_topic(topic: str) -> str:
    # simple mapping that matches generate_static_pages
    return (
        topic.lower()
        .replace(" ", "_")
        .replace("’", "")
        .replace("'", "")
        + ".md"
    )


def main(list_path: Path, workers: int, pause: float, limit: int | None = None):
    # use provided list path instead of global constant
    lines = list_path.read_text().splitlines()
    # collect indices & topics that still need generating
    pending: list[tuple[int, str]] = []  # list of (index, stripped_topic)
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.endswith(" - done"):
            continue
        pending.append((idx, stripped))

    if limit is not None:
        pending = pending[:limit]

    if not pending:
        print("No new topics to process. Everything is already marked done.")
        return

    print(f"Dispatching {len(pending)} topics with {workers} workers...")

    # new_lines will be updated as topics finish; start as a copy of the
    # original lines so we can modify them in-place.
    new_lines = list(lines)

    # run generation in parallel
    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(generate_for_topic, topic): (idx, topic)
            for idx, topic in pending
        }
        for future in as_completed(future_map):
            idx, topic = future_map[future]
            try:
                article = future.result()
            except Exception as exc:  # pragma: no cover
                print(f"ERROR generating {topic}: {exc}")
                article = ""

            print(f"Completed '{topic}' (got {len(article.split())} words)")

            # write result immediately so that progress is durable even if the
            # script is interrupted
            if article:
                filename = _filename_for_topic(topic)
                filepath = STATIC_DIR / filename
                filepath.write_text(article)
                new_lines[idx] = topic + " - done"
            else:
                print(f"no content produced for {topic}, leaving unmodified")

            # persist the partially-updated list file after each topic
            list_path.write_text("\n".join(new_lines))

            # polite pause, not specific to a single worker; helps rate limits
            time.sleep(pause)

    print("Batch generation complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate static pages in parallel batches"
    )
    parser.add_argument(
        "--list",
        type=Path,
        default=LIST_PATH,
        help="path to the topic list file",
    )
    parser.add_argument(
        "--workers", type=int, default=5, help="number of concurrent topics"
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=1.0,
        help="seconds to sleep after each completion (rate limiting)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="process at most this many pending topics (for testing)",
    )
    args = parser.parse_args()
    main(list_path=args.list, workers=args.workers, pause=args.pause, limit=args.limit)
