"""
Sogou Search Source.
Searches Sogou for novel updates and extracts latest chapter information and links.
"""

import re
import urllib.parse
from typing import List
import httpx
from bs4 import BeautifulSoup

from .base import BaseSource, NovelSearchResult
from core.parser import extract_chapter_number


class SogouSearchSource(BaseSource):
    name = "搜狗搜索聚合"
    domain = "sogou.com"

    async def search(self, novel_name: str) -> List[NovelSearchResult]:
        results: List[NovelSearchResult] = []
        query = f"{novel_name} 最新章节"
        encoded_query = urllib.parse.quote(query)
        url = f"https://www.sogou.com/web?query={encoded_query}"

        try:
            async with httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
                verify=False
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return results

                soup = BeautifulSoup(resp.text, "html.parser")
                items = soup.select(".results .vrwrap, .results .rb")

                for item in items:
                    h3 = item.select_one("h3")
                    if not h3:
                        continue

                    title_text = h3.get_text(strip=True)
                    a_tag = h3.find("a")
                    page_url = a_tag.get("href", "") if a_tag else ""
                    if page_url.startswith("/"):
                        page_url = f"https://www.sogou.com{page_url}"

                    clean_book = re.sub(r'[\(（《》）\s]', '', novel_name)
                    clean_title = re.sub(r'[\(（《》）\s]', '', title_text)
                    if clean_book not in clean_title:
                        continue

                    body_text = item.get_text(" ", strip=True)

                    matches = re.findall(
                        r'(第\s*[0-9零一二两三四五六七八九十百千万]+\s*[章节回集卷篇节][^\s,，。；\n\r<]{0,30})',
                        body_text
                    )
                    special_matches = re.findall(
                        r'(终章[^\s,，。；\n\r<]{0,20}|大结局[^\s,，。；\n\r<]{0,20}|完本感言[^\s,，。；\n\r<]{0,20})',
                        body_text
                    )
                    all_matches = matches + special_matches
                    if not all_matches:
                        continue

                    best_ch_title = ""
                    best_ch_num = -1.0
                    for ch in all_matches:
                        ch_clean = ch.strip().replace(" ", "")
                        num, _ = extract_chapter_number(ch_clean)
                        if num > best_ch_num:
                            best_ch_num = num
                            best_ch_title = ch_clean

                    if best_ch_title:
                        author_match = re.search(r'作者[:：\s]*([^\s,，。；|_\-—]{1,10})', body_text)
                        author = author_match.group(1).strip() if author_match else "未知"

                        time_match = re.search(r'(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}|\d+\s*(?:小时|分钟|天)前)', body_text)
                        update_time = time_match.group(1).strip() if time_match else "近期"

                        results.append(NovelSearchResult.create(
                            book_name=novel_name,
                            author=author,
                            latest_chapter_title=best_ch_title,
                            latest_chapter_url=page_url,
                            book_url=page_url,
                            update_time=update_time,
                            source_name="搜狗聚合",
                            source_domain="sogou.com"
                        ))
        except Exception:
            pass

        return results
