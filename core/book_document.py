"""Read and merge existing books without losing headings or EPUB spine order."""
import os
import re
from dataclasses import dataclass

from core.parser import extract_chapter_number


HEADING = re.compile(
    r"^[ \t\u3000]*(?:第\s*[0-9〇零一二两三四五六七八九十百千万]+\s*[章节回节篇]"
    r"|Chapter\s+\d+\b|\d{1,5}[.、]\s+\S)[^\r\n]*", re.M | re.I
)
BAD_CONTENT = ("暂缺", "抓取异常", "微信扫码", "开通付费会员", "已读到0%",
               "想法、划线、书签", "屋里没人", "沉没。淹没。", "汉语词典", "在线词典")


@dataclass
class Chapter:
    number: int
    title: str
    body: str


def parse_document(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    matches = list(HEADING.finditer(text))
    if not matches:
        raise ValueError("未识别到章节标题，请检查文件格式（支持第1章、第一章、Chapter 1）。")
    chapters = []
    seen = set()
    for index, match in enumerate(matches):
        title = match.group().strip()
        number = int(extract_chapter_number(title)[0])
        if number in seen:
            raise ValueError(f"章节号重复：{title}，请先核对目录，原文件未修改。")
        seen.add(number)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chapters.append(Chapter(number, title, text[match.end():end].strip()))
    return text[:matches[0].start()].rstrip(), chapters


def read_book(file_path):
    if file_path.lower().endswith(".epub"):
        from ebooklib import epub
        from bs4 import BeautifulSoup
        book = epub.read_epub(file_path)
        parts = []
        for item_id, linear in book.spine:
            item = book.get_item_with_id(item_id)
            if item is not None and linear != "no" and "nav" not in getattr(item, "properties", []):
                parts.append(BeautifulSoup(item.get_content(), "html.parser").get_text("\n"))
        creators = book.get_metadata("DC", "creator")
        author = creators[0][0] if creators else "未知"
        titles = book.get_metadata("DC", "title")
        metadata_title = titles[0][0] if titles else ""
        text = "\n\n".join(parts)
    else:
        with open(file_path, encoding="utf-8-sig") as file:
            text = file.read()
        author = "未知"
        metadata_title = ""
    match = re.search(r"作者[：:\s]*([^\n\r]+)", text[:1000])
    if match:
        author = match.group(1).strip()
    title = os.path.splitext(os.path.basename(file_path))[0].replace("《", "").replace("》", "").strip()
    header_title = re.match(r"\s*《([^》]+)》\s*(?:\n|$)", text)
    title = metadata_title or (header_title.group(1) if header_title else title)
    return title, author, text


def defective(body, threshold=350):
    return len(body.strip()) < threshold or any(marker in body for marker in BAD_CONTENT)


def render_document(header, chapters):
    blocks = [header.strip()] if header.strip() else []
    blocks.extend(f"{chapter.title}\n\n{chapter.body.strip()}" for chapter in chapters)
    return "\n\n".join(blocks) + "\n"
