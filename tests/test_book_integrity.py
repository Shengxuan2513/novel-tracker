"""Regression tests for missing chapters, publication failures and pagination."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from bs4 import BeautifulSoup

from core.book_document import parse_document, read_book
from core.chapter_fetcher import fetch_complete_chapter
from core.chapter_storage import ChapterStorage
from core.exceptions import DataIncompleteError
from core.formatters import EpubFormatter, TxtFormatter
from core.incremental_updater import IncrementalNovelUpdater, output_paths, save_book
from core.book_health_auditor import NovelHealthAuditor
from core.safe_publish import capture_states, publish_outputs, ConcurrentBookChange
from core.universal_engine import UniversalNovelExtractor
from core.url_classifier import InputType

BODY = "这是完整的小说正文，主角循着山道来到城门前。" * 30
REAL_CLIENT = httpx.AsyncClient


def extractor():
    return SimpleNamespace(extract_article_text=lambda html, url="":
                           BeautifulSoup(html, "html.parser").select_one("#content").get_text("\n"))


def html(number, text=BODY, next_url=None):
    link = f'<a href="{next_url}">下一页</a>' if next_url else ""
    return f'<h1>第{number}章</h1><div id="content">{text}</div>{link}'


class TestPublication(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_generation_failure_keeps_both_originals(self):
        paths = [self.root / "book.txt", self.root / "book.epub"]
        for path in paths:
            path.write_bytes(b"original")
        with self.assertRaises(RuntimeError):
            with publish_outputs(paths) as staged:
                Path(staged[str(paths[0])]).write_text("new", encoding="utf-8")
                raise RuntimeError("EPUB generation failed")
        self.assertTrue(all(path.read_bytes() == b"original" for path in paths))
        self.assertFalse(list(self.root.glob(".novel-stage-*")))

    def test_second_publish_failure_rolls_back_first(self):
        paths = [self.root / "one.txt", self.root / "two.txt"]
        for path in paths:
            path.write_text("old", encoding="utf-8")
        replace = os.replace
        def fail_second(source, target):
            if Path(target) == paths[1] and Path(source).name.startswith(".novel-stage-"):
                raise OSError("simulated disk failure")
            return replace(source, target)
        with self.assertRaises(OSError), patch("core.safe_publish.os.replace", side_effect=fail_second):
            with publish_outputs(paths) as staged:
                for target in paths:
                    Path(staged[str(target)]).write_text("new", encoding="utf-8")
        self.assertTrue(all(path.read_text() == "old" for path in paths))
        self.assertTrue(all(Path(str(path) + ".bak").read_text() == "old" for path in paths))

    def test_concurrent_update_is_not_overwritten(self):
        path = self.root / "book.txt"
        path.write_text("old", encoding="utf-8")
        expected = capture_states([path])
        with self.assertRaises(ConcurrentBookChange):
            with publish_outputs([path], expected=expected) as staged:
                Path(staged[str(path)]).write_text("stale task", encoding="utf-8")
                path.write_text("another task", encoding="utf-8")
        self.assertEqual(path.read_text(), "another task")

    def test_invalid_epub_preserves_previous_file(self):
        path = self.root / "book.epub"
        path.write_bytes(b"original")
        with self.assertRaises(Exception):
            with publish_outputs([path]) as staged:
                Path(staged[str(path)]).write_bytes(b"not a zip")
        self.assertEqual(path.read_bytes(), b"original")

    def test_standalone_formatter_keeps_backup(self):
        path = self.root / "book.txt"
        path.write_text("old", encoding="utf-8")
        TxtFormatter.export(str(path), {"title": "测试"}, [(1, "第1章", BODY)])
        self.assertEqual(Path(str(path) + ".bak").read_text(), "old")
        self.assertIn(BODY, path.read_text(encoding="utf-8"))

    def test_epub_read_uses_spine_without_creating_txt(self):
        path = self.root / "book.epub"
        EpubFormatter.export(str(path), {"title": "测试", "author": "作者"},
                             [(1, "第一章", BODY), (2, "第二章", BODY)])
        title, author, text = read_book(str(path))
        _, chapters = parse_document(text)
        self.assertEqual([chapter.number for chapter in chapters], [1, 2])
        self.assertEqual(author, "作者")
        self.assertFalse(path.with_suffix(".txt").exists())

    def test_parser_keeps_first_chapter_at_start_and_chinese_numbers(self):
        header, chapters = parse_document("第一章 开始\n\n正文\n\n第二章 后续\n\n正文")
        self.assertEqual(header, "")
        self.assertEqual([chapter.number for chapter in chapters], [1, 2])

    def test_parser_rejects_duplicate_chapters(self):
        with self.assertRaises(ValueError):
            parse_document("第1章\n正文\n第1章\n正文")

    def test_range_filename_does_not_change_book_identity(self):
        path = self.root / "《测试》（章节范围1-2）.txt"
        path.write_text("《测试》\n作者：作者\n第1章\n正文", encoding="utf-8")
        self.assertEqual(read_book(str(path))[0], "测试")


class TestPagination(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, responses, **kwargs):
        def respond(request):
            status, content = responses[request.url.path]
            return httpx.Response(status, text=content)
        async with REAL_CLIENT(transport=httpx.MockTransport(respond)) as client:
            return await fetch_complete_chapter(client, "https://books.test/1.html", "第1章",
                                                extractor(), min_chars=200, **kwargs)

    async def test_all_subpages_are_stitched(self):
        text = await self.fetch({"/1.html": (200, html(1, "第一页正文" * 40, "1_2.html")),
                                 "/1_2.html": (200, html(1, "第二页正文" * 40))})
        self.assertIn("第一页正文", text)
        self.assertIn("第二页正文", text)

    async def test_short_subpage_is_allowed_when_combined_body_is_long(self):
        text = await self.fetch({"/1.html": (200, html(1, "第一页正文" * 20, "1_2.html")),
                                 "/1_2.html": (200, html(1, "第二页正文" * 25))})
        self.assertIn("第二页正文", text)

    async def test_tiny_last_page_is_kept(self):
        text = await self.fetch({"/1.html": (200, html(1, BODY, "1_2.html")),
                                 "/1_2.html": (200, html(1, "最后一句正文。"))})
        self.assertIn("最后一句正文。", text)

    async def test_failed_second_page_does_not_return_first(self):
        with self.assertRaises(httpx.HTTPStatusError):
            await self.fetch({"/1.html": (200, html(1, next_url="1_2.html")),
                              "/1_2.html": (503, "unavailable")})

    async def test_cycle_is_rejected(self):
        with self.assertRaises(DataIncompleteError):
            await self.fetch({"/1.html": (200, html(1, "第一页正文" * 40, "1_2.html")),
                              "/1_2.html": (200, html(1, "第二页正文" * 40, "1.html"))})

    async def test_other_chapter_is_rejected(self):
        with self.assertRaises(DataIncompleteError):
            await self.fetch({"/1.html": (200, html(1, next_url="2.html")),
                              "/2.html": (200, html(2))})

    async def test_limit_with_remaining_page_is_incomplete(self):
        with self.assertRaises(DataIncompleteError):
            await self.fetch({"/1.html": (200, html(1, next_url="1_2.html"))}, max_pages=1)

    async def test_duplicate_page_body_is_rejected(self):
        with self.assertRaises(DataIncompleteError):
            await self.fetch({"/1.html": (200, html(1, next_url="1_2.html")),
                              "/1_2.html": (200, html(1))})

    async def test_unverified_next_chapter_without_heading_is_rejected(self):
        with self.assertRaises(DataIncompleteError):
            await self.fetch({"/1.html": (200, html(1, next_url="2.html")),
                              "/2.html": (200, f'<div id="content">{BODY}</div>')})

    async def test_failure_is_not_cached_and_next_attempt_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = UniversalNovelExtractor(output_dir=directory, min_char_length=200)
            engine.storage = ChapterStorage(os.path.join(directory, "cache"))
            engine.extractor = extractor()
            engine.router.fallback_route = AsyncMock(return_value=(None, ""))
            failed = True
            def respond(request):
                if request.url.path == "/1.html":
                    return httpx.Response(200, text=html(1, "第一页正文" * 50, "1_2.html"))
                return httpx.Response(503 if failed else 200,
                                      text=html(1, "第二页正文" * 50))
            async with REAL_CLIENT(transport=httpx.MockTransport(respond)) as client:
                with patch("core.universal_engine.asyncio.sleep", new=AsyncMock()):
                    result = await engine.fetch_single_chapter("测试", 1, "第1章", "https://books.test/1.html",
                                                              asyncio.Semaphore(1), client=client)
                self.assertIn("暂缺", result[2])
                self.assertIsNone(engine.storage.get_chapter("测试", 1))
                failed = False
                result = await engine.fetch_single_chapter("测试", 1, "第1章", "https://books.test/1.html",
                                                          asyncio.Semaphore(1), client=client)
                self.assertIn("第二页正文", result[2])
                self.assertTrue(engine.storage.get_chapter("测试", 1)["complete"])


class TestUpdateAndRepair(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "《测试小说》.txt"
        self.updater = IncrementalNovelUpdater()
        self.updater.universal_engine.fetch_single_chapter = AsyncMock()

    def tearDown(self):
        self.directory.cleanup()

    def write(self, numbers):
        self.path.write_text("作者：测试\n\n" + "\n\n".join(
            f"第{number}章\n\n{BODY}" for number in numbers), encoding="utf-8")

    def catalog(self, numbers):
        self.updater._catalog = AsyncMock(return_value=("https://books.test/catalog", [
            (number, f"第{number}章", f"https://books.test/{number}.html", float(number))
            for number in numbers]))

    async def test_failed_middle_chapter_is_retried_after_later_success(self):
        self.write([100])
        self.catalog([100, 101, 102])
        async def fetch(name, index, title, *args, **kwargs):
            return index, title, "【暂缺】" if index == 101 else BODY
        self.updater.universal_engine.fetch_single_chapter.side_effect = fetch
        self.assertFalse(await self.updater.update_book(str(self.path)))
        self.assertEqual([chapter.number for chapter in parse_document(self.path.read_text(encoding="utf-8"))[1]], [100, 102])
        self.updater.universal_engine.fetch_single_chapter.reset_mock()
        self.updater.universal_engine.fetch_single_chapter.side_effect = lambda name, index, title, *a, **kw: (index, title, BODY)
        self.assertTrue(await self.updater.update_book(str(self.path)))
        self.assertEqual(self.updater.universal_engine.fetch_single_chapter.call_count, 1)
        self.assertEqual([chapter.number for chapter in parse_document(self.path.read_text(encoding="utf-8"))[1]], [100, 101, 102])
        self.assertTrue(await self.updater.update_book(str(self.path)))
        self.assertEqual(self.updater.universal_engine.fetch_single_chapter.call_count, 1)

    async def test_all_fetches_fail_original_file_is_kept(self):
        self.write([1])
        original = self.path.read_bytes()
        self.catalog([1, 2])
        self.updater.universal_engine.fetch_single_chapter.return_value = (2, "第2章", "【暂缺】")
        self.assertFalse(await self.updater.update_book(str(self.path)))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertFalse(self.path.with_suffix(".epub").exists())

    async def test_epub_generation_error_keeps_original_txt(self):
        self.write([1])
        original = self.path.read_bytes()
        self.catalog([1, 2])
        self.updater.universal_engine.fetch_single_chapter.return_value = (2, "第2章", BODY)
        with patch("core.incremental_updater.EpubFormatter.export", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await self.updater.update_book(str(self.path))
        self.assertEqual(self.path.read_bytes(), original)

    async def test_auditor_identifies_and_inserts_each_missing_chapter(self):
        self.write([1, 4])
        auditor = NovelHealthAuditor()
        defects, *_ = auditor.audit_file(str(self.path))
        self.assertEqual([defect["chapter_num"] for defect in defects], [2, 3])
        self.catalog([1, 2, 3, 4])
        self.updater.universal_engine.fetch_single_chapter.side_effect = lambda name, index, title, *a, **kw: (index, title, BODY)
        with patch("core.book_health_auditor.IncrementalNovelUpdater", return_value=self.updater):
            report = await auditor.repair_file(str(self.path))
        self.assertEqual(report, {"repaired": 2, "remaining": 0})
        self.assertEqual([chapter.number for chapter in parse_document(self.path.read_text(encoding="utf-8"))[1]], [1, 2, 3, 4])
        self.assertEqual((await auditor.repair_file(str(self.path)))["repaired"], 0)

    async def test_partial_repair_reports_remaining_and_retries(self):
        self.write([1, 4])
        self.catalog([1, 2, 3, 4])
        self.updater.universal_engine.fetch_single_chapter.side_effect = lambda name, index, title, *a, **kw: (index, title, BODY if index == 2 else "【暂缺】")
        auditor = NovelHealthAuditor()
        with patch("core.book_health_auditor.IncrementalNovelUpdater", return_value=self.updater):
            report = await auditor.repair_file(str(self.path))
        self.assertEqual(report, {"repaired": 1, "remaining": 1})
        self.assertEqual(auditor.audit_file(str(self.path))[0][0]["chapter_num"], 3)

    async def test_failed_tail_replacement_preserves_tail(self):
        self.write([1])
        with self.path.open("a", encoding="utf-8") as file:
            file.write("\n第2章\n\n原来的残章\n")
        original = self.path.read_bytes()
        self.catalog([1, 2])
        self.updater.universal_engine.fetch_single_chapter.return_value = (2, "第2章", "【暂缺】")
        await self.updater.update_book(str(self.path))
        self.assertEqual(self.path.read_bytes(), original)

    async def test_unavailable_gap_is_not_reported_as_up_to_date(self):
        self.write([1, 3])
        self.catalog([1, 3])
        original = self.path.read_bytes()
        self.assertFalse(await self.updater.update_book(str(self.path)))
        self.assertEqual(self.path.read_bytes(), original)

    async def test_audit_epub_does_not_create_counterpart_txt(self):
        path = self.path.with_suffix(".epub")
        EpubFormatter.export(str(path), {"title": "测试"}, [(1, "第1章", BODY), (2, "第3章", BODY)])
        defects = NovelHealthAuditor().audit_file(str(path))[0]
        self.assertEqual(defects[0]["chapter_num"], 2)
        self.assertFalse(self.path.exists())

    def real_paged_reader(self):
        engine = self.updater.universal_engine
        engine.fetch_single_chapter = UniversalNovelExtractor.fetch_single_chapter.__get__(engine)
        engine.extractor = extractor()
        engine.router.fallback_route = AsyncMock(return_value=(None, ""))
        def respond(request):
            if request.url.path.endswith("_2.html"):
                return httpx.Response(200, text=html(2, "续页的真实正文，山路通向远方。" * 30))
            return httpx.Response(200, text=html(2, "首页的真实正文，主角走过城门。" * 30, "2_2.html"))
        return lambda *args, **kwargs: REAL_CLIENT(transport=httpx.MockTransport(respond), **kwargs)

    async def test_actual_updater_stitches_and_saves_both_pages(self):
        self.write([1])
        self.catalog([1, 2])
        factory = self.real_paged_reader()
        with patch("core.incremental_updater.httpx.AsyncClient", side_effect=factory):
            self.assertTrue(await self.updater.update_book(str(self.path)))
        text = self.path.read_text(encoding="utf-8")
        self.assertIn("首页的真实正文", text)
        self.assertIn("续页的真实正文", text)

    async def test_actual_auditor_inserts_complete_paged_missing_chapter(self):
        self.write([1, 3])
        self.catalog([1, 2, 3])
        factory = self.real_paged_reader()
        with patch("core.book_health_auditor.IncrementalNovelUpdater", return_value=self.updater), \
             patch("core.book_health_auditor.httpx.AsyncClient", side_effect=factory):
            report = await NovelHealthAuditor().repair_file(str(self.path))
        self.assertEqual(report["remaining"], 0)
        self.assertIn("续页的真实正文", self.path.read_text(encoding="utf-8"))

    async def test_custom_catalog_with_wrong_author_is_rejected(self):
        self.updater.catalog_extractor.discover_catalog = AsyncMock(return_value=(
            {"title": "测试小说", "author": "另一作者"}, [(1, "第1章", "url", 1)]))
        with self.assertRaisesRegex(ValueError, "不一致"):
            await self.updater._catalog("测试小说", "https://books.test/catalog", "本地作者")

    async def test_wrong_author_in_source_cache_falls_back_to_discovery(self):
        self.updater.universal_engine.source_cache.get = Mock(return_value={
            "catalog_url": "https://books.test/wrong", "author": "另一作者"})
        self.updater.catalog_extractor.discover_catalog = AsyncMock(return_value=(
            {"title": "测试小说", "author": "另一作者"}, [(1, "第1章", "url", 1)]))
        self.updater.universal_engine.find_authentic_catalog_candidates = AsyncMock(return_value=[])
        source, chapters = await self.updater._catalog("测试小说", None, "本地作者")
        self.assertEqual(chapters, [])
        self.updater.universal_engine.find_authentic_catalog_candidates.assert_awaited_once()


class TestExtractionFiles(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_format_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = UniversalNovelExtractor(output_dir=directory)
            engine.classifier.classify = AsyncMock()
            with self.assertRaises(ValueError):
                await engine.extract("书名", formats=["txt", "invalid"])
            engine.classifier.classify.assert_not_called()

    async def test_limited_export_does_not_overwrite_full_book(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "《测试小说》.txt"
            target.write_text("已有全本", encoding="utf-8")
            engine = UniversalNovelExtractor(output_dir=directory)
            engine.classifier.classify = AsyncMock(return_value=(InputType.CATALOG_PAGE, {}))
            engine.catalog_extractor.discover_catalog = AsyncMock(return_value=(
                {"title": "测试小说", "author": "作者"},
                [(1, "第1章", "https://books.test/1.html", 1), (2, "第2章", "https://books.test/2.html", 2)]))
            engine.storage = ChapterStorage(os.path.join(directory, "cache"))
            engine.source_cache = SimpleNamespace(set=lambda **kwargs: None)
            async def fetch(name, index, title, url, *args, **kwargs):
                engine.storage.save_chapter(name, index, title, BODY, url)
                return index, title, BODY
            engine.fetch_single_chapter = fetch
            results = await engine.extract("https://books.test/catalog", formats=["txt"], limit_chapters=1)
            self.assertEqual(target.read_text(encoding="utf-8"), "已有全本")
            self.assertIn("章节范围1-1", results["txt"])
            self.assertIn(BODY, Path(results["txt"]).read_text(encoding="utf-8"))

    async def test_extraction_failure_keeps_missing_placeholder_in_separate_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "《测试小说》.txt"
            target.write_text("已有完整版本", encoding="utf-8")
            engine = UniversalNovelExtractor(output_dir=directory)
            engine.classifier.classify = AsyncMock(return_value=(InputType.CATALOG_PAGE, {}))
            engine.catalog_extractor.discover_catalog = AsyncMock(return_value=(
                {"title": "测试小说"}, [(1, "第1章", "https://books.test/1", 1), (2, "第2章", "https://books.test/2", 2)]))
            engine.storage = ChapterStorage(os.path.join(directory, "cache"))
            engine.source_cache = SimpleNamespace(set=lambda **kwargs: None)
            async def fetch(name, index, title, url, *args, **kwargs):
                if index == 1:
                    engine.storage.save_chapter(name, index, title, BODY, url)
                return index, title, BODY if index == 1 else "【暂缺】"
            engine.fetch_single_chapter = fetch
            engine.audit_and_heal_chapters = AsyncMock(side_effect=lambda **kwargs: (kwargs["chapters_data"], 0.5))
            results = await engine.extract("https://books.test/catalog", formats=["txt"])
            self.assertEqual(target.read_text(encoding="utf-8"), "已有完整版本")
            self.assertIn("未完整", results["txt"])
            self.assertIn("第2章", Path(results["txt"]).read_text(encoding="utf-8"))
