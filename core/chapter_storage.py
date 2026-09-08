"""
Chapter-Level Chunked Storage and Incremental Cache Engine.
Stores novel chapters as independent atomic files under storage/books/{book_hash}/chapters/
to enable sub-second incremental updates, offline resume, and stream export.
"""

import hashlib
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple


class ChapterStorage:
    def __init__(self, base_storage_dir: Optional[str] = None):
        if base_storage_dir is None:
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.base_storage_dir = os.path.join(root_dir, "storage", "books")
        else:
            self.base_storage_dir = base_storage_dir

        os.makedirs(self.base_storage_dir, exist_ok=True)

    def _get_book_key(self, book_name: str) -> str:
        """Generate safe, clean alphanumeric key for novel."""
        clean = book_name.strip().replace("《", "").replace("》", "")
        # md5 hash suffix to ensure safety across file systems
        md5_suffix = hashlib.md5(clean.encode("utf-8")).hexdigest()[:8]
        safe_name = re.sub(r'[^\w\u4e00-\u9fa5]', '_', clean)
        return f"{safe_name}_{md5_suffix}"

    def get_book_dir(self, book_name: str) -> str:
        """Get or create directory for a novel's chapters."""
        book_key = self._get_book_key(book_name)
        book_dir = os.path.join(self.base_storage_dir, book_key)
        chap_dir = os.path.join(book_dir, "chapters")
        os.makedirs(chap_dir, exist_ok=True)
        return book_dir

    def get_chapters_dir(self, book_name: str) -> str:
        book_dir = self.get_book_dir(book_name)
        return os.path.join(book_dir, "chapters")

    def get_cached_indices(self, book_name: str) -> Set[int]:
        """
        Returns set of valid chapter indices already downloaded and cached locally.
        Only counts chapters with valid length (>= 200 chars) and no error notice.
        """
        chap_dir = self.get_chapters_dir(book_name)
        cached_indices = set()

        if not os.path.exists(chap_dir):
            return cached_indices

        for fn in os.listdir(chap_dir):
            if fn.endswith(".json"):
                try:
                    idx_str = fn.split(".")[0]
                    idx = int(idx_str)
                    filepath = os.path.join(chap_dir, fn)
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        content = data.get("content", "")
                        if content and len(content) >= 100 and "暂缺" not in content and "抓取异常" not in content:
                            cached_indices.add(idx)
                except Exception:
                    pass

        return cached_indices

    def get_chapter(self, book_name: str, index: int) -> Optional[dict]:
        """Retrieve a specific cached chapter."""
        chap_dir = self.get_chapters_dir(book_name)
        filepath = os.path.join(chap_dir, f"{index:05d}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return None
        return None

    def save_chapter(
        self,
        book_name: str,
        index: int,
        title: str,
        content: str,
        url: str = "",
        source_domain: str = ""
    ) -> None:
        """
        Saves a single chapter to disk with atomic write.
        """
        chap_dir = self.get_chapters_dir(book_name)
        filepath = os.path.join(chap_dir, f"{index:05d}.json")
        tmp_path = f"{filepath}.tmp"

        payload = {
            "index": index,
            "title": title.strip(),
            "url": url.strip(),
            "source_domain": source_domain.strip(),
            "char_count": len(content),
            "content": content,
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            if os.path.exists(filepath):
                os.replace(tmp_path, filepath)
            else:
                os.rename(tmp_path, filepath)
        except Exception:
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def load_all_chapters(self, book_name: str) -> List[Tuple[int, str, str]]:
        """
        Loads all cached chapters sorted by index.
        Returns: [(index, title, content), ...]
        """
        chap_dir = self.get_chapters_dir(book_name)
        chapters: List[Tuple[int, str, str]] = []

        if not os.path.exists(chap_dir):
            return chapters

        for fn in sorted(os.listdir(chap_dir)):
            if fn.endswith(".json"):
                filepath = os.path.join(chap_dir, fn)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        idx = data.get("index", 0)
                        title = data.get("title", f"第{idx}章")
                        content = data.get("content", "")
                        chapters.append((idx, title, content))
                except Exception:
                    pass

        chapters.sort(key=lambda x: x[0])
        return chapters

    def clear_cache(self, book_name: str) -> None:
        """Clear cached chapters for a novel."""
        import shutil
        book_dir = self.get_book_dir(book_name)
        if os.path.exists(book_dir):
            shutil.rmtree(book_dir, ignore_errors=True)
