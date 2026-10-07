"""
JSON Document Formatter.
Exports structured novel data for API integration and programmatic processing.
"""

import json
import os
from typing import List, Tuple, Dict


from core.safe_publish import atomic_export


class JsonFormatter:
    @staticmethod
    @atomic_export
    def export(
        output_path: str,
        book_meta: Dict[str, str],
        chapters: List[Tuple[int, str, str]],
        source_url: str = ""
    ) -> str:
        """
        Exports chapters to a structured JSON file.
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        chapter_list = []
        for idx, title, content in chapters:
            paragraphs = [p.strip() for p in content.strip().split("\n") if p.strip()]
            # First line is chapter title
            body_paragraphs = paragraphs[1:] if len(paragraphs) > 1 and paragraphs[0] == title else paragraphs
            chapter_list.append({
                "index": idx,
                "title": title,
                "paragraphs": body_paragraphs,
                "character_count": sum(len(p) for p in body_paragraphs)
            })

        data = {
            "book_title": book_meta.get("title", "未命名小说"),
            "author": book_meta.get("author", "未知"),
            "description": book_meta.get("description", ""),
            "source_url": source_url,
            "total_chapters": len(chapters),
            "total_characters": sum(c["character_count"] for c in chapter_list),
            "chapters": chapter_list
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return output_path
