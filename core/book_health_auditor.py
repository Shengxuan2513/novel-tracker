"""
Core Novel Health Auditor & Self-Healing Repair Engine.
Scans local novel TXT or EPUB files for quality defects:
- Truncated chapters (length < 300 words)
- Dictionary / lexicon definition pollution (e.g. 1.无；没有：)
- Paywall, VIP truncation, or WeChat cards (e.g. 微信扫码开通会员)
- Missing / discontinuous chapter sequences (e.g. jumps from 979 to 983)
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
from core.formatters import EpubFormatter


class NovelHealthAuditor:
    def __init__(self, min_char_threshold: int = 350):
        self.min_char_threshold = min_char_threshold
        self.catalog_extractor = HeuristicCatalogExtractor()
        self.extractor = DualTrackExtractor()
        self.pipeline = RegexCleaningPipeline(min_char_length=200)

    def audit_file(self, file_path: str) -> Tuple[List[dict], str, str, str]:
        """
        Audits a TXT novel file and returns (defects, book_name, author, full_text).
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        txt_path = file_path
        author = "未知"
        if file_path.lower().endswith(".epub"):
            counterpart_txt = os.path.splitext(file_path)[0] + ".txt"
            if os.path.exists(counterpart_txt):
                txt_path = counterpart_txt
            else:
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

        basename = os.path.splitext(os.path.basename(file_path))[0]
        book_name = basename.replace("《", "").replace("》", "").strip()

        m_auth = re.search(r'作\s*者[：:\s]*([^\s,，。；\n\r<]{1,15})', text[:1000])
        if m_auth:
            author = m_auth.group(1).strip()

        # Split into chapters
        parts = re.split(r'\n(?=第\s*\d+\s*章)', text)
        if len(parts) <= 1:
            raise ValueError("No standard chapter headers found.")

        header_text = parts[0]
        chapters = parts[1:]

        defects = []
        parsed_chapters = []

        last_num = 0
        for idx, ch in enumerate(chapters, 1):
            lines = ch.strip().split("\n")
            head = lines[0].strip()
            body = "\n".join(lines[1:]).strip()

            m = re.search(r'第\s*(\d+)\s*章', head)
            c_num = int(m.group(1)) if m else idx

            # Check sequence continuity
            if last_num > 0 and c_num > last_num + 1:
                defects.append({
                    "type": "GAP_MISSING",
                    "index": idx,
                    "chapter_num": c_num,
                    "title": head,
                    "reason": f"章节序号不连续 (从第 {last_num} 章跳到了第 {c_num} 章，缺失中间章节)"
                })
            last_num = c_num

            # Check defect patterns
            is_bad = False
            reasons = []

            if len(body) < self.min_char_threshold:
                is_bad = True
                reasons.append(f"字数过短 (仅 {len(body)} 字)")

            if any(k in body for k in ("微信扫码", "开通付费会员", "已读到0%", "想法、划线、书签")):
                is_bad = True
                reasons.append("包含付费导流卡片")

            if any(k in body for k in ("屋里没人", "沉没。淹没。", "1.无；没有：", "汉语词典", "在线词典")):
                is_bad = True
                reasons.append("包含字典释义污染")

            if any(k in body for k in ("按回车[Enter]键返回", "上一章 章节目录 下一章", "加入书签方便您下次继续阅读")):
                is_bad = True
                reasons.append("包含网页残缺导航碎片")

            if is_bad:
                defects.append({
                    "type": "CONTENT_DEFECT",
                    "index": idx,
                    "chapter_num": c_num,
                    "title": head,
                    "reason": " / ".join(reasons)
                })

            parsed_chapters.append((c_num, head, body))

        return defects, book_name, author, text

    async def repair_file(self, file_path: str, source_url: Optional[str] = None):
        """
        Audits and auto-repairs defective chapters in-place.
        """
        print("=" * 65)
        print("🩺 【NovelHealthAuditor 小说全文健康体检与自愈引擎】")
        print(f"📁 目标文件: {file_path}")
        print("=" * 65)

        defects, book_name, author, full_text = self.audit_file(file_path)
        print(f"📖 扫描书籍: 《{book_name}》 (作者: {author})")
        print(f"📊 体检结果: 发现 {len(defects)} 处质量缺陷！\n")

        if not defects:
            print("🎉 恭喜！全书所有章节完整无损，无字典污染、无断章截断、无跳章！")
            return

        for d in defects:
            print(f"  ❌ [{d['type']}] [第 {d['chapter_num']} 章] {d['title']} -> {d['reason']}")

        print(f"\n🚀 正在启动全自动网络自愈修复...")

        # Find catalog
        if not source_url:
            from core.universal_engine import UniversalNovelExtractor
            engine = UniversalNovelExtractor()
            cached = engine.source_cache.get(book_name)
            if cached and cached.get("catalog_url"):
                source_url = cached["catalog_url"]
                if author == "未知" and cached.get("author"):
                    author = cached["author"]
            else:
                cands = await engine.find_authentic_catalog_candidates(book_name)
                source_url = cands[0] if cands else ""

        if not source_url:
            print("❌ 未能检索到用于修复的高质量书源，请使用 -s 指定源站目录 URL。")
            return

        print(f"🔗 正在从书源读取对应完整章节: {source_url} ...")
        _, all_chaps = await self.catalog_extractor.discover_catalog(source_url)
        chap_map = {int(c[3]): c for c in all_chaps if c[3] > 0}

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }

        repaired_count = 0
        async with httpx.AsyncClient(headers=headers, timeout=15.0, verify=False) as client:
            for d in defects:
                c_num = d["chapter_num"]
                if c_num not in chap_map:
                    print(f"  ⚠️ 源站未收录第 {c_num} 章，跳过...")
                    continue

                c_info = chap_map[c_num]
                c_url = c_info[2]
                c_title = c_info[1]

                print(f"  📥 正在重新抓取 [第 {c_num} 章] {c_title} ...", flush=True)
                for attempt in range(3):
                    try:
                        resp = await client.get(c_url, headers={'Referer': c_url})
                        if resp.status_code == 200:
                            html = safe_decode_response(resp)
                            raw = self.extractor.extract_article_text(html, url=c_url)
                            clean = self.pipeline.clean_text(raw, chapter_title=c_title, source_url=c_url)
                            if len(clean) >= 200:
                                # Replace in full text
                                old_pattern = rf'第\s*{c_num}\s*章[^\n]*\n.*?(?=\n第\s*\d+\s*章|\Z)'
                                new_block = f"{c_title}\n\n{clean}\n\n"
                                full_text, n = re.subn(old_pattern, new_block, full_text, count=1, flags=re.S)
                                if n > 0:
                                    print(f"    ✓ 修复成功 ({len(clean)} 字)")
                                    repaired_count += 1
                                break
                    except Exception as e:
                        pass
                    await asyncio.sleep(0.3)

        if repaired_count > 0:
            txt_target = file_path if file_path.endswith(".txt") else os.path.splitext(file_path)[0] + ".txt"
            with open(txt_target, "w", encoding="utf-8") as f:
                f.write(full_text)
            print(f"\n🎉 成功就地自愈修复 {repaired_count}/{len(defects)} 个缺陷章节并写回 TXT: {txt_target}！")

            # Re-compile EPUB
            epub_path = os.path.splitext(file_path)[0] + ".epub"
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
                output_path=epub_path,
                book_meta={"title": book_name, "author": author},
                chapters=all_epub_chaps,
                source_url=source_url
            )
            print(f"🎉 同步编译生成修复版 EPUB3 电子书: {epub_path}！")
