import asyncio
import os
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from core.parser import extract_chapter_number


def safe_decode_response(resp: httpx.Response) -> str:
    """Accurately decodes HTTP response detecting GBK/GB2312/GB18030/UTF-8 charsets."""
    raw_head = resp.content[:2000].decode("latin-1", errors="ignore")
    m = re.search(r'charset=["\']?\s*([a-zA-Z0-9_-]+)', raw_head, re.IGNORECASE)
    detected = m.group(1).lower() if m else None

    if detected in ("gbk", "gb2312", "gb18030"):
        try:
            return resp.content.decode("gb18030", errors="replace")
        except Exception:
            pass

    if detected in ("utf-8", "utf8"):
        try:
            return resp.content.decode("utf-8", errors="replace")
        except Exception:
            pass

    enc = resp.encoding if resp.encoding and resp.encoding.lower() not in ('iso-8859-1', 'ascii') else None
    if enc:
        try:
            return resp.content.decode(enc, errors="replace")
        except Exception:
            pass

    try:
        return resp.content.decode("utf-8")
    except UnicodeDecodeError:
        return resp.content.decode("gb18030", errors="replace")


class HeuristicCatalogExtractor:
    """
    Heuristic catalog and chapter list extractor.
    Discovers full chapter index from catalog pages, novel detail pages, or paginated catalogs.
    """

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def extract_novel_meta(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extracts book title and author heuristically from HTML."""
        meta = {"title": "", "author": "未知", "description": ""}

        # 1. OpenGraph / Novel Meta Tags
        og_title = soup.find("meta", property=re.compile(r"og:(?:novel:)?book_name|og:title", re.I))
        if og_title and og_title.get("content"):
            meta["title"] = og_title["content"].strip()

        og_author = soup.find("meta", property=re.compile(r"og:(?:novel:)?author", re.I))
        if og_author and og_author.get("content"):
            meta["author"] = og_author["content"].strip()

        # 2. Heading inspection
        if not meta["title"]:
            h1 = soup.find("h1")
            if h1:
                meta["title"] = h1.get_text(strip=True)

        if not meta["title"] and soup.title:
            t = soup.title.get_text(strip=True)
            m = re.search(r'《(.*?)》', t)
            if m:
                meta["title"] = m.group(1)
            else:
                meta["title"] = re.sub(r'[_|\-—].*$', '', t).replace('最新章节', '').replace('全文阅读', '').strip()

        if meta["author"] == "未知":
            full_text = soup.get_text()
            m = re.search(r'作\s*者[：:\s]*([^\s,，。；|_\-—\n\r<]{1,12})', full_text)
            if m:
                meta["author"] = m.group(1).strip()

        if meta["title"]:
            meta["title"] = re.sub(r'^\s*\d+(\.\d+)?[万千]?字\s*', '', meta["title"]).strip()
            meta["title"] = re.sub(r'(?:最新章节|全文阅读|小说|TXT下载|在线阅读|无弹窗).*$', '', meta["title"]).strip()

        return meta

    def find_catalog_link_from_detail(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """Finds entry link to full catalog from a book detail page."""
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if any(k in text for k in ("全部章节", "章节目录", "查看目录", "完整目录", "目录列表", "更多章节")):
                return urljoin(current_url, a["href"])

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if any(k in href for k in ("/mulu", "/catalog", "/chapters", "/zhangjie", "/dir")):
                return urljoin(current_url, href)

        return None

    def find_next_page_link(self, soup: BeautifulSoup, current_url: str) -> Optional[str]:
        """Detects pagination links for multi-page catalogs."""
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            if any(k in text for k in ("下一页", "下一页 »", "Next Page", "后一页")):
                return urljoin(current_url, a["href"])
        return None

    def parse_single_catalog_page(
        self,
        soup: BeautifulSoup,
        base_url: str,
        start_idx: int = 1
    ) -> List[Tuple[int, str, str, float]]:
        """
        Parses all chapter links from a single catalog HTML page.
        Returns: [(index, title, full_url, chapter_num), ...]
        """
        results = []
        seen_urls = set()

        containers = soup.find_all(["div", "ul", "dl", "section", "table"])
        best_container = None
        max_density = 0

        for container in containers:
            links = container.find_all("a", href=True)
            if len(links) < 5:
                continue

            chapter_matches = 0
            for link in links:
                txt = link.get_text(strip=True)
                if re.search(r'(第\s*[0-9零一二两三四五六七八九十百千万]+\s*[章节回集卷篇节]|Chapter\s*\d+|序章|楔子|尾声|番外|终章|大结局)', txt, re.I):
                    chapter_matches += 1

            density = chapter_matches / max(len(links), 1)
            if chapter_matches >= 5 and (chapter_matches > max_density * 5 or density > 0.5):
                if chapter_matches > max_density:
                    max_density = chapter_matches
                    best_container = container

        search_scope = best_container if best_container else soup

        for a in search_scope.find_all("a", href=True):
            txt = a.get_text(strip=True)
            if not txt or len(txt) > 60:
                continue

            href = a["href"].strip()
            if href.startswith("javascript:") or href.startswith("#") or not href:
                continue

            full_url = urljoin(base_url, href)
            if full_url in seen_urls:
                continue

            if not re.search(r'(第\s*[0-9零一二两三四五六七八九十百千万]+\s*[章节回集卷篇节]|Chapter\s*\d+|序章|楔子|尾声|番外|终章|大结局|\d+\.|\d+、)', txt, re.I):
                continue

            seen_urls.add(full_url)
            ch_num, _ = extract_chapter_number(txt)
            results.append((len(results) + start_idx, txt, full_url, ch_num))

        return results

    async def discover_catalog(
        self,
        target_url: str,
        html_preset: Optional[str] = None
    ) -> Tuple[Dict[str, str], List[Tuple[int, str, str, float]]]:
        """
        Discovers complete book metadata and all chapter links (including handling multi-page catalogs).
        Returns:
            (book_meta: Dict, chapters: List[(idx, title, url, num)])
        """
        chapters: List[Tuple[int, str, str, float]] = []
        book_meta: Dict[str, str] = {"title": "未知小说", "author": "未知"}
        visited_urls = set()

        current_url = target_url

        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
            verify=False
        ) as client:
            # 1. Fetch initial page if not preset
            if html_preset:
                html = html_preset
            else:
                try:
                    resp = await client.get(current_url)
                    html = safe_decode_response(resp)
                except Exception:
                    return book_meta, chapters

            soup = BeautifulSoup(html, "html.parser")
            book_meta = self.extract_novel_meta(soup)

            # Check if this is a book detail page with an external catalog link
            catalog_link = self.find_catalog_link_from_detail(soup, current_url)
            if catalog_link and catalog_link != current_url and catalog_link not in visited_urls:
                try:
                    resp = await client.get(catalog_link)
                    c_html = safe_decode_response(resp)
                    current_url = catalog_link
                    soup = BeautifulSoup(c_html, "html.parser")
                    meta2 = self.extract_novel_meta(soup)
                    if meta2["title"]:
                        book_meta["title"] = meta2["title"]
                    if meta2["author"] != "未知":
                        book_meta["author"] = meta2["author"]
                except Exception:
                    pass

            # 2. Extract chapters across paginated catalog pages
            max_pages = 25
            current_page = 1

            while current_url and current_url not in visited_urls and current_page <= max_pages:
                visited_urls.add(current_url)

                page_chapters = self.parse_single_catalog_page(soup, current_url, start_idx=len(chapters) + 1)
                chapters.extend(page_chapters)

                next_url = self.find_next_page_link(soup, current_url)
                if not next_url or next_url in visited_urls:
                    break

                try:
                    current_page += 1
                    resp = await client.get(next_url)
                    n_html = safe_decode_response(resp)
                    current_url = next_url
                    soup = BeautifulSoup(n_html, "html.parser")
                except Exception:
                    break

        # Post-process: deduplicate by chapter title
        final_chapters = []
        seen_titles = set()
        for idx, (original_idx, title, url, num) in enumerate(chapters, 1):
            clean_t = re.sub(r'\s+', '', title)
            if clean_t not in seen_titles:
                seen_titles.add(clean_t)
                final_chapters.append((len(final_chapters) + 1, title, url, num))

        # Auto-detect reverse ordering (e.g. Chapter 966 -> Chapter 1)
        # Sort chapters sequentially if majority have valid chapter numbers
        valid_chapters = [c for c in final_chapters if c[3] > 0]
        if len(valid_chapters) >= 15 and len(valid_chapters) / len(final_chapters) >= 0.7:
            final_chapters.sort(key=lambda x: (x[3] == 0, x[3]))
            # Re-index to 1..N
            final_chapters = [
                (new_idx, title, url, num)
                for new_idx, (_, title, url, num) in enumerate(final_chapters, 1)
            ]
        elif len(valid_chapters) >= 10 and valid_chapters[0][3] > valid_chapters[-1][3]:
            final_chapters.reverse()
            final_chapters = [
                (new_idx, title, url, num)
                for new_idx, (_, title, url, num) in enumerate(final_chapters, 1)
            ]

        return book_meta, final_chapters
