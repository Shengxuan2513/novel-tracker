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


class UniversalNovelExtractor:
    def __init__(
        self,
        output_dir: str = "downloads",
        concurrency: int = 12,
        timeout: float = 10.0,
        min_char_length: int = 400
    ):
        self.output_dir = output_dir
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
        self,
        novel_name: str,
        chap_index: int,
        chap_title: str,
        chap_url: str,
        semaphore: asyncio.Semaphore,
        log_callback: Optional[callable] = None,
        persist: bool = True
    ) -> Tuple[int, str, str]:
        """
        Fetches and extracts clean text for a single chapter with dual-track extraction and fallback routing.
        """
        async with semaphore:
            # Check ChapterStorage cache first
            if persist:
                cached = self.storage.get_chapter(novel_name, chap_index)
                if cached and cached.get("content") and len(cached["content"]) >= 200:
                    if "暂缺" not in cached["content"] and "抓取异常" not in cached["content"]:
                        return (chap_index, cached.get("title", chap_title), cached["content"])

            # 1. First attempt: Direct fetch + DualTrackExtractor (Rule or Heuristic)
            try:
                async with httpx.AsyncClient(
                    headers=self.headers,
                    timeout=self.timeout,
                    follow_redirects=True,
                    verify=False
                ) as client:
                    resp = await client.get(chap_url)
                    if resp.status_code == 200:
                        from core.heuristic_catalog import safe_decode_response
                        html = safe_decode_response(resp)

                        raw_text = self.extractor.extract_article_text(html, url=chap_url)
                        clean_text = self.pipeline.clean_text(raw_text, chapter_title=chap_title, source_url=chap_url)
                        if len(clean_text) >= 200 and not any(k in clean_text for k in ("VIP", "开通会员", "购买后阅读")):
                            if persist:
                                self.storage.save_chapter(
                                    book_name=novel_name,
                                    index=chap_index,
                                    title=chap_title,
                                    content=clean_text,
                                    url=chap_url,
                                    source_domain=urllib.parse.urlparse(chap_url).netloc
                                )
                            if log_callback:
                                await log_callback(f"  ✓ [{chap_index}] 提取成功: {chap_title[:20]} ({len(clean_text)} 字)")
                            return (chap_index, chap_title, clean_text)
            except Exception:
                pass

            # 2. Second attempt: Smart fallback router across mirror search
            try:
                fallback_text, fallback_url = await self.router.fallback_route(
                    novel_name=novel_name,
                    chapter_title=chap_title
                )
                if fallback_text and len(fallback_text) >= 200:
                    if persist:
                        self.storage.save_chapter(
                            book_name=novel_name,
                            index=chap_index,
                            title=chap_title,
                            content=fallback_text,
                            url=fallback_url,
                            source_domain=urllib.parse.urlparse(fallback_url).netloc if fallback_url else "mirror"
                        )
                    if log_callback:
                        await log_callback(f"  ✓ [{chap_index}] 备用镜像提取成功: {chap_title[:20]} ({len(fallback_text)} 字)")
                    return (chap_index, chap_title, fallback_text)
            except Exception:
                pass

            # 3. Third attempt: Mark placeholder
            fail_text = f"【本章《{chap_title}》抓取异常或源站防爬拦截，暂缺】\n"
            if log_callback:
                await log_callback(f"  ✗ [{chap_index}] 提取失败/内容过短: {chap_title[:20]}")
            return (chap_index, chap_title, fail_text)

    async def audit_and_heal_chapters(
        self,
        novel_name: str,
        chapters_data: List[Tuple[int, str, str]],
        semaphore: asyncio.Semaphore,
        log_callback: Optional[callable] = None
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
            async with semaphore:
                try:
                    fallback_text, fallback_url = await self.router.fallback_route(
                        novel_name=novel_name,
                        chapter_title=c_title
                    )
                    if fallback_text and len(fallback_text) >= 200:
                        chapters_data[arr_idx] = (c_idx, c_title, fallback_text)
                        self.storage.save_chapter(
                            book_name=novel_name,
                            index=c_idx,
                            title=c_title,
                            content=fallback_text,
                            url=fallback_url,
                            source_domain="fallback_heal"
                        )
                        if log_callback:
                            await log_callback(f"  ✨ [自愈成功] [{c_idx}] {c_title[:18]} ({len(fallback_text)} 字)")
                except Exception:
                    pass

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

        out_dir = custom_output_dir or self.output_dir
        os.makedirs(out_dir, exist_ok=True)

        async def _log(msg: str):
            print(msg)
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
            novel_name_for_tasks = book_meta.get("title", input_target)
            target_chaps = [c for c in chap_list if c[0] >= start_chapter]
            if limit_chapters:
                target_chaps = target_chaps[:limit_chapters]

            # Check local chapter-level chunk cache
            cached_indices = self.storage.get_cached_indices(novel_name_for_tasks)
            needed_chaps = [c for c in target_chaps if c[0] not in cached_indices]

            if cached_indices:
                hit_count = len(target_chaps) - len(needed_chaps)
                await _log(f"⚡ [增量命中] 本地已命中 {hit_count}/{len(target_chaps)} 章独立分片，仅需增量拉取 {len(needed_chaps)} 章！")
            else:
                await _log(f"📚 共锁定 {len(target_chaps)} 个正文章节，准备并发采集...")

            semaphore = asyncio.Semaphore(self.concurrency)
            if needed_chaps:
                tasks = [
                    self.fetch_single_chapter(novel_name_for_tasks, idx, title, url, semaphore, log_callback=None, persist=True)
                    for idx, title, url, _ in needed_chaps
                ]

                completed = 0
                total = len(tasks)
                for coro in asyncio.as_completed(tasks):
                    res = await coro
                    completed += 1
                    if completed % 10 == 0 or completed == total:
                        pct = completed / total * 100
                        await _log(f"📥 增量进度: [{completed}/{total}] {pct:.1f}% ({res[1][:15]}...)")

            # Load all chapters from ChapterStorage
            chapters_data = self.storage.load_all_chapters(novel_name_for_tasks)
            if not chapters_data and needed_chaps:
                # Fallback if storage not ready
                pass

            # Filter chapters to range
            if start_chapter or limit_chapters:
                chapters_data = [c for c in chapters_data if c[0] >= start_chapter]
                if limit_chapters:
                    chapters_data = chapters_data[:limit_chapters]

            # Audit & Self-Healing Gap Filling
            chapters_data, defect_rate = await self.audit_and_heal_chapters(
                novel_name=novel_name_for_tasks,
                chapters_data=chapters_data,
                semaphore=semaphore,
                log_callback=_log
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

        book_title = book_meta.get("title", "未命名小说")
        author = book_meta.get("author", "未知")

        if "txt" in formats:
            txt_path = os.path.join(out_dir, f"《{book_title}》.txt")
            TxtFormatter.export(txt_path, book_meta, chapters_data, source_url)
            results["txt"] = txt_path
            await _log(f"  📄 [TXT 导出成功] -> {txt_path}")

        if "json" in formats:
            json_path = os.path.join(out_dir, f"《{book_title}》.json")
            JsonFormatter.export(json_path, book_meta, chapters_data, source_url)
            results["json"] = json_path
            await _log(f"  📦 [JSON 导出成功] -> {json_path}")

        if "epub" in formats:
            epub_path = os.path.join(out_dir, f"《{book_title}》.epub")
            EpubFormatter.export(epub_path, book_meta, chapters_data, source_url)
            results["epub"] = epub_path
            await _log(f"  📚 [EPUB 导出成功] -> {epub_path}")

        elapsed = time.time() - start_time
        await _log(f"\n🎉 全流程提取完成！耗时 {elapsed:.2f} 秒。\n")
        return results
