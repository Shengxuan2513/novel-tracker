"""
Incremental Novel Updater (CLI Entry).
Detects the latest chapter in an existing local novel file (.txt or .epub),
probes the freshest authentic catalog, fetches only new chapters, and merges them seamlessly.

Usage:
    python scripts/incremental_updater.py <path_to_txt_or_epub>
"""

import argparse
import asyncio
import os
import sys

if sys.platform.startswith("win") and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.incremental_updater import IncrementalNovelUpdater


def main():
    parser = argparse.ArgumentParser(description="Incremental Novel Updater for local novel files.")
    parser.add_argument("file", help="Path to local novel file (.txt or .epub)")
    parser.add_argument("-s", "--source", help="Custom catalog URL to crawl from", default=None)
    parser.add_argument("-c", "--concurrency", type=int, default=15, help="Concurrency worker count (default: 15)")
    args = parser.parse_args()

    updater = IncrementalNovelUpdater(concurrency=args.concurrency)
    asyncio.run(updater.update_book(args.file, custom_source_url=args.source))


if __name__ == "__main__":
    main()
