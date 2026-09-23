"""
Core Incremental Novel Updater Module.
Detects the latest chapter in an existing local novel file (.txt or .epub),
probes the freshest authentic catalog, fetches only new chapters, and merges them seamlessly.
"""

import asyncio
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

if sys.platform.startswith("win") and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

import httpx
from core.heuristic_catalog import HeuristicCatalogExtractor, safe_decode_response
from core.rule_extractor import DualTrackExtractor
from core.pipeline import RegexCleaningPipeline
from core.formatters import EpubFormatter, TxtFormatter
from core.parser import extract_chapter_number
from core.universal_engine import UniversalNovelExtractor


class IncrementalNovelUpdater:
    def __init__(self, timeout: float = 12.0, concurrency: int = 15):
        self.timeout = timeout
        self.concurrency = concurrency
        self.catalog_extractor = HeuristicCatalogExtractor(timeout=timeout)
        self.extractor = DualTrackExtractor()
        self.pipeline = RegexCleaningPipeline(min_char_length=200)
        self.universal_engine = UniversalNovelExtractor()
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def analyze_local_file(self, file_path: str) -> Tuple[str, str, float, str, str]:
        """
        Analyzes a local TXT or EPUB file to extract book title, author, and latest chapter.
        Returns: (book_name, author, last_chap_num, last_chap_title, base_clean_text)
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Target file not found: {file_path}")

        basename = os.path.splitext(os.path.basename(file_path))[0]
        book_name = basename.replace("《", "").replace("》", "").strip()
        author = "未知"

        # If EPUB, look for counterpart TXT or extract from EPUB
        txt_path = file_path
        if file_path.lower().endswith(".epub"):
            counterpart_txt = os.path.splitext(file_path)[0] + ".txt"
            if os.path.exists(counterpart_txt):
                txt_path = counterpart_txt
            else:
                # Extract text from EPUB
                import ebooklib
                from ebooklib import epub
                from bs4 import BeautifulSoup
                book = epub.read_epub(file_path)
                author_meta = book.get_metadata('DC', 'creator')
                if author_meta:
                    author = author_meta[0][0]
                text_parts = []
                for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    text_parts.append(soup.get_text())
                full_raw_text = "\n\n".join(text_parts)
                with open(counterpart_txt, "w", encoding="utf-8") as f:
                    f.write(full_raw_text)
                txt_path = counterpart_txt

        with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

        # Extract author if present in header
        m_auth = re.search(r'作\s*者[：:\s]*([^\s,，。；\n\r<]{1,15})', text[:1000])
        if m_auth:
            author = m_auth.group(1).strip()
        elif author == "未知":
            cached = self.universal_engine.source_cache.get(book_name)
            if cached and cached.get("author"):
                author = cached["author"]

        # Scan all chapter headings
        matches = list(re.finditer(r'^(第\s*(\d+)\s*章[^\n]*)', text, re.M))
        if not matches:
            raise ValueError("No standard chapter headings (e.g. 第X章) found in local file.")

        last_match = matches[-1]
        last_chap_title = last_match.group(1).strip()
        last_chap_num = float(last_match.group(2))

        # Check if the last chapter is truncated (< 350 chars)
        last_pos = last_match.start()
        last_content = text[last_pos:]
        if len(last_content.strip()) < 350 and len(matches) > 1:
            prev_match = matches[-2]
            print(f"⚠️ 检测到最后一章 ({last_chap_title}) 正文不完整 (仅 {len(last_content.strip())} 字)，将从第 {prev_match.group(2)} 章重新续更。")
            last_chap_title = prev_match.group(1).strip()
            last_chap_num = float(prev_match.group(2))
            base_clean_text = text[:matches[-1].start()].rstrip()
        else:
            base_clean_text = text.rstrip()

        return book_name, author, last_chap_num, last_chap_title, base_clean_text

    async def update_book(self, file_path: str, custom_source_url: Optional[str] = None) -> bool:
        """
        Performs incremental update on a local novel file.
        """
        print("=" * 65)
        print("⚡ 【IncrementalNovelUpdater 本地小说智能续更引擎】")
        print(f"📁 目标文件: {file_path}")
        print("=" * 65)

        book_name, author, last_num, last_title, base_text = self.analyze_local_file(file_path)
        print(f"📖 识别书籍: 《{book_name}》 (作者: {author})")
        print(f"📍 本地已存最新章节: [第 {int(last_num)} 章] {last_title}")

        # 1. Discover or probe latest source catalog
        if custom_source_url:
            source_url = custom_source_url
            print(f"🔗 使用指定的自定义书源: {source_url}")
            meta, all_chaps = await self.catalog_extractor.discover_catalog(source_url)
        else:
            cached = self.universal_engine.source_cache.get(book_name)
            if cached and cached.get("catalog_url"):
                source_url = cached["catalog_url"]
                print(f"⚡ [Cache 命中] 正在直连已知优质书源: {source_url} ...")
                meta, all_chaps = await self.catalog_extractor.discover_catalog(source_url)
            else:
                print(f"🔎 正在全网检索《{book_name}》的最优全本目录...")
                candidates = await self.universal_engine.find_authentic_catalog_candidates(book_name)
                best_url = ""
                best_chaps = []
                best_meta = {}
                for cand in candidates[:10]:
                    try:
                        m_c, c_c = await self.catalog_extractor.discover_catalog(cand)
                        if c_c and len(c_c) > len(best_chaps):
                            is_usable = await self.universal_engine.probe_catalog_usability(book_name, cand, c_c)
                            if is_usable:
                                best_url = cand
                                best_chaps = c_c
                                best_meta = m_c
                    except Exception:
                        continue
                source_url = best_url
                all_chaps = best_chaps
                meta = best_meta

        if not all_chaps:
            print("❌ 未能在网络中找到该书的有效目录源。")
            return False

        # Filter new chapters
        new_chaps = [c for c in all_chaps if c[3] > last_num]
        if not new_chaps:
            print(f"\n✅ 《{book_name}》目前已是全网最新版本，暂无新增章节！")
            return True

        print(f"\n🚀 发现 {len(new_chaps)} 个新章节 (第 {int(new_chaps[0][3])} 章 ~ 第 {int(new_chaps[-1][3])} 章):")
        for c in new_chaps[:10]:
            print(f"  - [{int(c[3])}] {c[1]}")
        if len(new_chaps) > 10:
            print(f"  ... 以及其余 {len(new_chaps)-10} 个章节")

        # 2. Fetch new chapters concurrently
        semaphore = asyncio.Semaphore(self.concurrency)
        appended_blocks = []

        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
            verify=False,
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=20)
        ) as client:
            for idx, title, url, num in new_chaps:
                clean_title = re.sub(r'【.*?】', '', title).strip()
                print(f"📥 正在拉取 [{int(num)}] {clean_title[:20]} ...", flush=True)
                fetched = False
                for attempt in range(3):
                    try:
                        resp = await client.get(url, headers={'Referer': url})
                        if resp.status_code == 200:
                            ch_html = safe_decode_response(resp)
                            raw = self.extractor.extract_article_text(ch_html, url=url)
                            clean = self.pipeline.clean_text(raw, chapter_title=clean_title, source_url=url)
                            if len(clean) >= 200:
                                block = f"\n\n{clean_title}\n\n{clean}"
                                appended_blocks.append((num, block))
                                print(f"  ✓ [{int(num)}] 抓取成功 ({len(clean)} 字)")
                                fetched = True
                                break
                    except Exception:
                        pass
                    await asyncio.sleep(0.3)

                if not fetched:
                    print(f"  ⚠️ [{int(num)}] 章节正文未更新或防爬拦截，暂缺: {clean_title}")

        if not appended_blocks:
            print("⚠️ 未能拉取到任何新增章节正文。")
            return False

        appended_blocks.sort(key=lambda x: x[0])
        full_text = base_text + "".join(b[1] for b in appended_blocks) + "\n"

        # 3. Write back to TXT
        out_txt = file_path if file_path.endswith(".txt") else os.path.splitext(file_path)[0] + ".txt"
        with open(out_txt, "w", encoding="utf-8") as f:
            f.write(full_text)
        print(f"\n🎉 TXT 文件追加更新成功: {out_txt}")

        # 4. Re-compile matching EPUB
        out_epub = os.path.splitext(file_path)[0] + ".epub"
        ch_parts = re.split(r'\n(?=第\s*\d+\s*章)', full_text)
        all_epub_chaps = []
        for p in ch_parts:
            lines = p.strip().split('\n')
            if not lines:
                continue
            head = lines[0].strip()
            body = "\n\n".join(lines[1:])
            if head.startswith("第") and "章" in head:
                all_epub_chaps.append((len(all_epub_chaps) + 1, head, body))

        EpubFormatter.export(
            output_path=out_epub,
            book_meta={"title": book_name, "author": author},
            chapters=all_epub_chaps,
            source_url=source_url
        )
        print(f"🎉 EPUB3 电子书全量重构成功: {out_epub} (共 {len(all_epub_chaps)} 章)！")
        return True
