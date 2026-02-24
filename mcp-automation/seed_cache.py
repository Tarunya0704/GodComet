"""
Figma Cache Seeder
==================
Run this ONCE to pre-warm the Figma file cache before starting the full workflow.
After this succeeds, the workflow will skip the Figma API entirely (7-day TTL).

Usage:
    cd mcp-automation
    python seed_cache.py <figma_url>

Example:
    python seed_cache.py "https://www.figma.com/design/oWK4dPW26jwz4I3dncfu6S/..."
"""

import sys
import os
import json
import time
import re
import requests
from pathlib import Path
from dotenv import load_dotenv

# Load token from mcp-automation/.env
load_dotenv(Path(__file__).parent / ".env")

FIGMA_TOKEN = os.getenv("FIGMA_TOKEN")
if not FIGMA_TOKEN:
    print("[ERROR] FIGMA_TOKEN not found in mcp-automation/.env")
    sys.exit(1)

if len(sys.argv) < 2:
    print("Usage: python seed_cache.py <figma_url>")
    sys.exit(1)

figma_url = sys.argv[1]

# Extract file ID
match = re.search(r'/(?:design|file)/([a-zA-Z0-9]+)', figma_url)
if not match:
    print(f"[ERROR] Cannot extract file ID from: {figma_url}")
    sys.exit(1)

file_id = match.group(1)
cache_dir = Path(__file__).parent / "figma_cache"
cache_dir.mkdir(exist_ok=True)
cache_file = cache_dir / f"{file_id}.json"

# Already cached?
if cache_file.exists():
    age_minutes = int((time.time() - cache_file.stat().st_mtime) / 60)
    age_hours = age_minutes // 60
    if age_hours < 168:  # 7 days
        size_kb = cache_file.stat().st_size // 1024
        print(f"[OK] Already cached (saved {age_hours}h {age_minutes % 60}m ago, {size_kb} KB)")
        print(f"     {cache_file}")
        print()
        print("Cache is fresh -- no API call needed.")
        print("You can run the workflow immediately.")
        sys.exit(0)

# Fetch from API
print(f"[>>] Fetching Figma file: {file_id}")
print(f"     Token: {FIGMA_TOKEN[:8]}...")
print()

headers = {"X-Figma-Token": FIGMA_TOKEN}
url = f"https://api.figma.com/v1/files/{file_id}"

max_retries = 3
wait = 300  # 5 minutes on first retry — enough for Figma's sliding window to drain

for attempt in range(max_retries):
    print(f"   Attempt {attempt + 1}/{max_retries}...")
    resp = requests.get(url, headers=headers, timeout=30)

    if resp.status_code == 200:
        data = resp.json()
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        size_kb = cache_file.stat().st_size // 1024
        file_name = data.get("name", "Unknown")
        pages = len(data.get("document", {}).get("children", []))
        print()
        print("[OK] Cached successfully!")
        print(f"     File name : {file_name}")
        print(f"     Pages     : {pages}")
        print(f"     Size      : {size_kb} KB")
        print(f"     Saved to  : {cache_file}")
        print()
        print("You can now run the workflow -- it will skip the Figma API for 7 days.")
        sys.exit(0)

    elif resp.status_code == 429:
        if attempt < max_retries - 1:
            print(f"   [WAIT] Rate limit hit. Waiting {wait}s...")
            for remaining in range(wait, 0, -10):
                print(f"      {remaining}s remaining...", end="\r", flush=True)
                time.sleep(min(10, remaining))
            print()
            wait *= 2
        else:
            print()
            print("[ERROR] Rate limit exhausted after all retries.")
            print()
            print("Wait 5 minutes, then run this script again:")
            print(f'    python seed_cache.py "{figma_url}"')
            sys.exit(1)

    elif resp.status_code == 403:
        print(f"[ERROR] 403 Forbidden -- check your FIGMA_TOKEN has 'file_content:read' scope")
        print(f"        Response: {resp.text[:200]}")
        sys.exit(1)

    else:
        print(f"[ERROR] Unexpected status {resp.status_code}: {resp.text[:200]}")
        sys.exit(1)
