"""
Unit tests for URLClassifier and Formatters (TXT, EPUB, JSON).
"""

import json
import os
import tempfile
import unittest
import zipfile
from bs4 import BeautifulSoup

from core.url_classifier import URLClassifier, InputType
from core.heuristic_catalog import HeuristicCatalogExtractor
from core.formatters import TxtFormatter, JsonFormatter, EpubFormatter


class TestUniversalComponents(unittest.TestCase):
    def setUp(self):
        self.classifier = URLClassifier()
        self.catalog_extractor = HeuristicCatalogExtractor()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_url_classification_is_url(self):
        self.assertTrue(self.classifier.is_url("https://www.biquge.com/book/123"))
        self.assertTrue(self.classifier.is_url("http://127.0.0.1:8080/chap/1.html"))
        self.assertFalse(self.classifier.is_url("宿命之环"))
        self.assertFalse(self.classifier.is_url("没钱修什么仙？"))

    def test_metadata_extraction_from_soup(self):
        sample_html = """
        <html>
        <head>
            <title>《赤心巡天》最新章节全文在线阅读 - 顶点小说</title>
            <meta property="og:novel:author" content="情何以甚"/>
            <meta property="og:novel:book_name" content="赤心巡天"/>
        </head>
        <body>
            <h1>赤心巡天</h1>
        </body>
        </html>
        """
        soup = BeautifulSoup(sample_html, "html.parser")
        meta = self.catalog_extractor.extract_novel_meta(soup)
        self.assertEqual(meta["title"], "赤心巡天")
        self.assertEqual(meta["author"], "情何以甚")

    def test_formatters_export(self):
        book_meta = {"title": "测试修真传", "author": "测试作者", "description": "这是一本测试修仙小说"}
        chapters = [
            (1, "第1章 惊变", "第1章 惊变\n\n    第一段正文内容，张羽手持青锋剑。\n\n    第二段正文内容，狂风大作。"),
            (2, "第2章 仙缘", "第2章 仙缘\n\n    第一段正文内容，仙人洞天开启。\n\n    第二段正文内容，踏入仙途。")
        ]

        # 1. Test TXT Formatter
        txt_out = os.path.join(self.temp_dir.name, "book.txt")
        TxtFormatter.export(txt_out, book_meta, chapters, "http://test.com")
        self.assertTrue(os.path.exists(txt_out))
        with open(txt_out, "r", encoding="utf-8") as f:
            txt_content = f.read()
            self.assertIn("《测试修真传》", txt_content)
            self.assertIn("第1章 惊变", txt_content)

        # 2. Test JSON Formatter
        json_out = os.path.join(self.temp_dir.name, "book.json")
        JsonFormatter.export(json_out, book_meta, chapters, "http://test.com")
        self.assertTrue(os.path.exists(json_out))
        with open(json_out, "r", encoding="utf-8") as f:
            j = json.load(f)
            self.assertEqual(j["book_title"], "测试修真传")
            self.assertEqual(j["total_chapters"], 2)
            self.assertEqual(len(j["chapters"]), 2)

        # 3. Test EPUB Formatter (Check valid EPUB zip structure)
        epub_out = os.path.join(self.temp_dir.name, "book.epub")
        EpubFormatter.export(epub_out, book_meta, chapters, "http://test.com")
        self.assertTrue(os.path.exists(epub_out))
        with zipfile.ZipFile(epub_out, "r") as zf:
            namelist = zf.namelist()
            self.assertIn("mimetype", namelist)
            self.assertIn("META-INF/container.xml", namelist)
            self.assertIn("OEBPS/content.opf", namelist)
            self.assertIn("OEBPS/toc.ncx", namelist)
            self.assertIn("OEBPS/nav.xhtml", namelist)
            self.assertIn("OEBPS/chapter_1.xhtml", namelist)
            self.assertIn("OEBPS/chapter_2.xhtml", namelist)


if __name__ == "__main__":
    unittest.main()
