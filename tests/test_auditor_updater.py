"""
Unit tests for IncrementalNovelUpdater and NovelHealthAuditor.
"""

import os
import tempfile
import unittest
from core.incremental_updater import IncrementalNovelUpdater
from core.book_health_auditor import NovelHealthAuditor


class TestAuditorAndUpdater(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_auditor_clean_file(self):
        content = "书名：测试仙道\n作者：测试君\n\n第1章 起源\n\n天地初开，万物有灵。" + "正文内容。" * 50 + "\n\n第2章 问道\n\n修仙之路漫漫。" + "正文内容。" * 50
        file_path = os.path.join(self.temp_dir.name, "《测试仙道》.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        auditor = NovelHealthAuditor(min_char_threshold=50)
        defects, book_name, author, full_text = auditor.audit_file(file_path)
        self.assertEqual(book_name, "测试仙道")
        self.assertEqual(author, "测试君")
        self.assertEqual(len(defects), 0)

    def test_auditor_detects_defects(self):
        # Chapter 1 is clean, Chapter 2 is 0 words, Chapter 4 causes gap jump from 2 to 4
        content = "第1章 起源\n\n" + "正文内容。" * 50 + "\n\n第2章 残缺\n\n\n\n第4章 飞升\n\n" + "正文内容。" * 50
        file_path = os.path.join(self.temp_dir.name, "《残缺仙道》.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        auditor = NovelHealthAuditor(min_char_threshold=50)
        defects, book_name, author, _ = auditor.audit_file(file_path)
        self.assertEqual(book_name, "残缺仙道")
        self.assertGreaterEqual(len(defects), 2)
        types = [d["type"] for d in defects]
        self.assertIn("CONTENT_DEFECT", types)
        self.assertIn("GAP_MISSING", types)

    def test_updater_analyze_local_file(self):
        content = "书名：长生道\n作者：云中客\n\n第1章 起步\n\n" + "正文内容。" * 100 + "\n\n第10章 筑基\n\n" + "筑基圆满。" * 100
        file_path = os.path.join(self.temp_dir.name, "《长生道》.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        updater = IncrementalNovelUpdater()
        bname, author, last_num, last_title, base_text = updater.analyze_local_file(file_path)
        self.assertEqual(bname, "长生道")
        self.assertEqual(author, "云中客")
        self.assertEqual(last_num, 10.0)
        self.assertIn("第10章", last_title)

    def test_updater_truncation_fallback(self):
        # Chapter 10 has only 10 chars -> should fall back to chapter 1
        content = "书名：长生道\n作者：云中客\n\n第1章 起步\n\n" + "正文内容。" * 100 + "\n\n第10章 筑基\n\n短内容"
        file_path = os.path.join(self.temp_dir.name, "《长生道残章》.txt")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        updater = IncrementalNovelUpdater()
        bname, author, last_num, last_title, base_text = updater.analyze_local_file(file_path)
        self.assertEqual(last_num, 1.0)
        self.assertIn("第1章", last_title)


if __name__ == "__main__":
    unittest.main()
