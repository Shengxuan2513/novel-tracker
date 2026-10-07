"""Chapter cache validated against the current book and chapter identity."""
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from core.parser import extract_chapter_number
from core.book_document import BAD_CONTENT


def chapter_identity(title):
    number = extract_chapter_number(title)[0]
    tail = re.sub(r"^第\s*[0-9〇零一二两三四五六七八九十百千万]+\s*[章节回节篇]", "", title.strip())
    tail = re.sub(r"^Chapter\s*\d+", "", tail, flags=re.I)
    return number, re.sub(r"[\W_]+", "", tail).casefold()


class ChapterStorage:
    def __init__(self, base_storage_dir=None):
        if base_storage_dir is None:
            from core.paths import data_dir
            base_storage_dir = os.path.join(data_dir(), "storage", "books")
        self.base_storage_dir = str(base_storage_dir)
        os.makedirs(self.base_storage_dir, exist_ok=True)

    def _get_book_key(self, book_name, author=""):
        clean = book_name.strip().replace("《", "").replace("》", "")
        author = author.strip() if author and author != "未知" else ""
        identity = clean + ("|" + author if author else "")
        digest = hashlib.md5(identity.encode("utf-8")).hexdigest()[:8]
        return re.sub(r"[^\w\u4e00-\u9fa5]", "_", clean) + "_" + digest

    def get_book_dir(self, book_name, author=""):
        directory = os.path.join(self.base_storage_dir, self._get_book_key(book_name, author))
        os.makedirs(os.path.join(directory, "chapters"), exist_ok=True)
        return directory

    def get_chapters_dir(self, book_name, author=""):
        return os.path.join(self.get_book_dir(book_name, author), "chapters")

    @staticmethod
    def valid(data, title=None, min_chars=100, number=None):
        if not isinstance(data, dict):
            return False
        content = data.get("content", "")
        if not isinstance(content, str) or not isinstance(data.get("title", ""), str):
            return False
        if data.get("complete") is not True or len(re.sub(r"\s", "", content)) < min_chars:
            return False
        if any(marker in content for marker in BAD_CONTENT):
            return False
        if title is not None and chapter_identity(data.get("title", "")) != chapter_identity(title):
            return False
        if number is not None and extract_chapter_number(data.get("title", ""))[0] != number:
            return False
        return True

    def get_cached_indices(self, book_name, author="", expected_chapters=None, min_chars=100):
        expected = {row[0]: row for row in expected_chapters} if expected_chapters is not None else None
        indices = set()
        for row in self.load_all_chapters(book_name, author):
            index = row[0]
            data = self.get_chapter(book_name, index, author)
            if data is None or (expected is not None and index not in expected):
                continue
            wanted = expected[index] if expected is not None else None
            if self.valid(data, title=wanted[1] if wanted else None,
                          number=wanted[3] if wanted else None, min_chars=min_chars):
                indices.add(index)
        return indices

    def get_chapter(self, book_name, index, author=""):
        path = os.path.join(self.get_chapters_dir(book_name, author), f"{index:05d}.json")
        try:
            with open(path, encoding="utf-8") as file:
                data = json.load(file)
                return data if isinstance(data, dict) else None
        except (FileNotFoundError, ValueError):
            return None

    def save_chapter(self, book_name, index, title, content, url="", source_domain="",
                     complete=True, author=""):
        directory = self.get_chapters_dir(book_name, author)
        path = os.path.join(directory, f"{index:05d}.json")
        payload = {"index": index, "title": title.strip(), "content": content,
                   "url": url.strip(), "source_domain": source_domain.strip(),
                   "complete": complete, "author": author, "char_count": len(content),
                   "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        descriptor, temporary = tempfile.mkstemp(prefix=".chapter-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def load_all_chapters(self, book_name, author=""):
        chapters = []
        directory = self.get_chapters_dir(book_name, author)
        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".json"):
                continue
            try:
                index = int(filename.split(".")[0])
                data = self.get_chapter(book_name, index, author)
                if data is not None:
                    chapters.append((index, data.get("title", ""), data.get("content", "")))
            except (ValueError, OSError):
                continue
        return sorted(chapters)

    def clear_cache(self, book_name, author=""):
        import shutil
        shutil.rmtree(self.get_book_dir(book_name, author), ignore_errors=True)
