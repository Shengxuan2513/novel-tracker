"""Audit local chapters and insert missing chapters before safe publication."""
import asyncio
import httpx
from core.book_document import Chapter, read_book, parse_document, defective
from core.safe_publish import capture_states
from core.incremental_updater import IncrementalNovelUpdater, output_paths, save_book


class NovelHealthAuditor:
    def __init__(self, min_char_threshold=350):
        self.min_char_threshold = min_char_threshold

    def audit_file(self, file_path):
        title, author, text = read_book(file_path)
        _, chapters = parse_document(text)
        defects = []
        for index, chapter in enumerate(chapters):
            if index:
                previous = chapters[index - 1].number
                if chapter.number <= previous:
                    raise ValueError("章节顺序异常，原文件未修改。")
                for number in range(previous + 1, chapter.number):
                    defects.append({"type": "GAP_MISSING", "index": index,
                                    "chapter_num": number, "title": f"第{number}章",
                                    "reason": f"缺失第 {number} 章"})
            if defective(chapter.body, self.min_char_threshold):
                defects.append({"type": "CONTENT_DEFECT", "index": index,
                                "chapter_num": chapter.number, "title": chapter.title,
                                "reason": "正文过短、残缺或包含导流/污染内容"})
        return defects, title, author, text

    async def repair_file(self, file_path, source_url=None):
        expected = capture_states(output_paths(file_path))
        defects, title, author, text = self.audit_file(file_path)
        if not defects:
            print("✅ 未发现质量缺陷，原文件未修改。")
            return {"repaired": 0, "remaining": 0}
        header, chapters = parse_document(text)
        local = {chapter.number: chapter for chapter in chapters}
        updater = IncrementalNovelUpdater()
        updater.universal_engine.pipeline.min_char_length = self.min_char_threshold
        source_url, catalog = await updater._catalog(title, source_url, author)
        targets = {int(number): (index, chapter_title, url)
                   for index, chapter_title, url, number in catalog}
        repaired = 0
        semaphore = asyncio.Semaphore(updater.concurrency)
        async with httpx.AsyncClient(timeout=updater.timeout, follow_redirects=True,
                                    headers=updater.universal_engine.headers) as client:
            for defect in defects:
                number = defect["chapter_num"]
                if number not in targets:
                    print(f"⚠️ 当前书源未收录第 {number} 章，保留原内容。")
                    continue
                index, chapter_title, url = targets[number]
                _, _, body = await updater.universal_engine.fetch_single_chapter(
                    title, index, chapter_title, url, semaphore, persist=False, client=client)
                if not defective(body, self.min_char_threshold):
                    local[number] = Chapter(number, chapter_title, body)
                    repaired += 1
        if repaired:
            merged = [local[number] for number in sorted(local)]
            save_book(file_path, header, merged, title, author, source_url, expected)
            remaining = len(self.audit_file(output_paths(file_path)[0])[0])
        else:
            remaining = len(defects)
        print(f"{'✅' if remaining == 0 else '⚠️'} 修复 {repaired} 处，剩余 {remaining} 处"
              + ("；未完成部分可再次执行修复。" if remaining else "；TXT/EPUB 已同步更新。"))
        return {"repaired": repaired, "remaining": remaining}
