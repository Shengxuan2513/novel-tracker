"""
Chained Chapter Crawler.
Follows '下一章' / '下一页' links sequentially when starting from a single chapter URL.
"""

import re
from typing import List, Tuple, Dict, Optional
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup

from core.heuristic_extractor import HeuristicExtractor
from core.pipeline import RegexCleaningPipeline
from core.parser import extract_chapter_number
from core.chapter_fetcher import fetch_complete_chapter


class ChainedChapterCrawler:
    def __init__(self, timeout: float = 10.0, min_char_length: int = 300):
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

    def find_catalog_url_from_chapter(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """Looks for '目录' or '返回目录' link in reading page."""
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if any(k in text for k in ("目 录", "目录", "返回目录", "章节列表", "全书目录")):
                href = a["href"]
                if not href.startswith("javascript") and not href.startswith("#"):
                    return urljoin(current_url, href)
        return None

    def find_next_chapter_url(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """Finds '下一章' or '下一页' link in reading page."""
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if any(k in text for k in ("下一章", "下 一 章")):
                href = a["href"]
                if not href.startswith("javascript") and not href.startswith("#"):
                    target = urljoin(current_url, href)
                    if target != current_url and not target.endswith("/"):
                        return target
        return None

    async def crawl_chain(
        self,
        start_chapter_url: str,
        max_chapters: int = 2000,
        progress_callback = None,
        start_chapter: int = 1,
        log_callback = None
    ) -> Tuple[Dict[str, str], List[Tuple[int, str, str]]]:
        """
        Sequentially crawls along the chapter chain.
        Returns:
            (metadata, chapters: [(index, title, content), ...])
        """
        chapters: List[Tuple[int, str, str]] = []
        meta = {"title": "未知小说", "author": "未知"}
        current_url = start_chapter_url
        seen_urls = set()
        idx = 1
        max_chapters = max_chapters if max_chapters is not None else 2000

        async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True, verify=False) as client:
            while current_url and idx < start_chapter + max_chapters:
                if current_url in seen_urls:
                    break
                seen_urls.add(current_url)

                try:
                    resp = await client.get(current_url)
                    html = ""
                    if resp.status_code == 200:
                        enc = resp.encoding if resp.encoding and resp.encoding != 'iso-8859-1' else 'utf-8'
                        try:
                            html = resp.content.decode(enc, errors='replace')
                        except Exception:
                            html = resp.text

                    if resp.status_code in (403, 503) or "Just a moment" in html or "请稍候" in html or not html:
                        try:
                            from core.browser_fetcher import BrowserFetcher
                            bf = BrowserFetcher()
                            rendered = await bf.fetch_html(current_url)
                            if rendered:
                                html = rendered
                        except Exception:
                            pass

                    if not html:
                        break

                    soup = BeautifulSoup(html, "html.parser")

                    # Extract book title if not present
                    if meta["title"] == "未知小说" and soup.title:
                        t = soup.title.get_text(strip=True)
                        m = re.search(r'《(.*?)》', t)
                        if m:
                            meta["title"] = m.group(1)

                    # Extract chapter title
                    h1 = soup.find("h1")
                    if h1:
                        chapter_title = h1.get_text(strip=True)
                    elif soup.title:
                        chapter_title = re.sub(r'[_|\-—].*$', '', soup.title.get_text(strip=True)).strip()
                    else:
                        chapter_title = f"第 {idx} 章"

                    clean_content, soup, final_url = await fetch_complete_chapter(
                        client, current_url, chapter_title, self.extractor,
                        min_chars=self.pipeline.min_char_length, html_preset=html, return_page=True)
                    self.pipeline.validator.validate_and_record(chapter_title, clean_content, current_url)
                    if idx >= start_chapter:
                        chapters.append((idx, chapter_title, clean_content))
                    if log_callback:
                        await log_callback(f"  ✓ [{idx}] 完整章节: {chapter_title}")

                    if progress_callback:
                        progress_callback(idx, chapter_title)

                    # Find next chapter
                    next_url = self.find_next_chapter_url(soup, final_url)
                    if not next_url or next_url == current_url:
                        break
                    current_url = next_url
                    idx += 1
                except Exception:
                    break

        return meta, chapters
