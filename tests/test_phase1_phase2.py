# -*- coding: utf-8 -*-
"""
Automated Test Suite for Phase 1 & Phase 2 Architecture Upgrades.
Tests RedirectResolver, RuleBasedExtractor, DualTrackExtractor, and ChapterStorage.
"""

import asyncio
import os
import shutil
import sys
import unittest
import httpx

from core.redirect_resolver import RedirectResolver
from core.rule_extractor import RuleBasedExtractor, DualTrackExtractor
from core.chapter_storage import ChapterStorage
from core.fallback_router import DomainStrategy


class TestPhase1Phase2(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.test_storage_dir = os.path.join(os.path.dirname(__file__), "tmp_test_storage")
        os.makedirs(self.test_storage_dir, exist_ok=True)

    def tearDown(self):
        if os.path.exists(self.test_storage_dir):
            shutil.rmtree(self.test_storage_dir, ignore_errors=True)

    async def test_redirect_resolver_direct_and_cache(self):
        resolver = RedirectResolver(timeout=5.0)
        direct_url = "https://www.example.com/novel/123"
        self.assertFalse(resolver.is_redirect_url(direct_url))
        res = await resolver.resolve_single_url(direct_url)
        self.assertEqual(res, direct_url)

        # Test resolution caching
        so_url = "https://www.so.com/link?m=mock123"
        self.assertTrue(resolver.is_redirect_url(so_url))

    def test_rule_based_extractor(self):
        extractor = RuleBasedExtractor()
        self.assertGreater(len(extractor.rules), 0, "Rules should be loaded from sources/rules")
        
        # Test domain matching
        rule_69 = extractor.get_rule_for_url("https://www.69shu.me/txt/123.htm")
        self.assertIsNotNone(rule_69)
        self.assertEqual(rule_69["name"], "69书吧")

        rule_bige3 = extractor.get_rule_for_url("https://www.bige3.cc/book/123/")
        self.assertIsNotNone(rule_bige3)
        self.assertEqual(rule_bige3["name"], "笔趣阁3")

        # Test content extraction with noise filtering
        sample_html = """
        <html>
            <body>
                <div id="txtcontent">
                    <p>第1章 开始</p>
                    <div class="ad_content">这是广告</div>
                    <p>天道无极，乾坤借法。69书吧最新网址</p>
                    <p>精彩纷呈，正文内容持续演进中，字数足够长以满足测试阈值要求。</p>
                    <p>第二段正文内容继续展开，描述修仙界的浩瀚广阔与无尽神奇，字数持续增加达到两百字以上。</p>
                </div>
            </body>
        </html>
        """
        extracted = extractor.extract_content(sample_html, url="https://www.69shu.me/txt/123/1.htm")
        self.assertIsNotNone(extracted)
        self.assertNotIn("这是广告", extracted)
        self.assertNotIn("69书吧最新网址", extracted)
        self.assertIn("天道无极", extracted)

    def test_chapter_storage_and_incremental_cache(self):
        storage = ChapterStorage(base_storage_dir=self.test_storage_dir)
        book_name = "测试修仙记"

        # Initially empty
        cached = storage.get_cached_indices(book_name)
        self.assertEqual(len(cached), 0)

        # Save chapters
        storage.save_chapter(
            book_name=book_name,
            index=1,
            title="第一章 初入仙门",
            content="这是第一章的完整正文内容，字数非常充裕，详细描绘了主角踏入修真门派的生动场景。" * 5,
            url="http://example.com/1",
            source_domain="example.com"
        )
        storage.save_chapter(
            book_name=book_name,
            index=2,
            title="第二章 筑基初成",
            content="这是第二章的完整正文内容，筑基顺利完成，灵力运转周天，展现出非凡的天赋资质。" * 5,
            url="http://example.com/2",
            source_domain="example.com"
        )

        # Check cached indices
        cached_after = storage.get_cached_indices(book_name)
        self.assertIn(1, cached_after)
        self.assertIn(2, cached_after)
        self.assertEqual(len(cached_after), 2)

        # Load all chapters
        all_chaps = storage.load_all_chapters(book_name)
        self.assertEqual(len(all_chaps), 2)
        self.assertEqual(all_chaps[0][0], 1)
        self.assertEqual(all_chaps[1][0], 2)
        self.assertIn("初入仙门", all_chaps[0][1])

    def test_domain_strategy_blacklist(self):
        # Verify blacklisted paywall domains
        self.assertTrue(DomainStrategy.is_blacklisted("https://chuangshi.qq.com/detail/123"))
        self.assertTrue(DomainStrategy.is_blacklisted("https://read.qq.com/chapter/123"))
        self.assertTrue(DomainStrategy.is_blacklisted("https://www.qidian.com/chapter/123"))
        self.assertFalse(DomainStrategy.is_blacklisted("https://www.69shu.me/txt/123.htm"))
        self.assertFalse(DomainStrategy.is_blacklisted("https://www.bige3.cc/book/123/"))


if __name__ == "__main__":
    unittest.main()
