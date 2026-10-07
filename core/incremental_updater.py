"""Incremental updates that retry gaps and publish TXT/EPUB together."""
import asyncio
import os
import re
from pathlib import Path
import httpx
from core.book_document import Chapter, read_book, parse_document, defective, render_document
from core.safe_publish import capture_states, publish_outputs
from core.formatters import EpubFormatter
from core.heuristic_catalog import HeuristicCatalogExtractor
from core.universal_engine import UniversalNovelExtractor


def output_paths(file_path):
    base = os.path.splitext(os.path.abspath(file_path))[0]
    return [base + ".txt", base + ".epub"]


def save_book(file_path, header, chapters, title, author, source_url, expected):
    paths = output_paths(file_path)
    with publish_outputs(paths, expected=expected) as staged:
        Path(staged[str(Path(paths[0]).resolve())]).write_text(
            render_document(header, chapters), encoding="utf-8")
        EpubFormatter.export(staged[str(Path(paths[1]).resolve())],
            {"title": title, "author": author},
            [(index, chapter.title, chapter.body) for index, chapter in enumerate(chapters, 1)],
            source_url)
    return paths


class IncrementalNovelUpdater:
    def __init__(self, timeout=12.0, concurrency=15):
        if concurrency < 1:
            raise ValueError("并发数必须大于零。")
        self.timeout = timeout
        self.concurrency = concurrency
        self.catalog_extractor = HeuristicCatalogExtractor(timeout=timeout)
        self.universal_engine = UniversalNovelExtractor(timeout=timeout, min_char_length=350)

    def analyze_local_file(self, file_path):
        title, author, text = read_book(file_path)
        header, chapters = parse_document(text)
        if author == "未知":
            cached = self.universal_engine.source_cache.get(title)
            if cached:
                author = cached.get("author", author)
        last = chapters[-1]
        base = text.rstrip()
        if defective(last.body) and len(chapters) > 1:
            last = chapters[-2]
            base = render_document(header, chapters[:-1]).rstrip()
        return title, author, float(last.number), last.title, base

    async def _catalog(self, title, custom_source_url, author=""):
        def matches(meta, fallback_author=""):
            candidate_title = meta.get("title") or ""
            candidate_author = meta.get("author")
            if not candidate_author or candidate_author == "未知":
                candidate_author = fallback_author or ""
            if candidate_title and candidate_title != "未知小说" and candidate_title.replace("《", "").replace("》", "").strip() != title:
                return False
            if author and author != "未知" and candidate_author and candidate_author != "未知":
                return re.sub(r"\s", "", author) == re.sub(r"\s", "", candidate_author)
            return True
        if custom_source_url:
            meta, chapters = await self.catalog_extractor.discover_catalog(custom_source_url)
            if not matches(meta):
                raise ValueError("指定书源的书名或作者与本地文件不一致，原文件未修改。")
            return custom_source_url, chapters
        cached = self.universal_engine.source_cache.get(title)
        if cached and cached.get("catalog_url"):
            try:
                meta, chapters = await self.catalog_extractor.discover_catalog(cached["catalog_url"])
                if chapters and matches(meta, cached.get("author", "")):
                    return cached["catalog_url"], chapters
            except Exception:
                pass
        candidates = await self.universal_engine.find_authentic_catalog_candidates(title)
        best_url, best = "", []
        for candidate in candidates[:10]:
            try:
                meta, chapters = await self.catalog_extractor.discover_catalog(candidate)
                if matches(meta) and len(chapters) > len(best) and await self.universal_engine.probe_catalog_usability(title, candidate, chapters):
                    best_url, best = candidate, chapters
            except Exception:
                continue
        return best_url, best

    async def update_book(self, file_path, custom_source_url=None):
        expected = capture_states(output_paths(file_path))
        title, author, text = read_book(file_path)
        header, chapters = parse_document(text)
        local = {chapter.number: chapter for chapter in chapters}
        first = min(local)
        source_url, catalog = await self._catalog(title, custom_source_url, author)
        if not catalog:
            print("❌ 未找到有效目录，原文件未修改。")
            return False
        selected = {}
        for index, chapter_title, url, number in catalog:
            number = int(number)
            if number >= first and (number not in local or defective(local[number].body)):
                selected.setdefault(number, (index, chapter_title, url))
        if not selected:
            unresolved = sorted(set(range(first, max(local) + 1)) - set(local)
                                | {number for number, chapter in local.items() if defective(chapter.body)})
            if unresolved:
                print(f"⚠️ 本地仍有缺失或残缺章节 {unresolved}，当前书源未提供对应正文；原文件未修改。")
                return False
            print("✅ 当前书源未发现需要补抓或新增的章节。")
            return True
        semaphore = asyncio.Semaphore(self.concurrency)
        successful, failures = {}, []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True,
                                    headers=self.universal_engine.headers) as client:
            async def fetch(number, info):
                index, chapter_title, url = info
                clean_title = re.sub(r"【.*?】", "", chapter_title).strip()
                _, _, content = await self.universal_engine.fetch_single_chapter(
                    title, index, clean_title, url, semaphore, persist=False, client=client)
                return number, clean_title, content
            for future in asyncio.as_completed([fetch(number, info) for number, info in selected.items()]):
                number, chapter_title, content = await future
                if not defective(content):
                    successful[number] = Chapter(number, chapter_title, content)
                else:
                    failures.append(number)
        if not successful:
            print("❌ 所有目标章节均未抓取完整，原文件未修改；下次执行会重试。")
            return False
        local.update(successful)
        merged = [local[number] for number in sorted(local)]
        save_book(file_path, header, merged, title, author, source_url, expected)
        missing = [number for number in range(first, max(local) + 1) if number not in local]
        remaining = sorted(set(failures + missing)
                           | {number for number, chapter in local.items() if defective(chapter.body)})
        if remaining:
            print(f"⚠️ 部分完成：保存 {len(successful)} 章，仍缺失或不完整 {remaining}；下次续更会重试。")
            return False
        print(f"✅ 续更完成：保存 {len(successful)} 章，TXT/EPUB 已更新，旧版本保存在 .bak。")
        return True
