"""Minimal API for serving the generated markdown pages.

Read-only endpoints are intended for production (Oracle VM).  Set
ENABLE_REGENERATE=true only on a machine that can run the LLM agent.

Usage:

    pip install -r requirements.txt
    python api_server.py

Environment variables:
    STATIC_DIR          Directory of .md files (default: /home/anandks/wiki-articles)
    ALLOWED_ORIGINS     Comma-separated CORS origins (default: https://www.bheri.in)
    API_KEY             If set, require X-API-Key header on all routes except /health
    ENABLE_REGENERATE   Set to true to expose POST /pages/{filename}/regenerate
    PORT                Uvicorn port when run directly (default: 7171)
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pathlib import Path
from typing import Dict, Any
import asyncio
import os
import sys

app = FastAPI(title="Sanskrit Wiki API")

STATIC_DIR = Path(os.getenv("STATIC_DIR", "/home/anandks/wiki-articles"))
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "https://www.bheri.in").split(",")
    if origin.strip()
]
API_KEY = os.getenv("API_KEY", "")
ENABLE_REGENERATE = os.getenv("ENABLE_REGENERATE", "false").lower() in {
    "1",
    "true",
    "yes",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_cached_pages = None
_regen_in_progress: set = set()


@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if not API_KEY or request.url.path == "/health" or request.method == "OPTIONS":
        return await call_next(request)

    if request.headers.get("X-API-Key") != API_KEY:
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    return await call_next(request)


def _resolve_page_path(filename: str) -> Path:
    """Resolve a filename inside STATIC_DIR and block directory traversal."""
    if not filename.endswith(".md") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = (STATIC_DIR / filename).resolve()
    static_root = STATIC_DIR.resolve()

    if not file_path.is_relative_to(static_root):
        raise HTTPException(status_code=403, detail="Access denied")

    return file_path


def _get_all_pages():
    """Get all markdown files from the static directory (cached)."""
    global _cached_pages
    if _cached_pages is not None:
        return _cached_pages

    if not STATIC_DIR.exists():
        return []

    _cached_pages = sorted(STATIC_DIR.glob("*.md"))
    return _cached_pages


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


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
        "pages": [{"path": md.name} for md in paginated],
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
        except Exception:
            continue

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "count": len(pages),
        "pages": pages,
    }


@app.get("/pages/{filename}", response_model=Dict[str, str])
async def get_page(filename: str) -> Dict[str, str]:
    """Return a single page by filename."""
    if not STATIC_DIR.exists():
        raise HTTPException(status_code=500, detail="wiki-articles directory missing")

    file_path = _resolve_page_path(filename)

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        text = file_path.read_text(encoding="utf-8")
        return {"path": filename, "content": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")


if ENABLE_REGENERATE:

    @app.post("/pages/{filename}/regenerate", response_model=Dict[str, Any])
    async def regenerate_page(filename: str) -> Dict[str, Any]:
        """Regenerate a single wiki article by re-running the LLM agent."""
        global _cached_pages

        if not STATIC_DIR.exists():
            raise HTTPException(status_code=500, detail="wiki-articles directory missing")

        file_path = _resolve_page_path(filename)

        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(status_code=404, detail="Page not found")

        if filename in _regen_in_progress:
            raise HTTPException(
                status_code=409,
                detail="Regeneration already in progress for this page",
            )

        topic = filename[:-3].replace("_", " ")

        _regen_in_progress.add(filename)
        try:
            loop = asyncio.get_event_loop()
            article_text = await loop.run_in_executor(
                None,
                lambda: _run_generation(topic),
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")
        finally:
            _regen_in_progress.discard(filename)

        if not article_text:
            raise HTTPException(status_code=500, detail="Agent returned empty content")

        file_path.write_text(article_text, encoding="utf-8")
        _cached_pages = None

        return {"path": filename, "content": article_text, "regenerated": True}


def _run_generation(topic: str) -> str:
    """Blocking helper: import and call generate_for_topic from generate_static_pages."""
    project_root = str(Path(__file__).parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    from generate_static_pages import (
        generate_for_topic,
        filter_unused_references,
        renumber_references,
    )

    article = generate_for_topic(topic)
    if not article:
        return article

    article = filter_unused_references(article)
    article = renumber_references(article)
    return article


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "7171"))
    uvicorn.run(app, host="0.0.0.0", port=port)
