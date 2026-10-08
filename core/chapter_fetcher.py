"""Shared complete-chapter acquisition for extract, update and repair."""
import re
import urllib.parse

from bs4 import BeautifulSoup

from core.exceptions import DataIncompleteError
from core.heuristic_catalog import safe_decode_response
from core.parser import extract_chapter_number
from core.pipeline import RegexCleaningPipeline
from core.content_fingerprint import ContentFingerprintValidator


def _identity(url):
    parsed = urllib.parse.urlsplit(url)
    path = re.sub(r"[_-]\d+(?=\.[^/.]+$)", "", parsed.path)
    return parsed.hostname, path


def _number(soup):
    for node in soup.select("h1, h2, title"):
        title = node.get_text(" ", strip=True)
        if re.search(r"第\s*[0-9〇零一二两三四五六七八九十百千万]+\s*[章节回节篇]|Chapter\s+\d+", title, re.I):
            return extract_chapter_number(title)[0]
    return None


async def fetch_complete_chapter(client, url, title, extractor, min_chars=200, max_pages=9,
                                 html_preset=None, return_page=False):
    """Never return the first page when a declared continuation could not be read."""
    expected_number = extract_chapter_number(title)[0]
    visited, bodies, parts = set(), set(), []
    current, referer = url, url
    for page in range(max_pages):
        canonical = urllib.parse.urldefrag(current)[0]
        if canonical in visited:
            raise DataIncompleteError(title, current, 0, "分页链接循环")
        visited.add(canonical)
        if page == 0 and html_preset is not None:
            actual, html = current, html_preset
        else:
            response = await client.get(current, headers={"Referer": referer})
            response.raise_for_status()
            actual = str(response.url)
            html = safe_decode_response(response)
        soup = BeautifulSoup(html, "html.parser")
        number = _number(soup)
        if number is not None and expected_number > 0 and number != expected_number:
            raise DataIncompleteError(title, actual, 0, "分页跳到了其他章节")
        # Without a chapter heading, only accept recognisable same-chapter URLs.
        if page and number is None and _identity(actual) != _identity(url):
            raise DataIncompleteError(title, actual, 0, "无法确认分页属于当前章节")
        raw = extractor.extract_article_text(html, url=actual)
        clean = RegexCleaningPipeline(min_char_length=1, validator=ContentFingerprintValidator(min_char_length=1)).clean_text(
            raw, chapter_title=title, source_url=actual)
        if clean in bodies:
            raise DataIncompleteError(title, actual, len(clean), "分页正文重复")
        bodies.add(clean)
        parts.append(clean)
        next_link = next((anchor for anchor in soup.find_all("a", href=True)
                          if re.fullmatch(r"(?:下一页|下页)\s*[>»›→]*", anchor.get_text(strip=True))), None)
        if next_link is None:
            break
        referer, current = actual, urllib.parse.urljoin(actual, next_link["href"])
        if urllib.parse.urlsplit(current).hostname != urllib.parse.urlsplit(url).hostname:
            raise DataIncompleteError(title, current, 0, "分页链接指向其他站点")
    else:
        raise DataIncompleteError(title, current, 0, "达到分页上限，正文尚未完整")
    combined = "\n\n".join(parts)
    if len(re.sub(r"\s", "", combined)) < min_chars:
        raise DataIncompleteError(title, url, len(combined), "完整正文字数不足")
    return (combined, soup, actual) if return_page else combined
