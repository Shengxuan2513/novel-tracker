"""Cache identity, service ownership and HTTP behaviour regression tests."""
import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from core.chapter_storage import ChapterStorage
from core.paths import data_dir, downloads_dir
from core.service_process import is_project_service, stop_service
from core import service_process
from core.tracker import NovelTracker
from core.web_server import WebApp
from types import SimpleNamespace

BODY = "这是小说的完整正文，山间云雾散去，城门已经打开。" * 30


class TestCacheIdentity(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage = ChapterStorage(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def test_authors_with_same_book_name_are_separate(self):
        self.storage.save_chapter("同名小说", 1, "第一章 起步", BODY, author="甲")
        self.assertIsNone(self.storage.get_chapter("同名小说", 1, author="乙"))
        self.assertIsNone(self.storage.get_chapter("同名小说", 1))
        self.assertIsNotNone(self.storage.get_chapter("同名小说", 1, author="甲"))

    def test_catalog_position_shift_does_not_reuse_old_chapter(self):
        self.storage.save_chapter("测试", 1, "第1章 起步", BODY)
        self.storage.save_chapter("测试", 2, "第2章 后续", BODY)
        expected = [(1, "第0章 序章", "https://test/0", 0),
                    (2, "第1章 起步", "https://test/1", 1)]
        self.assertEqual(self.storage.get_cached_indices("测试", expected_chapters=expected), set())

    def test_chinese_and_arabic_heading_with_same_title_match(self):
        self.storage.save_chapter("测试", 1, "第一章 起步", BODY)
        expected = [(1, "第1章  起步", "https://test/1", 1)]
        self.assertEqual(self.storage.get_cached_indices("测试", expected_chapters=expected), {1})

    def test_different_title_with_same_number_is_rejected(self):
        self.storage.save_chapter("测试", 1, "第1章 起步", BODY)
        expected = [(1, "第1章 新版内容", "https://test/1", 1)]
        self.assertEqual(self.storage.get_cached_indices("测试", expected_chapters=expected), set())

    def test_legacy_cache_is_retained_but_requires_validation(self):
        path = Path(self.storage.get_chapters_dir("测试")) / "00001.json"
        path.write_text(json.dumps({"index": 1, "title": "第1章", "content": BODY}), encoding="utf-8")
        self.assertEqual(self.storage.get_cached_indices("测试"), set())
        self.assertTrue(path.exists())

    def test_invalid_content_is_not_a_cache_hit(self):
        self.storage.save_chapter("测试", 1, "第1章", BODY + "【暂缺】")
        self.assertEqual(self.storage.get_cached_indices("测试"), set())

    def test_corrupt_cache_json_shape_is_ignored(self):
        path = Path(self.storage.get_chapters_dir("测试")) / "00001.json"
        path.write_text("[]", encoding="utf-8")
        self.assertEqual(self.storage.get_cached_indices("测试"), set())


class TestServiceOwnership(unittest.TestCase):
    def process(self, script):
        process = Mock()
        process.cmdline.return_value = ["python", str(script), "web", "--port", "5000"]
        process.cwd.return_value = str(Path(service_process.__file__).resolve().parent.parent)
        process.create_time.return_value = 123
        return process

    def test_foreign_process_is_not_terminated(self):
        process = self.process(Path(tempfile.gettempdir()) / "unrelated" / "cli.py")
        with patch("core.service_process.find_pid_by_port", return_value=123), \
             patch("core.service_process.psutil.Process", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "其他程序"):
                stop_service(5000)
        process.terminate.assert_not_called()

    def test_owned_relative_script_is_recognised(self):
        process = self.process("cli.py")
        self.assertTrue(is_project_service(process))

    def test_owned_service_is_stopped(self):
        root = Path(service_process.__file__).resolve().parent.parent
        process = self.process(root / "cli.py")
        with patch("core.service_process.find_pid_by_port", return_value=123), \
             patch("core.service_process.psutil.Process", return_value=process):
            stop_service(5000)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=3)

    def test_changed_pid_is_not_terminated(self):
        root = Path(service_process.__file__).resolve().parent.parent
        process = self.process(root / "cli.py")
        with patch("core.service_process.find_pid_by_port", side_effect=[123, 456]), \
             patch("core.service_process.psutil.Process", return_value=process):
            with self.assertRaisesRegex(RuntimeError, "变化"):
                stop_service(5000)
        process.terminate.assert_not_called()


class TestPaths(unittest.TestCase):
    def test_data_paths_do_not_depend_on_working_directory(self):
        before = downloads_dir()
        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                self.assertEqual(downloads_dir(), before)
            finally:
                os.chdir(previous)

    def test_configured_data_directory_is_used(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"NOVEL_TRACKER_DATA_DIR": directory}):
            self.assertEqual(data_dir(), Path(directory).resolve())
            self.assertEqual(downloads_dir(), str(Path(directory).resolve() / "downloads"))


