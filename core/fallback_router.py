"""
Fallback Routing and Heuristic Content Extraction Engine.
Dispatches queries across multi-engine SERP adapters (Baidu, Sogou, Bing, DuckDuckGo)
with domain scoring to guarantee high-reliability full chapter extraction.
"""

import asyncio
import os
import re
import urllib.parse
from typing import List, Optional, Tuple, Dict
import httpx
from bs4 import BeautifulSoup

from core.exceptions import DataIncompleteError, SourceExhaustedError
from core.heuristic_extractor import HeuristicExtractor
from core.pipeline import RegexCleaningPipeline


class DomainStrategy:
    """
    Domain whitelist and scoring table.
    Prioritizes clean content mirrors and blacklists paywalled/community sites.
    """
    DOMAIN_WEIGHTS = {
        "51read.org": 100,
        "bige3.cc": 95,
        "xbiquwx.la": 90,
        "69shu.me": 85,
        "shuhaige.net": 85,
        "piaotia.com": 80,
        "biquge.com": 75,
        "biqu70.cc": 75,
        "89wx.cc": 70,
        "ttkan.co": 70,
        "xxsy.net": -100,
        "readnovel.com": -100,
        "hongxiu.com": -100,
        "xs8.cn": -100,
        "qdmm.com": -300,
        "qidian.com": -500,
        "qq.com": -500,
        "novel.qq.com": -500,
        "chuangshi.qq.com": -500,
        "tieba.baidu.com": -1000,
        "zhihu.com": -1000,
        "bilibili.com": -1000,
        "weibo.com": -1000,
        "douban.com": -1000,
    }

    @classmethod
    def get_domain_score(cls, url: str) -> int:
        for domain, score in cls.DOMAIN_WEIGHTS.items():
            if domain in url:
                return score
        return 10

    @classmethod
    def score_url(cls, url: str) -> int:
        return cls.get_domain_score(url)

    @classmethod
    def is_blacklisted(cls, url: str) -> bool:
        return cls.get_domain_score(url) <= -300

    @classmethod
    def filter_and_sort_candidates(cls, candidate_urls: List[str]) -> List[str]:
        valid_urls = []
        seen = set()
        for url in candidate_urls:
            if not url or not url.startswith("http"):
                continue
            if url in seen:
                continue
            seen.add(url)
            if not cls.is_blacklisted(url):
                valid_urls.append(url)

        valid_urls.sort(key=lambda u: cls.get_domain_score(u), reverse=True)
        return valid_urls


class FallbackRouter:
    """
    Orchestrates fallback query construction, multi-engine SERP scraping,
    and heuristic content extraction.
    """
    def __init__(self, timeout: float = 8.0, min_char_length: int = 350):
        self.timeout = timeout
        self.extractor = HeuristicExtractor()
        self.pipeline = RegexCleaningPipeline(min_char_length=min_char_length)
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def build_search_query(self, novel_name: str, chapter_title: str) -> str:
        """Builds clean high-recall search query."""
        clean_ch = re.sub(r'第\s*[0-9零一二两三四五六七八九十百千万]+\s*[章节回集卷篇节]\s*', '', chapter_title)
        clean_ch = re.sub(r'[\(（\[【].*?[\)）\]】]', '', clean_ch).strip()
        sub_title = clean_ch if len(clean_ch) >= 2 else chapter_title
        return f"{novel_name} {sub_title}"

    def build_query(self, novel_name: str, chapter_title: str) -> str:
        return self.build_search_query(novel_name, chapter_title)

    async def search_candidates(self, query: str) -> List[str]:
        """
        Dispatches multi-engine search across Baidu, Sogou, Bing, and DuckDuckGo.
        """
        candidates: List[str] = []
        encoded_q = urllib.parse.quote(query)

        async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True, verify=False) as client:
            # 1. Baidu Search
            try:
                baidu_url = f"https://www.baidu.com/s?wd={encoded_q}&rn=10"
                resp = await client.get(baidu_url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.select(".result h3 a, .c-container h3 a"):
                        href = a.get("href")
                        if href and href.startswith("http"):
                            candidates.append(href)
            except Exception:
                pass

            # 2. Sogou Web
            try:
                sogou_url = f"https://www.sogou.com/web?query={encoded_q}"
                resp = await client.get(sogou_url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.select(".results a"):
                        href = a.get("href", "")
                        if href.startswith("/"):
                            href = f"https://www.sogou.com{href}"
                        if href.startswith("http") and "sogou.com/link" in href:
                            candidates.append(href)
            except Exception:
                pass

            # 3. Bing Web
            try:
                bing_url = f"https://cn.bing.com/search?q={encoded_q}"
                resp = await client.get(bing_url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.content.decode("utf-8", errors="ignore"), "html.parser")
                    for a in soup.select("#b_results li.b_algo h2 a"):
                        href = a.get("href", "")
                        if href.startswith("http"):
                            candidates.append(href)
            except Exception:
                pass

            # 4. DuckDuckGo HTML
            try:
                ddg_url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
                resp = await client.post(ddg_url, data={"q": query})
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a in soup.select(".result__url, .result__title a"):
                        href = a.get("href", "")
                        if "uddg=" in href:
                            m = re.search(r'uddg=([^&]+)', href)
                            if m:
                                href = urllib.parse.unquote(m.group(1))
                        if href.startswith("http"):
                            candidates.append(href)
            except Exception:
                pass

        return DomainStrategy.filter_and_sort_candidates(candidates)

    async def fallback_route(
        self,
        novel_name: str,
        chapter_title: str,
        max_retries: int = 8
    ) -> Tuple[str, str]:
        """
        Executes fallback routing to recover full chapter text.
        """
        query = self.build_search_query(novel_name, chapter_title)
        candidates = await self.search_candidates(query)

        if not candidates:
            raise SourceExhaustedError(chapter_title, f"No fallback candidates found for query: {query}")

        async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True, verify=False) as client:
            for idx, url in enumerate(candidates[:max_retries]):
                try:
                    resp = await client.get(url, timeout=self.timeout)
                    if resp.status_code != 200:
                        continue

                    enc = resp.encoding if resp.encoding and resp.encoding != 'iso-8859-1' else 'utf-8'
                    try:
                        html = resp.content.decode(enc, errors='replace')
                    except Exception:
                        html = resp.text

                    raw_text = self.extractor.extract_article_text(html, url=str(resp.url))
                    if not raw_text or len(raw_text) < 300:
                        continue

                    clean_text = self.pipeline.clean_text(raw_text, chapter_title=chapter_title, source_url=str(resp.url))
                    if len(clean_text) >= 300:
                        return clean_text, str(resp.url)

                except Exception:
                    continue

        raise SourceExhaustedError(
            chapter_title,
            f"All {min(len(candidates), max_retries)} candidate fallback sources failed or returned incomplete content"
        )
