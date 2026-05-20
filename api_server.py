"""Minimal API for serving the generated markdown pages.

This module uses FastAPI because it's lightweight, async-friendly, and easy to
install.  A full Django project would be overkill for a handful of read–only
endpoints; FastAPI (or Flask) is a much simpler alternative and integrates
well with the existing Python code in this repository.

By default the endpoint exposes `.md` files under `wiki-articles/`, but the
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
from typing import List, Dict, Optional, Any
import os

app = FastAPI(title="Sanskrit Wiki API")

# directory containing markdown pages; can be overridden with the
# STATIC_DIR environment variable (useful for development/testing).
STATIC_DIR = Path(os.getenv("STATIC_DIR", "/home/anandks/wiki-articles"))

# Cache the list of markdown files
_cached_pages = None

def _get_all_pages():
    """Get all markdown files from the static directory (cached)."""
    global _cached_pages
    if _cached_pages is not None:
        return _cached_pages
    
    if not STATIC_DIR.exists():
        return []
    
    _cached_pages = sorted(STATIC_DIR.glob("*.md"))
    return _cached_pages


@app.get("/pages/list", response_model=Dict[str, Any])
async def list_pages_metadata(page: int = 1, limit: int = 100) -> Dict[str, Any]:
    """Return metadata (path only) of markdown files with pagination."""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=500, detail="wiki-articles directory missing")
    
    all_pages = _get_all_pages()
    total = len(all_pages)
    
    if page < 1:
        page = 1
    
    skip = (page - 1) * limit
    paginated = all_pages[skip : skip + limit]
    
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "pages": [{"path": md.name} for md in paginated]
    }


@app.get("/pages", response_model=Dict[str, Any])
async def list_pages(page: int = 1, limit: int = 100) -> Dict[str, Any]:
    """Return paginated pages with content. Default: page 1, limit 100 per page."""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=500, detail="wiki-articles directory missing")
    
    all_pages = _get_all_pages()
    total = len(all_pages)
    
    if page < 1:
        page = 1
    
    skip = (page - 1) * limit
    paginated = all_pages[skip : skip + limit]
    
    pages = []
    for md in paginated:
        try:
            text = md.read_text(encoding="utf-8")
            pages.append({"path": md.name, "content": text})
        except Exception as e:
            # skip files we can't read
            continue
    
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "count": len(pages),
        "pages": pages
    }


@app.get("/pages/{filename}", response_model=Dict[str, str])
async def get_page(filename: str) -> Dict[str, str]:
    """Return a single page by filename."""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=500, detail="wiki-articles directory missing")
    
    file_path = STATIC_DIR / filename
    
    # Security: prevent directory traversal
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    
    if not str(file_path).startswith(str(STATIC_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    
    try:
        text = file_path.read_text(encoding="utf-8")
        return {"path": filename, "content": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7171)