class TestWebStability(AioHTTPTestCase):
    async def get_application(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.webapp = WebApp(output_dir=str(self.root))
        self.webapp.tracker = NovelTracker(str(self.root / "watchlist.json"))
        self.webapp.official_prober.probe = AsyncMock(return_value={})
        self.webapp.sources_manager.search_novel = AsyncMock(return_value=(None, []))
        self.webapp.source_cache.get = Mock(return_value=None)
        app = web.Application()
        app.router.add_post("/api/extract", self.webapp.handle_extract_stream)
        app.router.add_post("/api/bookshelf/add", self.webapp.handle_add_bookshelf)
        app.router.add_post("/api/bookshelf/remove", self.webapp.handle_remove_bookshelf)
        app.router.add_post("/api/bookshelf/check", self.webapp.handle_check_bookshelf)
        app.router.add_get("/api/bookshelf", self.webapp.handle_get_bookshelf)
        app.router.add_get("/api/files", self.webapp.handle_list_files)
        app.router.add_get("/api/download/{filename}", self.webapp.handle_download_file)
        app.router.add_get("/opds", self.webapp.handle_opds)
        app.router.add_get("/api/legado/info", self.webapp.handle_legado_info)
        async def cleanup(app):
            yield
            self.directory.cleanup()
        app.cleanup_ctx.append(cleanup)
        return app

    async def test_bad_extract_inputs_fail_before_starting_task(self):
        invalid = [[], {"target": 123}, {"target": "书名", "formats": []},
                   {"target": "书名", "formats": ["bad"]},
                   {"target": "书名", "start": 0}, {"target": "书名", "start": True},
                   {"target": "书名", "limit": -1}, {"target": "书名", "limit": 1.5}]
        with patch("core.web_server.UniversalNovelExtractor") as engine:
            for value in invalid:
                response = await self.client.post("/api/extract", json=value)
                self.assertEqual(response.status, 400)
            engine.assert_not_called()

    async def test_invalid_json_returns_clear_error(self):
        response = await self.client.post("/api/extract", data="not json", headers={"Content-Type": "application/json"})
        self.assertEqual(response.status, 400)

    async def test_empty_result_is_reported_as_failure(self):
        engine = Mock()
        engine.extract = AsyncMock(return_value={})
        with patch("core.web_server.UniversalNovelExtractor", return_value=engine):
            response = await self.client.post("/api/extract", json={"target": "书名"})
            text = await response.text()
        self.assertIn("提取失败", text)
        self.assertNotIn("✅ 提取完成", text)

    async def test_partial_result_is_not_reported_as_complete(self):
        engine = Mock()
        engine.extract = AsyncMock(return_value={"txt": str(self.root / "《书名》（未完整）.txt")})
        with patch("core.web_server.UniversalNovelExtractor", return_value=engine):
            response = await self.client.post("/api/extract", json={"target": "书名"})
            text = await response.text()
        self.assertIn("部分完成", text)
        self.assertNotIn("✅ 提取完成", text)

    async def test_unknown_book_does_not_return_fake_add_success(self):
        response = await self.client.post("/api/bookshelf/add", json={"name": "不存在的书"})
        self.assertEqual(response.status, 422)
        self.assertEqual(self.webapp.tracker.get_all(), [])

    async def test_book_update_calls_notifier_with_valid_parameters(self):
        self.webapp.tracker.add_book(book_name="测试", latest_chapter="第1章", latest_chapter_num=1)
        self.webapp.sources_manager.search_novel.return_value = (
            SimpleNamespace(latest_chapter_title="第2章", latest_chapter_num=2,
                            latest_chapter_url="https://books.test/2", source_name="测试源"), [])
        self.webapp.notifier.config = {"enable_desktop_notification": False}
        response = await self.client.post("/api/bookshelf/check", json={})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.webapp.tracker.get_book("测试")["last_known_chapter_num"], 2)

    async def test_special_characters_are_preserved_in_bookshelf_json(self):
        name = "带引号'与尖括号<测试>的书"
        self.webapp.tracker.add_book(book_name=name, author="作者")
        response = await self.client.get("/api/bookshelf")
        data = await response.json()
        self.assertEqual(data["books"][0]["name"], name)
        self.assertIsNone(data["books"][0]["gap_chapters"])

    async def test_download_cannot_escape_directory(self):
        response = await self.client.get("/api/download/..%5Csecret.txt")
        self.assertEqual(response.status, 404)

    async def test_literal_percent_filename_and_range_download(self):
        name = "《测试》%2F.txt"
        (self.root / name).write_bytes(b"abcdefghij")
        import urllib.parse
        response = await self.client.get("/api/download/" + urllib.parse.quote(name, safe=""),
                                         headers={"Range": "bytes=2-5"})
        self.assertEqual(response.status, 206)
        self.assertEqual(await response.read(), b"cdef")

    async def test_backups_are_not_listed_or_downloadable(self):
        (self.root / "book.txt").write_text("正文", encoding="utf-8")
        (self.root / "book.txt.bak").write_text("原正文", encoding="utf-8")
        response = await self.client.get("/api/files")
        data = await response.json()
        self.assertEqual([row["name"] for row in data["files"]], ["book.txt"])
        response = await self.client.get("/api/download/book.txt.bak")
        self.assertEqual(response.status, 404)

    async def test_opds_uses_the_address_requested_by_reader(self):
        response = await self.client.get("/opds", headers={"Host": "192.168.137.1:5000"})
        self.assertIn("http://192.168.137.1:5000/opds", await response.text())

    async def test_mobile_copy_links_use_the_same_hotspot_address(self):
        response = await self.client.get("/api/legado/info", headers={"Host": "192.168.137.1:8123"})
        data = await response.json()
        self.assertEqual(data["opds_url"], "http://192.168.137.1:8123/opds")
