"""
TXT Document Formatter.
Merges structured chapters into a standardized Chinese plain text file.
"""

import os
from typing import List, Tuple, Dict


from core.safe_publish import atomic_export


class TxtFormatter:
    @staticmethod
    @atomic_export
    def export(
        output_path: str,
        book_meta: Dict[str, str],
        chapters: List[Tuple[int, str, str]],
        source_url: str = ""
    ) -> str:
        """
        Exports chapters to a formatted TXT file.
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        title = book_meta.get("title", "未命名小说")
        author = book_meta.get("author", "未知")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(f"《{title}》\n")
            f.write(f"作者：{author}\n")
            label = "未完整，含暂缺章节" if book_meta.get("complete") is False else "正文导出版"
            f.write(f"【{label}】共 {len(chapters)} 章\n")
            if source_url:
                f.write(f"提取来源：{source_url}\n")
            f.write("=" * 60 + "\n\n")

            for idx, title, content in chapters:
                clean_content = content.strip()
                if not clean_content.startswith(title):
                    f.write(f"{title}\n\n")
                f.write(clean_content + "\n\n")

        return output_path
