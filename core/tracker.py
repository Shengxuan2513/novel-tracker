"""
Watchlist and state manager for followed novels.
Persists tracked novels and their latest known chapters to a JSON file.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple


class NovelTracker:
    def __init__(self, storage_path: Optional[str] = None):
        if storage_path is None:
            # Default to watchlist.json in current work directory
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.storage_path = os.path.join(base_dir, "watchlist.json")
        else:
            self.storage_path = storage_path
            
        self.data: Dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        """Load watchlist from disk."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}
        else:
            self.data = {}

    def save(self) -> None:
        """Save watchlist to disk."""
        os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
        with open(self.storage_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def get_all(self) -> List[dict]:
        """Return all tracked novels as a list."""
        return list(self.data.values())

    def get_book(self, book_name: str) -> Optional[dict]:
        """Get a specific tracked novel."""
        return self.data.get(book_name.strip())

    def add_book(
        self,
        book_name: str,
        author: str = "",
        latest_chapter: str = "",
        latest_chapter_num: float = 0.0,
        latest_chapter_url: str = "",
        source_name: str = "",
        official_chapter: str = "",
        official_chapter_num: float = 0.0,
        official_source: str = "",
        official_url: str = "",
        official_time: str = "",
        crawlable_chapter: str = "",
        crawlable_chapter_num: float = 0.0,
        crawlable_source: str = "",
        catalog_url: str = ""
    ) -> dict:
        """
        Add or update a book in the watchlist with dual-progress tracking.
        """
        name = book_name.strip()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Resolve fields
        c_chap = crawlable_chapter or latest_chapter
        c_num = crawlable_chapter_num or latest_chapter_num
        c_src = crawlable_source or source_name or "全网聚合"
        
        o_chap = official_chapter or c_chap
        o_num = official_chapter_num or c_num
        o_src = official_source or "官方首发站"

        gap = max(0, int(o_num - c_num)) if (o_num > 0 and c_num > 0) else 0

        book_entry = {
            "book_name": name,
            "author": author.strip() if author else "未知",
            "last_known_chapter": c_chap,
            "last_known_chapter_num": c_num,
            "last_known_chapter_url": latest_chapter_url,
            "source_name": c_src,
            "official_chapter": o_chap,
            "official_chapter_num": o_num,
            "official_source": o_src,
            "official_url": official_url,
            "official_time": official_time or "正版连载中",
            "crawlable_chapter": c_chap,
            "crawlable_chapter_num": c_num,
            "crawlable_source": c_src,
            "catalog_url": catalog_url,
            "gap_chapters": gap,
            "added_at": self.data.get(name, {}).get("added_at", now_str),
            "updated_at": now_str,
            "last_checked_at": now_str
        }
        self.data[name] = book_entry
        self.save()
        return book_entry

    def remove_book(self, book_name: str) -> bool:
        """Remove a book from the watchlist."""
        name = book_name.strip()
        if name in self.data:
            del self.data[name]
            self.save()
            return True
        return False

    def check_and_update(
        self,
        book_name: str,
        new_chapter_title: str = "",
        new_chapter_num: float = 0.0,
        new_chapter_url: str = "",
        source_name: str = "",
        official_chapter: str = "",
        official_chapter_num: float = 0.0,
        official_source: str = "",
        official_url: str = "",
        official_time: str = "",
        crawlable_chapter: str = "",
        crawlable_chapter_num: float = 0.0,
        crawlable_source: str = "",
        catalog_url: str = ""
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if incoming chapter is newer than recorded.
        Returns:
            (is_updated: bool, old_chapter_title: Optional[str])
        """
        name = book_name.strip()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if name not in self.data:
            self.add_book(
                book_name=name,
                latest_chapter=new_chapter_title,
                latest_chapter_num=new_chapter_num,
                latest_chapter_url=new_chapter_url,
                source_name=source_name,
                official_chapter=official_chapter,
                official_chapter_num=official_chapter_num,
                official_source=official_source,
                official_url=official_url,
                official_time=official_time,
                crawlable_chapter=crawlable_chapter,
                crawlable_chapter_num=crawlable_chapter_num,
                crawlable_source=crawlable_source,
                catalog_url=catalog_url
            )
            return False, None

        current = self.data[name]
        current["last_checked_at"] = now_str
        old_title = current.get("last_known_chapter", "")
        old_num = current.get("last_known_chapter_num", 0.0)

        # Update crawlable
        c_chap = crawlable_chapter or new_chapter_title
        c_num = crawlable_chapter_num or new_chapter_num
        c_src = crawlable_source or source_name

        if c_chap:
            if c_num > old_num or not old_title:
                current["last_known_chapter"] = c_chap
                current["last_known_chapter_num"] = c_num
                current["crawlable_chapter"] = c_chap
                current["crawlable_chapter_num"] = c_num
                if new_chapter_url:
                    current["last_known_chapter_url"] = new_chapter_url
                if c_src:
                    current["source_name"] = c_src
                    current["crawlable_source"] = c_src
                current["updated_at"] = now_str

        # Update official
        if official_chapter:
            current["official_chapter"] = official_chapter
            current["official_chapter_num"] = official_chapter_num
            if official_source:
                current["official_source"] = official_source
            if official_url:
                current["official_url"] = official_url
            if official_time:
                current["official_time"] = official_time

        if catalog_url:
            current["catalog_url"] = catalog_url

        # Recalculate gap
        o_n = current.get("official_chapter_num", 0.0)
        c_n = current.get("crawlable_chapter_num", current.get("last_known_chapter_num", 0.0))
        current["gap_chapters"] = max(0, int(o_n - c_n)) if (o_n > 0 and c_n > 0) else 0

        self.save()
        return (c_num > old_num and old_num > 0), old_title
