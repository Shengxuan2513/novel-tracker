"""
Novel Downloader with Multi-Source Fallback Routing and Heuristic Content Extraction.
Orchestrates MasterProbe, FallbackRouter, HeuristicExtractor, and RegexCleaningPipeline.
"""

import asyncio
import os
from typing import List, Optional, Tuple
from urllib.parse import quote
import httpx
from bs4 import BeautifulSoup

from core.exceptions import DataIncompleteError, SourceExhaustedError
from core.heuristic_extractor import HeuristicExtractor
from core.pipeline import RegexCleaningPipeline
from core.fallback_router import FallbackRouter
from core.probe import MasterProbe, ChapterMetadata
from core.chapter_fetcher import fetch_complete_chapter
from core.safe_publish import publish_outputs, capture_states
from pathlib import Path
import re
from core.paths import downloads_dir


class NovelDownloader:
    def __init__(
        self,
        output_dir: Optional[str] = None,
        concurrency: int = 12,
        timeout: float = 10.0,
        min_char_length: int = 500
    ):
        self.output_dir = output_dir or downloads_dir()
        self.concurrency = concurrency
        self.timeout = timeout
        self.probe = MasterProbe(timeout=timeout)
        self.extractor = HeuristicExtractor()
        self.pipeline = RegexCleaningPipeline(min_char_length=min_char_length)
        self.router = FallbackRouter(timeout=timeout, min_char_length=min_char_length)
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }
        os.makedirs(self.output_dir, exist_ok=True)

    async def fetch_single_chapter(
        self,
        client: httpx.AsyncClient,
        novel_name: str,
        chapter: ChapterMetadata,
        semaphore: asyncio.Semaphore
    ) -> Tuple[int, str, str, str]:
        """
        Fetches single chapter content. If primary source is incomplete or errors,
        triggers FallbackRouter to query alternate sources.
        Returns:
            (chapter_index, chapter_title, clean_content, source_status)
        """
        async with semaphore:
            clean_body: Optional[str] = None
            source_info = "主节点"

            # 1. Attempt primary node extraction
            try:
                clean_body = await fetch_complete_chapter(
                    client, chapter.url, chapter.title, self.extractor,
                    min_chars=self.pipeline.min_char_length)
                self.pipeline.validator.validate_and_record(chapter.title, clean_body, chapter.url)
            except (DataIncompleteError, Exception):
                clean_body = None

            # 2. Fallback routing if primary extraction failed or was incomplete
            if not clean_body:
                try:
                    fallback_text, fallback_url = await self.router.fallback_route(
                        novel_name=novel_name,
                        chapter_title=chapter.title
                    )
                    clean_body = await fetch_complete_chapter(
                        client, fallback_url, chapter.title, self.extractor,
                        min_chars=self.pipeline.min_char_length)
                    self.pipeline.validator.validate_and_record(chapter.title, clean_body, fallback_url)
                    source_info = f"降级回源 ({fallback_url[:30]}...)"
                except SourceExhaustedError:
                    clean_body = f"    (全网源站暂未获取到本章完整正文)\n"
                    source_info = "回源耗尽"
                except Exception:
                    clean_body = f"    (抓取异常)\n"
                    source_info = "异常"

            formatted_content = f"\n\n{chapter.title}\n\n{clean_body}\n"
            return chapter.index, chapter.title, formatted_content, source_info

    async def download_novel(
        self,
        novel_name: str,
        catalog_url: str,
        start_chapter: int = 1,
        limit_chapters: Optional[int] = None
    ) -> Optional[str]:
        """
        Downloads novel chapters using MasterProbe + FallbackRouter architecture.
        """
        initial = capture_states([os.path.join(self.output_dir, name) for name in os.listdir(self.output_dir)
                                  if os.path.isfile(os.path.join(self.output_dir, name))])
        print(f"📡 [MasterProbe] 正在探测目录元数据: {catalog_url} ...")
        chapters = await self.probe.probe_catalog(catalog_url)

        if not chapters:
            print(f"⚠️ [MasterProbe] 未能从 {catalog_url} 获取到章节元数据。")
            return None

        chapters_to_download = [ch for ch in chapters if ch.index >= start_chapter]
        if limit_chapters:
            chapters_to_download = chapters_to_download[:limit_chapters]

        total = len(chapters_to_download)
        if not total:
            print("⚠️ 指定范围内没有章节，已有文件未修改。")
            return None
        print(f"📚 [Scheduler] 已就绪 {len(chapters)} 章元数据，准备调度下载 {total} 章完整正文...")

        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", novel_name).rstrip(". ") or "未命名小说"
        suffix = ""
        if start_chapter > 1 or limit_chapters is not None:
            suffix = f"（章节范围{start_chapter}-{chapters_to_download[-1].index}）"
        output_filename = f"《{safe_name}》{suffix}.txt"
        output_file_path = os.path.join(self.output_dir, output_filename)

        semaphore = asyncio.Semaphore(self.concurrency)
        results = []
        fallback_count = 0

        async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True, verify=False) as client:
            tasks = [
                self.fetch_single_chapter(client, novel_name, ch, semaphore)
                for ch in chapters_to_download
            ]

            completed = 0
            for f in asyncio.as_completed(tasks):
                res = await f
                results.append(res)
                completed += 1
                if "降级" in res[3]:
                    fallback_count += 1
                percent = (completed / total) * 100
                print(f"\r📥 采集进度: [{completed}/{total}] {percent:.1f}% [{res[3]}] ({res[1][:18]}...)", end="", flush=True)

        print(f"\n\n💾 采集完毕 (共触发 {fallback_count} 次多源降级回源)，正在规范化合并至落盘文件...")
        results.sort(key=lambda x: x[0])
        failures = sum(row[3] in ("异常", "回源耗尽") for row in results)
        if failures == len(results):
            print("❌ 未取得有效正文，已有文件未修改。")
            return None
        if failures:
            output_file_path = os.path.splitext(output_file_path)[0] + "（未完整）.txt"
            print(f"⚠️ 部分完成：仍有 {failures} 章暂缺，结果另存，不覆盖完整版本。")
        expected = {str(Path(output_file_path).resolve()): initial.get(str(Path(output_file_path).resolve()))}

        with publish_outputs([output_file_path], expected=expected) as staged:
            with open(staged[str(Path(output_file_path).resolve())], "w", encoding="utf-8") as f:
                f.write(f"《{novel_name}》\n\n")
                label = "未完整，含暂缺章节" if failures else "正文导出版"
                f.write(f"【{label}】共 {len(results)} 章\n")
                f.write(f"主索引源: {catalog_url}\n")
                f.write("=" * 60 + "\n\n")
                for _, _, content, _ in results:
                    f.write(content + "\n")

        print(f"🎉 规范化文本已成功落盘至: {output_file_path}")
        return output_file_path
