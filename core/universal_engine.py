"""
Universal Novel Extractor and Pipeline Orchestrator with Self-Healing Architecture.
Coordinates URL classification, heuristic and rule-based catalog discovery, candidate discovery,
search redirect decryption, deep-water pre-fetch probing, parallel chapter fetching,
chapter-level chunked storage, incremental updates, multi-source stitching,
and EPUB/TXT/JSON formatting.
"""

import asyncio
import os
import re
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from core.url_classifier import URLClassifier, InputType
from core.heuristic_catalog import HeuristicCatalogExtractor
from core.chain_crawler import ChainedChapterCrawler
from core.rule_extractor import DualTrackExtractor
from core.pipeline import RegexCleaningPipeline
from core.fallback_router import FallbackRouter, DomainStrategy
from core.formatters import TxtFormatter, JsonFormatter, EpubFormatter
from core.source_cache import SourceCache
from core.redirect_resolver import RedirectResolver
from core.chapter_storage import ChapterStorage
from core.chapter_fetcher import fetch_complete_chapter
from core.safe_publish import capture_states, publish_outputs
from pathlib import Path
from core.paths import downloads_dir


class UniversalNovelExtractor:
    def __init__(
        self,
        output_dir: Optional[str] = None,
        concurrency: int = 12,
        timeout: float = 10.0,
        min_char_length: int = 400
    ):
        self.output_dir = output_dir or downloads_dir()
        if type(concurrency) is not int or concurrency < 1:
            raise ValueError("并发数必须是正整数。")
        self.concurrency = concurrency
        self.timeout = timeout
        self.classifier = URLClassifier(timeout=timeout)
        self.catalog_extractor = HeuristicCatalogExtractor(timeout=timeout)
        self.chain_crawler = ChainedChapterCrawler(timeout=timeout, min_char_length=min_char_length)
        self.extractor = DualTrackExtractor()
        self.pipeline = RegexCleaningPipeline(min_char_length=min_char_length)
        self.router = FallbackRouter(timeout=timeout, min_char_length=min_char_length)
        self.source_cache = SourceCache()
        self.resolver = RedirectResolver(timeout=timeout)
        self.storage = ChapterStorage()
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

    async def find_authentic_catalog_candidates(self, book_name: str) -> List[str]:
        """
        Searches across DirectSiteSearchHub, SourceManager, and multi-engine SERP,
        decrypts search redirects, and applies domain strategy filtering.
        """
        raw_candidates: List[str] = []

        # 1. First priority: Direct novel site search endpoints
        try:
            from core.direct_site_search import DirectSiteSearchHub
            hub = DirectSiteSearchHub(timeout=self.timeout)
            direct_hits = await hub.search_all_direct_sites(book_name)
            for url in direct_hits:
                if url and url not in raw_candidates:
                    raw_candidates.append(url)
        except Exception:
            pass

        # 2. Second priority: Multi-source search manager
        try:
            from sources.manager import SourceManager
            sm = SourceManager(timeout=self.timeout)
            _, all_res = await sm.search_novel(book_name)
            for r in all_res:
                if r.book_url and r.book_url not in raw_candidates:
                    raw_candidates.append(r.book_url)
                if r.latest_chapter_url and r.latest_chapter_url not in raw_candidates:
                    raw_candidates.append(r.latest_chapter_url)
        except Exception:
            pass

        # 3. Third priority: Multi-Engine Fallback SERP search
        search_queries = [
            f"{book_name} 目录",
            f"{book_name} 最新章节",
            f"{book_name} 笔趣阁 目录",
            f"{book_name} 章节列表"
        ]

        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
            verify=False
        ) as client:
            for q in search_queries:
                encoded_q = urllib.parse.quote(q)

                # 360 Search endpoint
                try:
                    so_url = f"https://www.so.com/s?q={encoded_q}"
                    resp = await client.get(so_url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for a in soup.select(".res-list h3 a"):
                            j_url = a.get("href", "")
                            if j_url and j_url not in raw_candidates:
                                raw_candidates.append(j_url)
                except Exception:
                    pass

                # Baidu search endpoint
                try:
                    baidu_url = f"https://www.baidu.com/s?wd={encoded_q}&rn=10"
                    resp = await client.get(baidu_url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for a in soup.select(".result h3 a, .c-container h3 a"):
                            href = a.get("href", "")
                            if href and href.startswith("http") and href not in raw_candidates:
                                raw_candidates.append(href)
                except Exception:
                    pass

                # DuckDuckGo HTML endpoint
                try:
                    url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for a in soup.select(".results .result__url"):
                            href = a.get_text(strip=True)
                            if not href.startswith("http"):
                                href = f"https://{href}"
                            if href not in raw_candidates:
                                raw_candidates.append(href)
                except Exception:
                    pass

                # Bing search endpoint
                try:
                    bing_url = f"https://cn.bing.com/search?q={encoded_q}&setlang=zh-Hans"
                    resp = await client.get(bing_url)
                    if resp.status_code == 200:
                        soup = BeautifulSoup(resp.text, "html.parser")
                        for a in soup.select("#b_results .b_algo h2 a[href]"):
                            href = a["href"].strip()
                            if href.startswith("http") and href not in raw_candidates:
                                raw_candidates.append(href)
                except Exception:
                    pass

        # Phase 1: Decrypt and resolve all search engine redirect links before blacklisting
        resolved_candidates = await self.resolver.resolve_all(raw_candidates, concurrency=12)

        # Apply domain strategy filtering and scoring on canonical URLs
        return DomainStrategy.filter_and_sort_candidates(resolved_candidates)

    async def probe_catalog_usability(
        self,
        novel_name: str,
        catalog_url: str,
        chap_list: List[Tuple[int, str, str, float]]
    ) -> bool:
        """
        Deep-water pre-fetch usability probe.
        Samples chapters in the 75%, 85%, and 95% deep VIP zone to verify
        that the catalog is a genuine readable source rather than a VIP paywalled/truncated source.
        """
        if not chap_list or len(chap_list) < 3:
            return False

        # Target deep-water chapters where VIP locks usually happen
        if len(chap_list) >= 10:
            sample_indices = [
                int(len(chap_list) * 0.75),
                int(len(chap_list) * 0.85),
                int(len(chap_list) * 0.95)
            ]
        else:
            sample_indices = [0, len(chap_list) // 2, len(chap_list) - 1]

        sample_indices = sorted(list(set(sample_indices)))
        sample_chaps = [chap_list[i] for i in sample_indices if i < len(chap_list)]

        valid_count = 0
        semaphore = asyncio.Semaphore(3)
        for idx, title, url, _ in sample_chaps:
            try:
                _, _, content = await self.fetch_single_chapter(
                    novel_name=novel_name,
                    chap_index=idx,
                    chap_title=title,
                    chap_url=url,
                    semaphore=semaphore,
                    log_callback=None,
                    persist=False
                )
                if content and len(content) >= 350:
                    # Check for paywall keywords
                    if not any(k in content for k in ("VIP", "开通会员", "请购买后阅读", "防爬拦截", "暂缺")):
                        valid_count += 1
            except Exception:
                pass

        # At least 2 out of 3 deep-water chapters must pass
        return valid_count >= max(1, len(sample_chaps) - 1)

    async def fetch_single_chapter(
        self, novel_name, chap_index, chap_title, chap_url, semaphore,
        log_callback=None, persist=True, client=None, book_author=""
    ):
        """Use the same complete-chapter reader for downloads, updates and repair."""
        async with semaphore:
            if persist and book_author and book_author != "未知":
                cached = self.storage.get_chapter(novel_name, chap_index, book_author)
                if cached and self.storage.valid(cached, chap_title, self.pipeline.min_char_length):
                    return (chap_index, cached.get("title", chap_title), cached["content"])
            own_client = client is None
            c = client or httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True)
            try:
                content = None
                source = chap_url
                for attempt in range(3):
                    try:
                        content = await fetch_complete_chapter(
                            c, chap_url, chap_title, self.extractor,
                            min_chars=self.pipeline.min_char_length)
                        self.pipeline.validator.validate_and_record(chap_title, content, chap_url)
                        break
                    except Exception:
                        content = None
                        if attempt < 2:
                            await asyncio.sleep(0.3 * (attempt + 1))
                if content is None:
                    try:
                        _, fallback_url = await self.router.fallback_route(
                            novel_name=novel_name, chapter_title=chap_title)
                        if fallback_url:
                            # First-page text alone is not proof of completeness.
                            content = await fetch_complete_chapter(
                                c, fallback_url, chap_title, self.extractor,
                                min_chars=self.pipeline.min_char_length)
                            self.pipeline.validator.validate_and_record(chap_title, content, fallback_url)
                            source = fallback_url
                    except Exception:
                        content = None
                if content is not None:
                    if persist:
                        self.storage.save_chapter(
                            book_name=novel_name, index=chap_index, title=chap_title,
                            content=content, url=source,
                            source_domain=urllib.parse.urlparse(source).netloc, complete=True, author=book_author)
                    if log_callback:
                        await log_callback(f"  ✓ [{chap_index}] 提取完整: {chap_title[:20]}")
                    return (chap_index, chap_title, content)
            finally:
                if own_client:
                    await c.aclose()
            return (chap_index, chap_title, f"【本章《{chap_title}》抓取异常或分页不完整，暂缺】")

    async def audit_and_heal_chapters(
        self,
        novel_name: str,
        chapters_data: List[Tuple[int, str, str]],
        semaphore: asyncio.Semaphore,
        log_callback: Optional[callable] = None,
        book_author: str = ""
    ) -> Tuple[List[Tuple[int, str, str]], float]:
        """
        Audits chapters_data for missing/incomplete chapters and triggers targeted cross-source fallback healing.
        """
        if not chapters_data:
            return [], 1.0

        failed_items = []
        for i, (idx, title, content) in enumerate(chapters_data):
            if not content or len(content) < 150 or "暂缺" in content or "抓取异常" in content:
                failed_items.append((i, idx, title))

        defect_rate = len(failed_items) / len(chapters_data)
        if not failed_items:
            return chapters_data, 0.0

        if log_callback:
            await log_callback(f"\n🩺 [差额审计] 发现 {len(failed_items)} 章正文缺失 (缺失率 {defect_rate*100:.1f}%)，启动第二轮镜像差额定向自愈...")

        async def _heal_one(arr_idx: int, c_idx: int, c_title: str):
            cached = self.storage.get_chapter(novel_name, c_idx, book_author) or {}
            _, _, content = await self.fetch_single_chapter(
                novel_name, c_idx, c_title, cached.get("url", ""), semaphore, persist=True, book_author=book_author)
            if "暂缺" not in content and "抓取异常" not in content:
                chapters_data[arr_idx] = (c_idx, c_title, content)

        heal_tasks = [_heal_one(arr_idx, c_idx, c_title) for arr_idx, c_idx, c_title in failed_items]
        await asyncio.gather(*heal_tasks, return_exceptions=True)

        remaining_failed = sum(1 for _, _, content in chapters_data if not content or len(content) < 150 or "暂缺" in content)
        final_defect_rate = remaining_failed / len(chapters_data)
        if log_callback:
            recovered = len(failed_items) - remaining_failed
            await log_callback(f"🏁 [自愈完成] 成功补齐 {recovered}/{len(failed_items)} 章，最终缺失率: {final_defect_rate*100:.1f}%")

        return chapters_data, final_defect_rate

    async def extract(
        self,
        input_target: str,
        formats: Optional[List[str]] = None,
        start_chapter: int = 1,
        limit_chapters: Optional[int] = None,
        custom_output_dir: Optional[str] = None,
        log_callback: Optional[callable] = None
    ) -> Dict[str, str]:
        """
        Main entry point for universal novel extraction with incremental caching and multi-source stitching.
        """
        if formats is None:
            formats = ["epub", "txt"]
        if not isinstance(formats, list) or not formats or any(fmt not in ("txt", "epub", "json", "all") for fmt in formats):
            raise ValueError("请选择 txt、epub、json 或 all 导出格式。")
        if "all" in formats:
            formats = ["txt", "epub", "json"]
        if type(start_chapter) is not int or start_chapter < 1 or (limit_chapters is not None and (type(limit_chapters) is not int or limit_chapters < 1)):
            raise ValueError("起始章节和章节数量必须是正整数。")

        out_dir = custom_output_dir or self.output_dir
        os.makedirs(out_dir, exist_ok=True)

        async def _log(msg: str):
            print(msg, flush=True)
            if log_callback:
                try:
                    if asyncio.iscoroutinefunction(log_callback):
                        await log_callback(msg)
                    else:
                        log_callback(msg)
                except Exception:
                    pass

        await _log("=" * 65)
        await _log("🌐 【UniversalNovelExtractor 通用小说提取器 2.0】启动")
        await _log(f"🎯 目标输入: {input_target}")
        await _log("=" * 65)

        initial_states = capture_states([os.path.join(out_dir, name) for name in os.listdir(out_dir)
                                         if os.path.isfile(os.path.join(out_dir, name))])
        start_time = time.time()
        input_type, meta_info = await self.classifier.classify(input_target)
        await _log(f"🔍 [Classifier] 识别输入类型: [{input_type.value.upper()}]")

        book_meta = {"title": "未知小说", "author": "未知"}
        chapters_data: List[Tuple[int, str, str]] = []
        source_url = input_target if input_type != InputType.BOOK_NAME else ""
        chap_list = []

        # Case 1: Pure Book Name -> Multi-engine Candidate Discovery
        if input_type == InputType.BOOK_NAME:
            book_name = meta_info.get("book_name", input_target)
            
            # Step 1: Check SourceCache (Persistent Memory)
            cached = self.source_cache.get(book_name)
            if cached and cached.get("catalog_url") and cached.get("status") != "unhealthy":
                cached_url = cached["catalog_url"]
                cached_total = cached.get("total_chapters", 0)
                await _log(f"⚡ [Cache 命中] 正在直连已知优质书源: {cached_url} (记忆库: {cached_total} 章)...")
                try:
                    meta_cand, chaps_cand = await self.catalog_extractor.discover_catalog(cached_url)
                    if chaps_cand and len(chaps_cand) >= max(5, int(cached_total * 0.7)):
                        is_healthy = await self.probe_catalog_usability(book_name, cached_url, chaps_cand)
                        if is_healthy:
                            await _log(f"  ✅ [书源探活成功] 直连锁定最新 {len(chaps_cand)} 章目录 (跳过盲搜耗时)")
                            book_meta = meta_cand
                            if not book_meta.get("title") or book_meta["title"] == "未知小说":
                                book_meta["title"] = book_name
                            chap_list = chaps_cand
                            source_url = cached_url
                except Exception as e:
                    await _log(f"  ⚠️ [Cache 失效] 已知书源访问异常 ({e})，自动触发全网重新检索与自愈...")

            # Step 2: If no cache or cache failed, probe all candidates
            if not chap_list:
                await _log(f"🔎 [Search] 正在全网检索《{book_name}》的可用目录...")
                candidates = await self.find_authentic_catalog_candidates(book_name)
                await _log(f"📋 发现 {len(candidates)} 个解密后的有效书源候选，正在逐一进行真目录与深水区探活校验...")

                best_meta = None
                best_chaps = []
                best_url = ""

                for idx, cand_url in enumerate(candidates[:25], 1):
                    try:
                        meta_cand, chaps_cand = await self.catalog_extractor.discover_catalog(cand_url)
                        if chaps_cand and len(chaps_cand) >= 5:
                            # Deep-water pre-fetch usability probe (75%, 85%, 95%)
                            is_usable = await self.probe_catalog_usability(book_name, cand_url, chaps_cand)
                            if is_usable:
                                await _log(f"  ✅ [有效目录锁定] 候选 #{idx} ({cand_url[:38]}...) 通过深水区可用性校验 ({len(chaps_cand)} 章)")
                                if len(chaps_cand) > len(best_chaps):
                                    best_meta = meta_cand
                                    best_chaps = chaps_cand
                                    best_url = cand_url
                            else:
                                await _log(f"  ⚠️ [探活未通过] 候选 #{idx} ({cand_url[:38]}...) 属于付费截断或防爬源，跳过...")
                    except Exception:
                        continue

                if best_chaps:
                    book_meta = best_meta
                    if not book_meta.get("title") or book_meta["title"] == "未知小说":
                        book_meta["title"] = book_name
                    chap_list = best_chaps
                    source_url = best_url
                    await _log(f"🏆 [锁定最优目录源] 选用包含 {len(chap_list)} 章的高质量源 ({source_url})")
                else:
                    await _log(f"\n❌ 未能在开放网络中匹配到《{book_name}》的有效全本目录。")
                    await _log("💡 建议：请检查书名拼写是否正确，或直接复制该小说在任意网站的目录页/详情页 URL 传入提取！")
                    return {}

        # Case 2: Catalog Page or Book Detail Page -> Heuristic Catalog Extraction
        elif input_type in (InputType.CATALOG_PAGE, InputType.BOOK_DETAIL_PAGE):
            await _log(f"📖 [Catalog] 正在扫描全书目录与分页结构...")
            book_meta, chap_list = await self.catalog_extractor.discover_catalog(
                input_target,
                html_preset=meta_info.get("html")
            )
            if not chap_list:
                await _log(f"\n❌ 该页面未能识别为有效的小说章节目录。")
                return {}

        # Case 3: Single Chapter Page -> Chained Crawler
        elif input_type == InputType.CHAPTER_PAGE:
            await _log(f"🔗 [Chain] 正在沿单章阅读页链式拓扑追溯...")
            book_meta, chapters_data = await self.chain_crawler.crawl_chain(
                input_target,
                start_chapter=start_chapter,
                max_chapters=limit_chapters,
                log_callback=log_callback
            )

        # Fetch chapters with ChapterStorage incremental caching
        if chap_list:
            novel_name_for_tasks = book_meta.get("title") or input_target
            book_author = book_meta.get("author", "")
            target_chaps = [c for c in chap_list if c[0] >= start_chapter]
            if limit_chapters:
                target_chaps = target_chaps[:limit_chapters]

            # Check local chapter-level chunk cache
            cached_indices = self.storage.get_cached_indices(
                novel_name_for_tasks, book_author, target_chaps, self.pipeline.min_char_length) if book_author and book_author != "未知" else set()
            needed_chaps = [c for c in target_chaps if c[0] not in cached_indices]

            if cached_indices:
                hit_count = len(target_chaps) - len(needed_chaps)
                await _log(f"⚡ [增量命中] 本地已命中 {hit_count}/{len(target_chaps)} 章独立分片，仅需增量拉取 {len(needed_chaps)} 章！")
            else:
                await _log(f"📚 共锁定 {len(target_chaps)} 个正文章节，准备并发采集...")

            semaphore = asyncio.Semaphore(self.concurrency)
            fetched_results = []
            if needed_chaps:
                async with httpx.AsyncClient(
                    headers=self.headers,
                    timeout=self.timeout,
                    follow_redirects=True,
                    verify=False,
                    limits=httpx.Limits(max_connections=35, max_keepalive_connections=25)
                ) as shared_client:
                    tasks = [
                        self.fetch_single_chapter(novel_name_for_tasks, idx, title, url, semaphore, log_callback=None, persist=True, client=shared_client, book_author=book_author)
                        for idx, title, url, _ in needed_chaps
                    ]

                    completed = 0
                    total = len(tasks)
                    for coro in asyncio.as_completed(tasks):
                        res = await coro
                        fetched_results.append(res)
                        completed += 1
                        if completed % 10 == 0 or completed == total:
                            pct = completed / total * 100
                            await _log(f"📥 增量进度: [{completed}/{total}] {pct:.1f}% ({res[1][:15]}...)")

            # Failed placeholders remain visible, without becoming complete cache entries.
            cached = {index: (index, title, body) for index, title, body
                      in self.storage.load_all_chapters(novel_name_for_tasks, book_author)}
            cached.update({row[0]: row for row in fetched_results})
            chapters_data = [cached.get(index, (index, title, "【暂缺】"))
                             for index, title, url, number in target_chaps]

            # Audit & Self-Healing Gap Filling
            chapters_data, defect_rate = await self.audit_and_heal_chapters(
                novel_name=novel_name_for_tasks,
                chapters_data=chapters_data,
                semaphore=semaphore,
                log_callback=_log,
                book_author=book_author
            )

            # Persist to Cache with health rating
            success_rate = (1.0 - defect_rate) * 100.0
            if source_url:
                self.source_cache.set(
                    book_name=novel_name_for_tasks,
                    catalog_url=source_url,
                    total_chapters=len(chap_list),
                    last_chapter_title=chap_list[-1][1] if chap_list else "",
                    author=book_meta.get("author", "未知"),
                    success_rate=success_rate,
                    status="healthy" if defect_rate < 0.2 else "degraded"
                )

        if not chapters_data:
            await _log("\n❌ 未能提取到任何有效章节正文。")
            return {}

        await _log(f"\n💾 采集完毕 (共 {len(chapters_data)} 章)，正在导出指定格式...")
        results = {}

        book_title = book_meta.get("title") or "未命名小说"
        author = book_meta.get("author") or "未知"

        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", book_title).rstrip(". ") or "未命名小说"
        suffix = ""
        if start_chapter > 1 or limit_chapters is not None:
            last_index = max(row[0] for row in chapters_data)
            suffix = f"（章节范围{start_chapter}-{last_index}）"
        failed = [row for row in chapters_data if "暂缺" in row[2] or "抓取异常" in row[2]]
        if failed:
            suffix += "（未完整）"
            book_meta["complete"] = False
            await _log(f"⚠️ 部分完成：仍有 {len(failed)} 章暂缺，未覆盖已有完整版本。")
        if len(failed) == len(chapters_data):
            await _log("❌ 未取得有效正文，已有文件未修改。")
            return {}
        exporters = {"txt": TxtFormatter, "json": JsonFormatter, "epub": EpubFormatter}
        targets = {fmt: str(Path(out_dir, f"《{safe_title}》{suffix}.{fmt}").resolve())
                   for fmt in exporters if fmt in formats}
        if not targets:
            raise ValueError("请至少选择一种有效导出格式。")
        expected = {path: initial_states.get(path) for path in targets.values()}
        with publish_outputs(list(targets.values()), expected=expected) as staged:
            for fmt, path in targets.items():
                exporters[fmt].export(staged[path], book_meta, chapters_data, source_url)
        results.update(targets)
        for fmt, path in targets.items():
            await _log(f"  ✓ [{fmt.upper()} 导出成功] -> {path}")

        elapsed = time.time() - start_time
        status = "⚠️ 提取部分完成，仍有暂缺章节" if failed else "✅ 提取完成"
        await _log(f"\n{status}，耗时 {elapsed:.2f} 秒。\n")
        return results
