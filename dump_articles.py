#!/usr/bin/env python3
"""Dump all articles from the API server to a JSON file."""

import requests
import json
import sys

API_URL = "http://localhost:7171/pages"
OUTPUT_FILE = "articles_dump.json"
ARTICLES_PER_PAGE = 500  # larger batch for efficiency

def dump_all_articles():
    """Fetch all articles from the API and save to a JSON file."""
    all_articles = []
    page = 1
    
    while True:
        print(f"Fetching page {page}...", file=sys.stderr)
        try:
            response = requests.get(API_URL, params={"page": page, "limit": ARTICLES_PER_PAGE})
            response.raise_for_status()
            data = response.json()
            
            articles = data.get("pages", [])
            if not articles:
                break
            
            all_articles.extend(articles)
            print(f"  Got {len(articles)} articles (total: {len(all_articles)})", file=sys.stderr)
            
            # Check if we've got all articles
            if len(all_articles) >= data.get("total", 0):
                break
            
            page += 1
        except Exception as e:
            print(f"Error fetching page {page}: {e}", file=sys.stderr)
            break
    
    # Save to file
    print(f"\nSaving {len(all_articles)} articles to {OUTPUT_FILE}...", file=sys.stderr)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)
    
    print(f"Done! Saved to {OUTPUT_FILE}", file=sys.stderr)
    print(f"Total articles: {len(all_articles)}")

if __name__ == "__main__":
    dump_all_articles()
