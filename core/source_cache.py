"""
Persistent Source Cache and URL Router.
Caches verified authentic catalog URLs for novels to enable sub-second direct extractions
and prevent regression to truncated/preview search results.
"""

import json
import os
from datetime import datetime
from typing import Dict, Optional


class SourceCache:
    def __init__(self, storage_path: Optional[str] = None):
        if storage_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.storage_path = os.path.join(base_dir, "source_cache.json")
        else:
            self.storage_path = storage_path

        self.data: Dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        """Load source cache from disk."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}
        else:
            self.data = {}

    def save(self) -> None:
        """Save source cache to disk safely with atomic replace."""
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        tmp_path = f"{self.storage_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            if os.path.exists(self.storage_path):
                os.replace(tmp_path, self.storage_path)
            else:
                os.rename(tmp_path, self.storage_path)
        except Exception:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get(self, book_name: str) -> Optional[dict]:
        """Get cached source info for a novel."""
        clean_name = book_name.strip().replace("《", "").replace("》", "")
        return self.data.get(clean_name)

    def set(
        self,
        book_name: str,
        catalog_url: str,
        total_chapters: int,
        last_chapter_title: str = "",
        author: str = "未知",
        source_name: str = "全网聚合",
        success_rate: float = 100.0,
        status: str = "healthy"
    ) -> dict:
        """
        Record or update verified catalog URL for a novel with health metadata.
        """
        clean_name = book_name.strip().replace("《", "").replace("》", "")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        entry = {
            "book_name": clean_name,
            "catalog_url": catalog_url.strip(),
            "total_chapters": total_chapters,
            "last_chapter_title": last_chapter_title,
            "author": author,
            "source_name": source_name,
            "success_rate": round(success_rate, 1),
            "status": status,
            "updated_at": now_str
        }
        self.data[clean_name] = entry
        self.save()
        return entry

    def remove(self, book_name: str) -> bool:
        """Remove a cached novel source."""
        clean_name = book_name.strip().replace("《", "").replace("》", "")
        if clean_name in self.data:
            del self.data[clean_name]
            self.save()
            return True
        return False

    def get_all(self) -> Dict[str, dict]:
        """Return all cached sources."""
        return self.data
