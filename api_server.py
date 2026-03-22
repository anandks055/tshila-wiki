"""Minimal API for serving the generated markdown pages.

This module uses FastAPI because it's lightweight, async-friendly, and easy to
install.  A full Django project would be overkill for a handful of read–only
endpoints; FastAPI (or Flask) is a much simpler alternative and integrates
well with the existing Python code in this repository.

By default the endpoint exposes `.md` files under `static_files/`, but the
folder can be changed by setting the `STATIC_DIR` environment variable.  This
makes it easy to point the API at `extracted_pages/` (or any other directory)
without editing code.  It returns JSON with a list of objects containing
`path` and `content`.  You could also mount `StaticFiles` if you only needed to
serve the raw files.

Usage:

    pip install fastapi uvicorn
    python api_server.py

Then visit `http://localhost:7171/pages` to get the list.

You can expand this service later—add search, authentication, write support,
etc.—without spinning up a big web framework.
"""

from fastapi import FastAPI, HTTPException
from pathlib import Path
from typing import List, Dict
import os

app = FastAPI(title="Sanskrit Wiki API")

# directory containing markdown pages; can be overridden with the
# STATIC_DIR environment variable (useful for development/testing).
STATIC_DIR = Path(os.getenv("STATIC_DIR", "static_files"))


@app.get("/pages", response_model=List[Dict[str, str]])
async def list_pages() -> List[Dict[str, str]]:
    """Return the content of every markdown file in the static directory."""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=500, detail="static_files directory missing")
    pages = []
    for md in sorted(STATIC_DIR.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception as e:
            # skip files we can't read
            continue
        pages.append({"path": md.name, "content": text})
    return pages


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7171)
